"""Variant endpoints: search, region query, detail, export.

All endpoints accept an ``assembly`` parameter (never hardcoded).
Pagination is cursor-based (base64 keyset).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...core.public_ids import normalize_public_id
from ...core.security import RoleName
from ...core.task_contract import EXPORT_VARIANTS_TASK
from ...models.variant import MutantLine
from ...schemas.variant import (
    ConsequenceType,
    ExportRequest,
    ExportResponse,
    ImpactLevel,
    VariantDetail,
    VariantFilterParams,
    VariantListResponse,
    VariantResponse,
    VariantType,
)
from ...services.outbox_service import enqueue_task_event
from ...services.release_context import ReleaseContext, get_release_context
from ...services.variant_service import VariantService
from .deps import require_role

router = APIRouter(prefix="/variants", tags=["variants"])
service = VariantService()


#: A public mutant id is the ``SM`` prefix plus a Crockford-Base32 body.
#: The length is deliberately not pinned: the issuance scheme owns that number
#: (see ``core/public_ids.py``), and a fixed width here would start rejecting
#: legitimately issued ids the moment the scheme changes.
_PUBLIC_ID_PREFIX = "SM"
_CROCKFORD_BODY = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _looks_like_public_id(value: str) -> bool:
    """True when *value* is shaped like a public mutant identifier.

    Used to reject internal/numeric locators at the API boundary *before* any
    lookup: a numeric value must fail as invalid input, not as "no such line"
    (which would confirm nothing about existence but still accept the wrong
    identifier class).
    """
    candidate = normalize_public_id(value)
    if not candidate.startswith(_PUBLIC_ID_PREFIX):
        return False
    body = candidate[len(_PUBLIC_ID_PREFIX):]
    if not body:
        return False
    return all(char in _CROCKFORD_BODY for char in body)


async def _resolve_mutant_line_key(
    db: AsyncSession,
    public_id: str,
    *,
    release_context: ReleaseContext,
) -> int:
    """Resolve a public mutant id to its internal key within the release.

    The variant projection stores the internal surrogate, so the translation has
    to happen server-side. A value that is not a public id is rejected outright;
    a public id with no visible line in the resolved release is a 404.
    """
    if not _looks_like_public_id(public_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "mutant_line_public_id must be a public identifier such as "
                "SM7QF3Z9P2A; internal/numeric identifiers are not accepted."
            ),
        )

    result = await db.execute(
        select(MutantLine.id).where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            MutantLine.is_deleted.is_(False),
            MutantLine.is_public.is_(True),
            MutantLine.release_id == release_context.release_id,
        )
    )
    line_id = result.scalar_one_or_none()
    if line_id is None:
        raise NotFoundError(f"Mutant line {public_id} not found")
    return int(line_id)


@router.get("", response_model=VariantListResponse)
async def list_variants(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly: str | None = Query(default=None),
    chromosome: str | None = Query(default=None),
    start: int | None = Query(default=None, ge=0),
    end: int | None = Query(default=None, ge=0),
    ref: str | None = Query(default=None, min_length=1, max_length=4096),
    alt: str | None = Query(default=None, min_length=1, max_length=4096),
    gene_id: str | None = Query(default=None),
    mutant_line_public_id: str | None = Query(
        default=None,
        description=(
            "Public mutant-line identifier (e.g. SM7QF3Z9P2A). Resolved to the "
            "line's internal key server-side; a numeric/internal id is rejected."
        ),
    ),
    # Legacy alias kept so an existing deep link keeps working; it accepts the
    # same *public* identifier and never a numeric/internal key.
    mutant_line_id: str | None = Query(default=None, include_in_schema=False),
    variant_type: VariantType | None = Query(default=None),
    consequence: ConsequenceType | None = Query(default=None),
    impact: ImpactLevel | None = Query(default=None),
    min_af: float | None = Query(default=None, ge=0.0, le=1.0),
    max_af: float | None = Query(default=None, ge=0.0, le=1.0),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> VariantListResponse:
    """Search variants with filters and cursor pagination (limit ≤ 200).

    The mutant-line filter takes a **public** identifier. It is resolved to the
    line's internal key inside the resolved published release, so a numeric or
    otherwise internal value is rejected instead of being bound to ClickHouse as
    if it were a surrogate (which previously matched nothing, or silently
    nothing, depending on the value).
    """
    requested_public_id = mutant_line_public_id or mutant_line_id
    try:
        params = VariantFilterParams(
        assembly=assembly,
        chromosome=chromosome,
        start=start,
        end=end,
        ref=ref,
        alt=alt,
        gene_id=gene_id,
        variant_type=variant_type,
        consequence=consequence,
        impact=impact,
        min_af=min_af,
        max_af=max_af,
        cursor=cursor,
        limit=limit,
    )
    except ValueError as exc:
        # An unknown filter value is client input, not a server error.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if requested_public_id:
        params.mutant_line_id = await _resolve_mutant_line_key(
            db, requested_public_id, release_context=release_context
        )

    return await service.list_variants(
        db,
        params,
        release_context=release_context,
    )


@router.get("/region", response_model=list[VariantResponse])
async def get_variants_by_region(
    release_context: ReleaseContext = Depends(get_release_context),
    assembly: str = Query(..., description="Assembly name (required)"),
    chromosome: str = Query(...),
    start: int = Query(..., ge=1),
    end: int = Query(..., ge=1),
    max_results: int = Query(default=1000, ge=1, le=10000),
) -> list[VariantResponse]:
    """Query variants in a genomic region (assembly is required)."""
    if end < start:
        raise ValidationError("end must be greater than or equal to start")
    return await service.get_variants_by_region(
        assembly=assembly,
        chromosome=chromosome,
        start=start,
        end=end,
        max_results=max_results,
        release_context=release_context,
    )


@router.get("/{variant_id}", response_model=VariantDetail)
async def get_variant(
    variant_id: str,
    release_context: ReleaseContext = Depends(get_release_context),
) -> VariantDetail:
    """Get variant detail by ID."""
    return await service.get_variant(
        variant_id,
        release_context=release_context,
    )


@router.post(
    "/export",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(RoleName.RESEARCHER))],
)
async def export_variants(
    request: ExportRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> ExportResponse:
    """Submit an asynchronous export job (vcf/tsv/csv/json/bed)."""
    export_id = str(uuid.uuid4())
    filters = request.filters.model_dump(
        mode="json", exclude_none=True, exclude={"cursor", "limit"}
    )
    filters["release_key"] = release_context.release_key
    # Exports have no persistence model of their own, so this event is the
    # durable command record. The dispatcher owns all broker I/O after commit.
    await enqueue_task_event(
        db,
        event_type="variant_export_requested",
        aggregate_type="variant_export",
        aggregate_id=export_id,
        task_name=EXPORT_VARIANTS_TASK,
        kwargs={
            "export_id": export_id,
            "filters": filters,
            "format": request.format,
            "compress": request.compress,
        },
    )
    await db.commit()

    return ExportResponse(
        export_id=export_id,
        status="pending",
        message="Export job submitted",
    )

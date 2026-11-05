"""Variant endpoints: search, region query, detail, export.

All endpoints accept an ``assembly`` parameter (never hardcoded).
Pagination is cursor-based (base64 keyset).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...core.public_ids import normalize_public_id
from ...core.security import RoleName
from ...core.task_contract import EXPORT_VARIANTS_TASK
from ...models.auth import User
from ...models.variant import MutantLine
from ...models.variant_facts import variant_facts
from ...schemas.error import ValidationErrorResponse
from ...schemas.variant import (
    MAX_ASSEMBLY_KEY_LENGTH,
    ConsequenceType,
    ExportDownloadResponse,
    ExportManifestResponse,
    ExportRequest,
    ExportResponse,
    ExportStatusResponse,
    ImpactLevel,
    VariantDetail,
    VariantFilterParams,
    VariantListResponse,
    VariantResponse,
    VariantType,
)
from ...services.outbox_service import enqueue_task_event
from ...services.release_context import ReleaseContext, get_release_context
from ...services.variant_export_service import VariantExportService
from ...services.variant_service import VariantService
from .deps import get_user_roles, require_role

router = APIRouter(prefix="/variants", tags=["variants"])
service = VariantService()
export_service = VariantExportService()


def _private(response: Response) -> None:
    """Owner-scoped answers must never enter a shared cache.

    The status body is the submitter's own record and the download body
    carries a signed URL; both are private to one account.
    """
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


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


async def _resolve_mutant_line_name(
    db: AsyncSession,
    public_id: str,
    *,
    release_context: ReleaseContext,
) -> str:
    """Resolve a public id to the fact's name inside the visible release.

    Historical variant surrogates are hashes, not mutant_lines.id foreign keys.
    The release/name relation is also used by the public export query. Names
    stay server-side; callers may supply only a public identifier.
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
        select(MutantLine.name).where(
            func.upper(MutantLine.public_id) == normalize_public_id(public_id),
            MutantLine.is_deleted.is_(False),
            MutantLine.is_public.is_(True),
            MutantLine.release_id == release_context.release_id,
        )
    )
    line_name = result.scalar_one_or_none()
    if line_name is None:
        raise NotFoundError(f"Mutant line {public_id} not found")
    return str(line_name)


def _export_assembly_scope(
    requested: str | None,
    release_context: ReleaseContext,
) -> str:
    """Resolve the single assembly namespace an export artifact is built from.

    v4 and v5 are distinct coordinate namespaces, and one export must never
    mix them: the export record advertises a single ``assembly_key`` and the
    worker constrains its SQL by the assembly the API puts into the filters.
    A search result may be labelled row by row, but a downloaded file is
    read as one file: VCF states its provenance in the header and BED has no
    free metadata field, so neither can carry a per-row assembly label and
    the artifact is a single namespace by construction. (TSV, CSV and JSON
    do repeat the assembly on every row, but the record and the command
    still have to name one namespace, so the export never claims a scope it
    does not use.)

    A named assembly wins. Otherwise the resolved release's own assembly
    scope is used, so a request that names none still exports exactly one
    namespace. When neither exists the request is refused: an export must
    never silently span assembly namespaces while the record advertises a
    single one.

    The resolved name must also fit ``variant_exports.assembly_key``
    (``String(64)``). An over-long name is refused with the same clean 422
    instead of being truncated, dropped or mapped onto another name: the
    request named a value the record cannot store, and guessing what it was
    meant to be would export the wrong namespace.
    """
    candidate = (requested or "").strip() or (release_context.assembly or "").strip()
    if not candidate:
        raise ValidationError(
            "An assembly is required for a variant export: the request named "
            "none and the resolved release declares no assembly scope. An "
            "export must not span assembly namespaces."
        )
    if len(candidate) > MAX_ASSEMBLY_KEY_LENGTH:
        raise ValidationError(
            f"The assembly name is too long for a variant export: at most "
            f"{MAX_ASSEMBLY_KEY_LENGTH} characters are accepted, "
            f"{len(candidate)} were given."
        )
    return candidate


async def _assembly_namespace_exists(
    db: AsyncSession,
    release_id: int,
    assembly: str,
) -> bool:
    """Whether the release actually holds variants in this namespace.

    The namespace of a fact is the assembly key it was imported under, which
    is the assembly's name *or* its version — both vocabularies occur in
    the data. So the question "does this export have anything to export?"
    can only be answered by the facts themselves.

    Without this check a misspelled assembly name produces an export that
    is recorded as ``succeeded`` with zero rows: the record advertises a
    release/assembly pair that does not exist, and the download is an empty
    file. A refused request is the honest answer.
    """
    result = await db.execute(
        select(variant_facts.c.variant_id)
        .where(
            variant_facts.c.release_id == release_id,
            variant_facts.c.assembly_key == assembly,
        )
        .limit(1)
    )
    return result.first() is not None


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
            "Public mutant-line identifier (e.g. SM7QF3Z9P2A). Resolved "
            "server-side within the published release; internal ids are rejected."
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

    The mutant-line filter takes a **public** identifier, resolved to the
    fact's release-scoped line name. A persistence key or historical hash is
    never accepted as a public identifier.
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
        params.mutant_line_name = await _resolve_mutant_line_name(
            db, requested_public_id, release_context=release_context
        )

    # The request-scoped session is passed on: the service reads the page
    # through it, so this request holds one pooled connection, not two.
    return await service.list_variants(
        db,
        params,
        release_context=release_context,
    )


@router.get("/region", response_model=list[VariantResponse])
async def get_variants_by_region(
    db: AsyncSession = Depends(get_db),
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
        db,
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


async def _submit_export(
    db: AsyncSession,
    *,
    export_request: ExportRequest,
    release_context: ReleaseContext,
    current_user: User,
) -> uuid.UUID:
    """Record one export request and queue it — the only place that does so.

    Both ``POST /variants/export`` and ``POST /exports/query`` call this.
    Splitting it (resolving filters here, writing the record and the outbox
    event at each call site) would be two places where release scoping,
    assembly resolution, provenance and the command payload could drift
    apart, and the query builder would quietly gain its own semantics.
    Returns the new export id; the caller commits.
    """
    filters = export_request.filters.model_dump(
        mode="json", exclude_none=True,
        exclude={"cursor", "limit", "mutant_line_public_id"},
    )
    if export_request.filters.mutant_line_public_id is not None:
        filters["mutant_line_name"] = await _resolve_mutant_line_name(
            db, export_request.filters.mutant_line_public_id,
            release_context=release_context,
        )
    filters["release_key"] = release_context.release_key
    # One namespace per artifact. The effective assembly is written into the
    # filters the worker receives, so the worker's SQL, the artifact's
    # provenance and the export record all state the same assembly instead
    # of the record advertising a namespace the file does not use.
    assembly_scope = _export_assembly_scope(
        export_request.filters.assembly, release_context
    )
    # An artifact that would contain no rows must not be recorded as a
    # successful export: the request is refused instead, so the submitter
    # learns that the namespace is empty rather than downloading an empty
    # file that claims to be the release's data.
    if not await _assembly_namespace_exists(
        db, release_context.release_id, assembly_scope
    ):
        raise ValidationError(
            f"No variants are published for assembly {assembly_scope!r} in this "
            "release. The export was refused: an artifact with no rows would "
            "claim a namespace the release does not have."
        )
    filters["assembly"] = assembly_scope

    export_id = uuid.uuid4()
    # The export record is the durable, owner-visible state of the request;
    # it is written in the same transaction as the outbox event, so a
    # committed request always has both the command and the record.
    # ``assembly_key`` records the assembly the *artifact* is built from
    # (the resolved one), not merely the release default, so the status
    # endpoint cannot advertise a namespace the file does not use.
    await export_service.create_record(
        db,
        export_id=export_id,
        user_id=current_user.id,
        release_key=release_context.release_key,
        assembly_key=assembly_scope,
        export_format=export_request.format,
        compress=export_request.compress,
        filters=filters,
    )
    # The dispatcher owns all broker I/O after commit.
    await enqueue_task_event(
        db,
        event_type="variant_export_requested",
        aggregate_type="variant_export",
        aggregate_id=str(export_id),
        task_name=EXPORT_VARIANTS_TASK,
        kwargs={
            "export_id": str(export_id),
            "filters": filters,
            "format": export_request.format,
            "compress": export_request.compress,
        },
    )
    return export_id


@router.post(
    "/export",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        422: {
            "model": ValidationErrorResponse,
            "description": (
                "Validation Error. The export is refused and nothing is "
                "queued, either because the request body failed schema "
                "validation (field-level ``errors`` are listed) or because the "
                "request could not be bound to exactly one assembly "
                "namespace: no assembly was named and the resolved release "
                "declares no scope, the resolved assembly name is longer "
                f"than the export record can store (at most "
                f"{MAX_ASSEMBLY_KEY_LENGTH} characters), or the resolved "
                "release publishes no variants in that assembly namespace. "
                "A domain refusal carries the unified envelope with "
                "``error.code`` ``validation_error`` and no ``errors`` list."
            ),
        },
    },
)
async def export_variants(
    request: ExportRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(require_role(RoleName.RESEARCHER)),
) -> ExportResponse:
    """Submit an asynchronous export job (vcf/tsv/csv/json/bed).

    The job is bound to exactly one assembly namespace: a named assembly
    wins, otherwise the resolved release's own assembly scope is used, and a
    request with neither is refused. See ``filters.assembly`` for the exact
    rule and its limits.
    """
    export_id = await _submit_export(
        db,
        export_request=request,
        release_context=release_context,
        current_user=current_user,
    )
    await db.commit()

    return ExportResponse(
        export_id=str(export_id),
        status="pending",
        message="Export job submitted",
    )


@router.get("/export/{export_id}", response_model=ExportStatusResponse)
async def get_variant_export_status(
    export_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(RoleName.RESEARCHER)),
) -> ExportStatusResponse:
    """Return the state of one export (submitter or administrator only)."""
    _private(response)
    return await export_service.get_status(
        db,
        export_id,
        user_id=current_user.id,
        user_roles=get_user_roles(current_user),
    )


@router.get(
    "/export/{export_id}/manifest",
    response_model=ExportManifestResponse,
)
async def get_variant_export_manifest(
    export_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(RoleName.RESEARCHER)),
) -> ExportManifestResponse:
    """Return citable provenance for one export (submitter or administrator).

    A legacy artifact with no checksum is reported with ``sha256: null`` and
    ``sha256_state='not_recorded'``; the response never invents a digest.
    """
    _private(response)
    return await export_service.get_manifest(
        db,
        export_id,
        user_id=current_user.id,
        user_roles=get_user_roles(current_user),
    )


@router.get("/export/{export_id}/download", response_model=ExportDownloadResponse)
async def get_variant_export_download(
    export_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(RoleName.RESEARCHER)),
) -> ExportDownloadResponse:
    """Return a short-lived download link for a completed export."""
    _private(response)
    return await export_service.get_download(
        db,
        export_id,
        user_id=current_user.id,
        user_roles=get_user_roles(current_user),
    )

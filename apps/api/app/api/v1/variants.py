"""Variant endpoints: search, region query, detail, export.

All endpoints accept an ``assembly`` parameter (never hardcoded).
Pagination is cursor-based (base64 keyset).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import ValidationError
from ...core.security import RoleName
from ...core.task_contract import EXPORT_VARIANTS_TASK
from ...core.task_dispatch import dispatch_task
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
from ...services.release_context import ReleaseContext, get_release_context
from ...services.variant_service import VariantService
from .deps import require_role

router = APIRouter(prefix="/variants", tags=["variants"])
service = VariantService()


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
    mutant_line_id: str | None = Query(default=None),
    variant_type: VariantType | None = Query(default=None),
    consequence: ConsequenceType | None = Query(default=None),
    impact: ImpactLevel | None = Query(default=None),
    min_af: float | None = Query(default=None, ge=0.0, le=1.0),
    max_af: float | None = Query(default=None, ge=0.0, le=1.0),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
) -> VariantListResponse:
    """Search variants with filters and cursor pagination (limit ≤ 200)."""
    params = VariantFilterParams(
        assembly=assembly,
        chromosome=chromosome,
        start=start,
        end=end,
        ref=ref,
        alt=alt,
        gene_id=gene_id,
        mutant_line_id=mutant_line_id,
        variant_type=variant_type,
        consequence=consequence,
        impact=impact,
        min_af=min_af,
        max_af=max_af,
        cursor=cursor,
        limit=limit,
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
    release_context: ReleaseContext = Depends(get_release_context),
) -> ExportResponse:
    """Submit an asynchronous export job (vcf/tsv/csv/json/bed)."""
    export_id = str(uuid.uuid4())
    filters = request.filters.model_dump(mode="json")
    filters["release_key"] = release_context.release_key
    dispatch_task(
        EXPORT_VARIANTS_TASK,
        identifier=export_id,
        kwargs={
            "export_id": export_id,
            "filters": filters,
            "format": request.format,
            "compress": request.compress,
        },
        queue="export",
    )

    return ExportResponse(
        export_id=export_id,
        status="pending",
        message="Export job submitted",
    )

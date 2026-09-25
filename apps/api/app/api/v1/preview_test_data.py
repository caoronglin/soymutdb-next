"""Loopback-only endpoints for the unpublished local test-data preview."""

from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.database import get_db
from ...schemas.local_test_preview import (
    LocalTestPreviewMeta,
    PreviewGeneSearchResponse,
    PreviewMutationSiteSearchResponse,
)
from ...services.local_test_preview_service import (
    get_preview_meta,
    search_preview_genes,
    search_preview_mutation_sites,
)

router = APIRouter(prefix="/preview/test-data", tags=["local-test-preview"])


def require_local_test_preview(request: Request) -> None:
    """Fail closed unless an opted-in baseline dev API receives a loopback call.

    The TCP peer is used instead of Host, Origin, forwarded headers, or any
    caller-controlled identity claim. A reverse proxy must itself run locally.
    """
    settings = get_settings()
    if (
        not settings.local_test_preview_enabled
        or settings.app_env != "dev"
        or settings.deployment_mode != "baseline"
    ):
        raise HTTPException(status_code=404, detail="Not found")

    peer = request.client
    try:
        is_loopback = peer is not None and ipaddress.ip_address(peer.host).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(status_code=404, detail="Not found")


@router.get(
    "/meta",
    response_model=LocalTestPreviewMeta,
    dependencies=[Depends(require_local_test_preview)],
)
async def preview_meta(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> LocalTestPreviewMeta:
    """Describe the local, unpublished v6 sample and its coordinate space."""
    _private_no_store(response)
    return await get_preview_meta(db)


@router.get(
    "/genes",
    response_model=PreviewGeneSearchResponse,
    dependencies=[Depends(require_local_test_preview)],
)
async def preview_genes(
    response: Response,
    gene_id: str = Query(..., min_length=1, max_length=6400),
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PreviewGeneSearchResponse:
    """Find exact GFF gene accessions within the local v6 draft release."""
    _private_no_store(response)
    return await search_preview_genes(db, gene_id, limit=limit)


@router.get(
    "/mutation-sites",
    response_model=PreviewMutationSiteSearchResponse,
    dependencies=[Depends(require_local_test_preview)],
)
async def preview_mutation_sites(
    response: Response,
    chromosome: str = Query(..., min_length=1, max_length=32),
    start: int = Query(..., ge=1),
    end: int = Query(..., ge=1),
    limit: int = Query(default=1000, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> PreviewMutationSiteSearchResponse:
    """Find source mutation-site records by a 1-based inclusive interval."""
    _private_no_store(response)
    return await search_preview_mutation_sites(
        db,
        chromosome=chromosome,
        start=start,
        end=end,
        limit=limit,
    )


def _private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


__all__ = ["require_local_test_preview", "router"]

"""Gene endpoints: search, detail, transcripts, assemblies, chromosomes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import SoyMutDBError
from ...schemas.genomic import (
    AssemblyResponse,
    ChromosomeResponse,
    GeneDetail,
    GeneListParams,
    GeneListResponse,
)
from ...services.cache import get_or_set
from ...services.gene_service import GeneService
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/genes", tags=["genes"])
service = GeneService()


@router.get("/assemblies", response_model=list[AssemblyResponse], tags=["assemblies"])
async def list_assemblies(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[AssemblyResponse]:
    """List only genome assemblies in the resolved published release.

    Read-hot query cached in Redis (default TTL) via cache-aside; a Redis
    failure degrades to a direct query.  An empty assembly list is cached as
    well (short-circuit for a freshly seeded database) — that empty-result
    caching is the anti-cache-penetration behaviour shared by every
    ``get_or_set`` call site: once a loader result (even an empty one) is
    stored, repeated requests no longer hit the database until the TTL
    expires.
    """
    payload = await get_or_set(
        f"genes:assemblies:release:{release_context.release_id}",
        ttl=None,
        loader=lambda: _load_assemblies(db, release_context.release_id),
    )
    return [AssemblyResponse.model_validate(item) for item in payload]


async def _load_assemblies(db: AsyncSession, release_id: int) -> list[dict]:
    """Fetch published-release assemblies for the Redis cache."""
    rows = await service.list_assemblies(db, release_id=release_id)
    return [AssemblyResponse.model_validate(row).model_dump(mode="json") for row in rows]


@router.get(
    "/assemblies/{assembly_id}/chromosomes",
    response_model=list[ChromosomeResponse],
    tags=["assemblies"],
)
async def list_chromosomes(
    assembly_id: int,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[ChromosomeResponse]:
    """List chromosomes only when the assembly belongs to this release."""
    return await service.list_chromosomes(
        db, assembly_id, release_id=release_context.release_id
    )


@router.get("", response_model=GeneListResponse)
async def list_genes(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    chromosome: str | None = Query(default=None),
    biotype: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=500),
    q: str | None = Query(default=None, max_length=500),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
    sort_by: str = Query(default="gene_id"),
    sort_dir: str = Query(default="asc"),
) -> GeneListResponse:
    """List genes with cursor pagination or the portal's page contract."""
    try:
        params = GeneListParams(
        assembly_id=str(assembly_id) if assembly_id else None,
        chromosome=chromosome,
        biotype=biotype,
        search=search or q,
        cursor=cursor,
        limit=limit,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    except ValueError as exc:
        # An unknown sort column/direction is client input, not a server bug.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await service.list_genes(
        db,
        params,
        release_context=release_context,
    )


@router.get("/{gene_id}", response_model=GeneDetail)
async def get_gene(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
) -> GeneDetail:
    """Get gene detail with transcripts and aliases.

    ``gene_id`` is the assembly-scoped accession. When it exists in
    multiple assemblies, ``assembly_id`` is required; the API returns an
    explicit disambiguation error otherwise.

    Domain errors (e.g. ``NotFoundError``) propagate to the error envelope;
    unexpected exceptions are converted to a 500 HTTP error so the client
    always receives a structured response.
    """
    try:
        return await service.get_gene(
            db,
            gene_id,
            release_context=release_context,
            assembly_id=assembly_id,
        )
    except SoyMutDBError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred"
        ) from exc

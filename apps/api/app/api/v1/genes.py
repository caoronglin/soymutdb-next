"""Gene endpoints: search, detail, transcripts, assemblies, chromosomes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.genomic import (
    AssemblyResponse,
    ChromosomeResponse,
    GeneDetail,
    GeneListParams,
    GeneListResponse,
)
from ...services.gene_service import GeneService

router = APIRouter(prefix="/genes", tags=["genes"])
service = GeneService()


@router.get("", response_model=GeneListResponse)
async def list_genes(
    db: AsyncSession = Depends(get_db),
    assembly_id: int | None = Query(default=None),
    chromosome: str | None = Query(default=None),
    biotype: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=500),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> GeneListResponse:
    """List genes with cursor pagination."""
    params = GeneListParams(
        assembly_id=str(assembly_id) if assembly_id else None,
        chromosome=chromosome,
        biotype=biotype,
        search=search,
        cursor=cursor,
        limit=limit,
    )
    return await service.list_genes(db, params)


@router.get("/{gene_id}", response_model=GeneDetail)
async def get_gene(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
) -> GeneDetail:
    """Get gene detail with transcripts and aliases."""
    return await service.get_gene(db, gene_id)


@router.get("/assemblies", response_model=list[AssemblyResponse], tags=["assemblies"])
async def list_assemblies(
    db: AsyncSession = Depends(get_db),
) -> list[AssemblyResponse]:
    """List all genome assemblies."""
    return await service.list_assemblies(db)


@router.get(
    "/assemblies/{assembly_id}/chromosomes",
    response_model=list[ChromosomeResponse],
    tags=["assemblies"],
)
async def list_chromosomes(
    assembly_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ChromosomeResponse]:
    """List chromosomes for an assembly."""
    return await service.list_chromosomes(db, assembly_id)

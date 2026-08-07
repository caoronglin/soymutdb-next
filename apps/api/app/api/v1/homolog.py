"""Public homolog data API: query orthologs/paralogs by gene or search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...models.homolog import GeneHomolog

router = APIRouter(prefix="/homologs", tags=["homologs"])


# ---------------------------------------------------------------------------
# 1. Get homologs for a gene
# ---------------------------------------------------------------------------


@router.get("/genes/{gene_id}/homologs")
async def get_gene_homologs(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all homologs (orthologs/paralogs) for a specific gene.

    Returns an empty list if the gene has no homolog entries — no error
    is raised because the gene may simply not have annotated homologs.
    """
    result = await db.execute(
        select(GeneHomolog)
        .where(GeneHomolog.gene_id == gene_id)
        .order_by(GeneHomolog.homolog_species.asc())
    )
    homologs = result.scalars().all()

    items = [
        {
            "homolog_species": h.homolog_species,
            "homolog_gene_id": h.homolog_gene_id,
            "homolog_type": h.homolog_type,
            "source": h.source,
        }
        for h in homologs
    ]

    return {"gene_id": gene_id, "homologs": items}


# ---------------------------------------------------------------------------
# 2. Search homologs
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_homologs(
    db: AsyncSession = Depends(get_db),
    gene_id: str | None = Query(default=None),
    homolog_species: str | None = Query(default=None),
    homolog_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Search homolog records with optional filters and pagination."""
    conditions = []
    if gene_id:
        conditions.append(GeneHomolog.gene_id == gene_id)
    if homolog_species:
        conditions.append(GeneHomolog.homolog_species == homolog_species)
    if homolog_type:
        conditions.append(GeneHomolog.homolog_type == homolog_type)

    where_clause = and_(*conditions) if conditions else None

    # Total count.
    count_stmt = select(func.count()).select_from(GeneHomolog)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows.
    offset = (page - 1) * page_size
    stmt = select(GeneHomolog).order_by(GeneHomolog.id.asc())
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    homologs = result.scalars().all()

    items = [
        {
            "id": h.id,
            "gene_id": h.gene_id,
            "homolog_species": h.homolog_species,
            "homolog_gene_id": h.homolog_gene_id,
            "homolog_type": h.homolog_type,
            "source": h.source,
        }
        for h in homologs
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}

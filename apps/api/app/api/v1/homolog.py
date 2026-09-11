"""Public homolog data API: query orthologs/paralogs by gene or search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...models.homolog import GeneHomolog
from ...services.gene_service import GeneService

router = APIRouter(prefix="/homologs", tags=["homologs"])

_gene_service = GeneService()

def _decode_id_cursor(cursor: str) -> int:
    """Decode a primary-key cursor without allowing offset-like deep paging."""
    try:
        value = int(cursor)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="cursor must be a positive homolog id") from exc
    if value < 1:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="cursor must be a positive homolog id")
    return value



# ---------------------------------------------------------------------------
# 1. Get homologs for a gene
# ---------------------------------------------------------------------------


@router.get("/genes/{gene_id}/homologs")
async def get_gene_homologs(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    assembly_id: int | None = Query(default=None),
    cursor: str | None = Query(
        default=None,
        description="Exclusive GeneHomolog.id keyset cursor.",
    ),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    """Get a bounded, keyset-paginated homolog slice for a specific gene.

    ``gene_id`` is the assembly-scoped accession; when it exists in
    multiple assemblies, ``assembly_id`` is required.

    Empty pages remain a successful response because a gene may simply not
    have annotated homologs.
    """
    resolved = await _gene_service.find_by_accessions(
        db, [gene_id], assembly_id=assembly_id
    )
    matches = resolved.get(gene_id, [])
    if not matches:
        raise NotFoundError(f"Gene {gene_id} not found")
    if len(matches) > 1:
        raise ValidationError(
            f"Gene {gene_id} exists in multiple assemblies; "
            "supply an explicit assembly_id",
            details={"code": "ambiguous_assembly"},
        )
    conditions = [GeneHomolog.gene_id == matches[0].gene_pk]
    if cursor is not None:
        conditions.append(GeneHomolog.id > _decode_id_cursor(cursor))
    result = await db.execute(
        select(GeneHomolog)
        .where(and_(*conditions))
        .order_by(GeneHomolog.id.asc())
        .limit(limit + 1)
    )
    rows = result.scalars().all()
    has_more = len(rows) > limit
    homologs = rows[:limit]

    items = [
        {
            "homolog_species": h.homolog_species,
            "homolog_gene_id": h.homolog_gene_id,
            "homolog_type": h.homolog_type,
            "source": h.source,
        }
        for h in homologs
    ]

    return {
        "gene_id": gene_id,
        "homologs": items,
        "next_cursor": str(homologs[-1].id) if has_more and homologs else None,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# 2. Search homologs
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_homologs(
    db: AsyncSession = Depends(get_db),
    gene_id: str | None = Query(default=None),
    assembly_id: int | None = Query(default=None),
    homolog_species: str | None = Query(default=None),
    homolog_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1, description="Offset page; ignored when cursor is supplied."),
    page_size: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, description="Exclusive GeneHomolog.id keyset cursor."),
) -> dict:
    """Search homolog records with optional filters and pagination."""
    conditions = []
    if gene_id:
        resolved = await _gene_service.find_by_accessions(
            db, [gene_id], assembly_id=assembly_id
        )
        matches = resolved.get(gene_id, [])
        if not matches:
            raise NotFoundError(f"Gene {gene_id} not found")
        if len(matches) > 1:
            raise ValidationError(
                f"Gene {gene_id} exists in multiple assemblies; "
                "supply an explicit assembly_id",
                details={"code": "ambiguous_assembly"},
            )
        conditions.append(GeneHomolog.gene_id == matches[0].gene_pk)
    if homolog_species:
        conditions.append(GeneHomolog.homolog_species == homolog_species)
    if homolog_type:
        conditions.append(GeneHomolog.homolog_type == homolog_type)

    where_clause = and_(*conditions) if conditions else None

    # Cursor mode is keyset pagination: no COUNT(*) and no deep OFFSET scan.
    # Keep page mode temporarily for existing clients.
    total: int | None = None
    if cursor is not None:
        cursor_id = _decode_id_cursor(cursor)
        keyset_conditions = list(conditions)
        keyset_conditions.append(GeneHomolog.id > cursor_id)
        stmt = select(GeneHomolog).where(and_(*keyset_conditions)).order_by(GeneHomolog.id.asc()).limit(page_size + 1)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        has_more = len(rows) > page_size
        homologs = rows[:page_size]
        next_cursor = str(homologs[-1].id) if has_more and homologs else None
    else:
        count_stmt = select(func.count()).select_from(GeneHomolog)
        if where_clause is not None:
            count_stmt = count_stmt.where(where_clause)
        total = int(await db.scalar(count_stmt) or 0)
        offset = (page - 1) * page_size
        stmt = select(GeneHomolog).order_by(GeneHomolog.id.asc())
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        stmt = stmt.offset(offset).limit(page_size)
        result = await db.execute(stmt)
        homologs = result.scalars().all()
        has_more = False
        next_cursor = None

    items = [
        {
            "id": h.id,
            "gene_id": h.gene.accession,
            "homolog_species": h.homolog_species,
            "homolog_gene_id": h.homolog_gene_id,
            "homolog_type": h.homolog_type,
            "source": h.source,
        }
        for h in homologs
    ]

    return {
        "items": items,
        "total": total,
        "page": page if cursor is None else None,
        "page_size": page_size,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }

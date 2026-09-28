"""Public homolog data API: query orthologs/paralogs by gene or search.

Release contract
----------------
``gene_homologs`` has no release/assembly column: a homolog row hangs off
``genes.gene_pk``. Release scoping therefore means joining ``genes`` →
``assemblies`` and filtering ``Assembly.release_id``, which every read here
does — including a search with no ``gene_id``, which previously listed homolog
rows from every release.

The keyset cursor is a signed, release- and filter-bound token rather than a
raw ``GeneHomolog.id``, and the public payload exposes the natural
``(species, gene, type)`` identity instead of the persistence key.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import ValidationError
from ...models.genomic import Assembly, Gene
from ...models.homolog import GeneHomolog
from ...services.gene_service import GeneService
from ...services.release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
    get_release_context,
)

router = APIRouter(prefix="/homologs", tags=["homologs"])

_gene_service = GeneService()

#: Cursor kind, so an expression cursor can never be replayed as a homolog one.
_CURSOR_KIND = "homolog"


def _release_scope(release_context: ReleaseContext):
    """Join predicate binding homolog rows to the published release."""
    return Assembly.release_id == release_context.release_id


def _base_query():
    """Homolog rows joined to their gene's assembly (release filter applies)."""
    return (
        select(GeneHomolog)
        .join(Gene, GeneHomolog.gene_id == Gene.gene_pk)
        .join(Assembly, Gene.assembly_id == Assembly.id)
    )


def _cursor_filters(**values) -> dict[str, str]:
    return {key: str(value) for key, value in values.items() if value is not None}


def _decode_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    filters: dict[str, str],
) -> int:
    payload = decode_bound_cursor(
        cursor,
        kind=_CURSOR_KIND,
        release_context=release_context,
        filters=filters,
    )
    raw = payload.get("d")
    # Row ids are positive: a zero/negative key is not a valid position and
    # would silently re-serve the first page.
    if not isinstance(raw, str) or not raw.isdigit() or int(raw) < 1:
        raise ValidationError("Invalid cursor sort key")
    return int(raw)


def _public_item(h: GeneHomolog) -> dict:
    """Public homolog projection: no persistence key, no surrogate gene id."""
    return {
        "gene_id": h.gene.accession if h.gene else None,
        "homolog_species": h.homolog_species,
        "homolog_gene_id": h.homolog_gene_id,
        "homolog_type": h.homolog_type,
        "source": h.source,
    }



# ---------------------------------------------------------------------------
# 1. Get homologs for a gene
# ---------------------------------------------------------------------------


@router.get("/genes/{gene_id}/homologs")
async def get_gene_homologs(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    cursor: str | None = Query(
        default=None,
        description="Opaque cursor returned by a previous page.",
    ),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    """Get a bounded, keyset-paginated homolog slice for a specific gene.

    ``gene_id`` is the assembly-scoped accession; when it exists in multiple
    assemblies *within the published release*, ``assembly_id`` is required.

    Empty pages remain a successful response because a gene may simply not
    have annotated homologs.
    """
    gene = await _gene_service.resolve_released_gene(
        db, gene_id, release_context=release_context, assembly_id=assembly_id
    )
    conditions = [
        GeneHomolog.gene_id == gene.gene_pk,
        _release_scope(release_context),
    ]
    filters = _cursor_filters(gene_id=gene_id, assembly_id=assembly_id, limit=limit)
    if cursor is not None:
        conditions.append(
            GeneHomolog.id
            > _decode_cursor(cursor, release_context=release_context, filters=filters)
        )
    result = await db.execute(
        _base_query()
        .where(and_(*conditions))
        .order_by(GeneHomolog.id.asc())
        .limit(limit + 1)
    )
    rows = result.scalars().all()
    has_more = len(rows) > limit
    homologs = rows[:limit]

    items = [_public_item(h) for h in homologs]

    return {
        "gene_id": gene_id,
        "homologs": items,
        "next_cursor": (
            encode_bound_cursor(
                kind=_CURSOR_KIND,
                sort_key={"d": str(homologs[-1].id)},
                release_context=release_context,
                filters=filters,
            )
            if has_more and homologs
            else None
        ),
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# 2. Search homologs
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_homologs(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    gene_id: str | None = Query(default=None),
    assembly_id: int | None = Query(default=None),
    homolog_species: str | None = Query(default=None),
    homolog_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1, description="Offset page; ignored when cursor is supplied."),
    page_size: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, description="Opaque cursor from a previous page."),
) -> dict:
    """Search homolog records with optional filters and pagination.

    Every row is scoped to the resolved published release, including when no
    ``gene_id`` is supplied.
    """
    conditions = [_release_scope(release_context)]
    if gene_id:
        gene = await _gene_service.resolve_released_gene(
            db, gene_id, release_context=release_context, assembly_id=assembly_id
        )
        conditions.append(GeneHomolog.gene_id == gene.gene_pk)
    if homolog_species:
        conditions.append(GeneHomolog.homolog_species == homolog_species)
    if homolog_type:
        conditions.append(GeneHomolog.homolog_type == homolog_type)

    where_clause = and_(*conditions)
    filters = _cursor_filters(
        gene_id=gene_id,
        assembly_id=assembly_id,
        species=homolog_species,
        type=homolog_type,
        page_size=page_size,
    )

    # Cursor mode is keyset pagination: no COUNT(*) and no deep OFFSET scan.
    # Keep page mode temporarily for existing clients.
    total: int | None = None
    if cursor is not None:
        cursor_id = _decode_cursor(
            cursor, release_context=release_context, filters=filters
        )
        keyset_conditions = [*conditions, GeneHomolog.id > cursor_id]
        stmt = (
            _base_query()
            .where(and_(*keyset_conditions))
            .order_by(GeneHomolog.id.asc())
            .limit(page_size + 1)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        has_more = len(rows) > page_size
        homologs = rows[:page_size]
        next_cursor = (
            encode_bound_cursor(
                kind=_CURSOR_KIND,
                sort_key={"d": str(homologs[-1].id)},
                release_context=release_context,
                filters=filters,
            )
            if has_more and homologs
            else None
        )
    else:
        count_stmt = (
            select(func.count())
            .select_from(GeneHomolog)
            .join(Gene, GeneHomolog.gene_id == Gene.gene_pk)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(where_clause)
        )
        total = int(await db.scalar(count_stmt) or 0)
        offset = (page - 1) * page_size
        stmt = (
            _base_query()
            .where(where_clause)
            .order_by(GeneHomolog.id.asc())
            .offset(offset)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        homologs = result.scalars().all()
        has_more = False
        next_cursor = None

    items = [_public_item(h) for h in homologs]

    return {
        "items": items,
        "total": total,
        "page": page if cursor is None else None,
        "page_size": page_size,
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }

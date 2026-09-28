"""Public expression data API: list libraries, query expression values by gene.

Release/assembly contract
-------------------------
Expression is biological data, so every read here is bound to the *resolved
published release* and to the assembly of the gene being queried:

* libraries are joined to ``assemblies`` and filtered by
  ``Assembly.release_id`` — an unbound library from a draft or another release
  can never appear;
* the gene is resolved through ``GeneService.find_by_accessions`` with the
  release context, and expression rows only join libraries whose
  ``assembly_id`` equals that gene's assembly, so v4 library data can never be
  attached to a v5 gene (or the reverse);
* the keyset cursor is a signed, release- and filter-bound token rather than a
  raw ``ExpressionData.id``, so it cannot be replayed under a different release
  or used to enumerate row counts.

Public identifiers
------------------
``ExpressionLibrary.id`` is a persistence key and stays internal: the library is
addressed everywhere by its ``sample_id`` (``public_id`` in responses), which is
the label the ingest pipeline assigns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...models.expression import ExpressionData, ExpressionLibrary
from ...models.genomic import Assembly
from ...services.gene_service import GeneService
from ...services.release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
    get_release_context,
)

router = APIRouter(prefix="/expression", tags=["expression"])
_gene_service = GeneService()


def _library_scope(release_context: ReleaseContext):
    """Join predicate binding expression libraries to the published release."""
    return Assembly.release_id == release_context.release_id


def _library_public_id(lib: ExpressionLibrary) -> str:
    """Public, non-persistence identifier of an expression library."""
    return str(lib.sample_id)


def _library_payload(lib: ExpressionLibrary, expression_data_count: int) -> dict:
    """Public library projection: no surrogate key, no raw assembly PK."""
    return {
        "public_id": _library_public_id(lib),
        "sample_id": lib.sample_id,
        "library_name": lib.library_name,
        "tissue": lib.tissue,
        "treatment": lib.treatment,
        "developmental_stage": lib.developmental_stage,
        "study_ref": lib.study_ref,
        "source": lib.source,
        "assembly_name": lib.assembly.name if lib.assembly else None,
        "extra_metadata": lib.extra_metadata,
        "expression_data_count": expression_data_count,
    }


async def _resolve_release_gene(
    db: AsyncSession,
    gene_id: str,
    *,
    assembly_id: int | None,
    release_context: ReleaseContext,
):
    """Resolve a gene accession inside the published release.

    Thin wrapper over the shared service helper so the expression and homolog
    routes cannot drift on the disambiguation rule.
    """
    return await _gene_service.resolve_released_gene(
        db,
        gene_id,
        release_context=release_context,
        assembly_id=assembly_id,
    )


def _expression_cursor_filters(**values) -> dict[str, str]:
    """Filter set the expression cursor is bound to (no None values)."""
    return {
        key: str(value)
        for key, value in values.items()
        if value is not None
    }


def _decode_expression_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    filters: dict[str, str],
) -> int:
    payload = decode_bound_cursor(
        cursor,
        kind="expression",
        release_context=release_context,
        filters=filters,
    )
    raw = payload.get("d")
    # Row ids are positive: a zero/negative key is not a valid position and
    # would silently re-serve the first page.
    if not isinstance(raw, str) or not raw.isdigit() or int(raw) < 1:
        raise ValidationError("Invalid cursor sort key")
    return int(raw)


async def _resolve_library(
    db: AsyncSession,
    public_id: str,
    *,
    release_context: ReleaseContext,
) -> ExpressionLibrary:
    """Resolve a library by its public sample id within the published release."""
    result = await db.execute(
        select(ExpressionLibrary)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
        .where(
            ExpressionLibrary.sample_id == public_id,
            _library_scope(release_context),
        )
    )
    library = result.scalar_one_or_none()
    if library is None:
        raise NotFoundError(f"Expression library {public_id!r} not found")
    return library


# ---------------------------------------------------------------------------
# 1. List expression libraries
# ---------------------------------------------------------------------------


@router.get("/libraries")
async def list_libraries(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    assembly_id: int | None = Query(default=None),
) -> dict:
    """Paginated list of expression libraries with optional filters.

    Only libraries whose assembly belongs to the resolved published release are
    returned. ``assembly_id`` narrows within that release; an id from another
    release simply yields no rows rather than widening the scope.
    """
    conditions = [_library_scope(release_context)]
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if assembly_id is not None:
        conditions.append(ExpressionLibrary.assembly_id == assembly_id)

    where_clause = and_(*conditions)

    # Total count.
    count_stmt = (
        select(func.count())
        .select_from(ExpressionLibrary)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
        .where(where_clause)
    )
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows.
    offset = (page - 1) * page_size
    stmt = (
        select(ExpressionLibrary)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
        .where(where_clause)
        .order_by(ExpressionLibrary.id.asc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    libraries = result.scalars().all()

    # Batch-count expression data rows for all libraries in this page (avoids N+1).
    lib_ids = [lib.id for lib in libraries]
    counts_map: dict[int, int] = {}
    if lib_ids:
        count_stmt = (
            select(ExpressionData.library_id, func.count())
            .where(ExpressionData.library_id.in_(lib_ids))
            .group_by(ExpressionData.library_id)
        )
        count_rows = (await db.execute(count_stmt)).all()
        counts_map = {lid: int(cnt) for lid, cnt in count_rows}

    items = [
        _library_payload(lib, counts_map.get(lib.id, 0)) for lib in libraries
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 2. Get single library
# ---------------------------------------------------------------------------


@router.get("/libraries/{public_id}")
async def get_library(
    public_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> dict:
    """Get a single expression library by its public sample identifier.

    The persistence key is not a locator: a request for it (or for a library in
    an unpublished release) returns the same not-found response.
    """
    lib = await _resolve_library(db, public_id, release_context=release_context)

    # Count expression data rows.
    count_result = await db.execute(
        select(func.count()).select_from(ExpressionData).where(
            ExpressionData.library_id == lib.id
        )
    )
    expr_count = int(count_result.scalar() or 0)

    return _library_payload(lib, expr_count)


# ---------------------------------------------------------------------------
# 3. Get expression data for a gene
# ---------------------------------------------------------------------------


@router.get("/genes/{gene_id}/expression")
async def get_gene_expression(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    library: str | None = Query(default=None),
    min_fpkm: float | None = Query(default=None, ge=0.0),
    max_fpkm: float | None = Query(default=None, ge=0.0),
    cursor: str | None = Query(
        default=None,
        description="Opaque cursor returned by a previous page.",
    ),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    """Get a bounded, keyset-paginated expression slice for a gene.

    ``gene_id`` is the assembly-scoped accession; when it exists in multiple
    assemblies within the published release, ``assembly_id`` is required.
    ``library`` accepts the public sample identifier. The cursor is opaque and
    bound to the release and every filter, so it cannot be replayed against a
    different release or filter set.

    Complete data exports must use the asynchronous export path rather than
    materialising every matching library in an API worker.
    """
    gene = await _resolve_release_gene(
        db, gene_id, assembly_id=assembly_id, release_context=release_context
    )
    conditions = [
        ExpressionData.gene_id == gene.gene_pk,
        # The library must live in the gene's own assembly AND the published
        # release: without this a v4 library could attach data to a v5 gene.
        ExpressionLibrary.assembly_id == gene.assembly_id,
        _library_scope(release_context),
    ]
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if library is not None:
        resolved_library = await _resolve_library(
            db, library, release_context=release_context
        )
        conditions.append(ExpressionData.library_id == resolved_library.id)
    if min_fpkm is not None:
        conditions.append(ExpressionData.fpkm >= min_fpkm)
    if max_fpkm is not None:
        conditions.append(ExpressionData.fpkm <= max_fpkm)

    filters = _expression_cursor_filters(
        gene_id=gene_id,
        assembly_id=assembly_id,
        tissue=tissue,
        treatment=treatment,
        library=library,
        min_fpkm=min_fpkm,
        max_fpkm=max_fpkm,
        limit=limit,
    )
    if cursor is not None:
        last_id = _decode_expression_cursor(
            cursor, release_context=release_context, filters=filters
        )
        conditions.append(ExpressionData.id > last_id)

    stmt = (
        select(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
        .where(and_(*conditions))
        .order_by(ExpressionData.id.asc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    expressions = []
    for row in rows:
        lib = row.library
        expressions.append({
            "library_public_id": _library_public_id(lib),
            "library_name": lib.library_name,
            "tissue": lib.tissue,
            "treatment": lib.treatment,
            "fpkm": row.fpkm,
            "tpm": row.tpm,
            "raw_count": row.raw_count,
        })

    return {
        "gene_id": gene_id,
        "expressions": expressions,
        "next_cursor": (
            encode_bound_cursor(
                kind="expression",
                sort_key={"d": str(rows[-1].id)},
                release_context=release_context,
                filters=filters,
            )
            if has_more and rows
            else None
        ),
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# 4. Search expression data
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_expression(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    gene_id: str | None = Query(default=None),
    assembly_id: int | None = Query(default=None),
    library: str | None = Query(default=None),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    min_fpkm: float | None = Query(default=None, ge=0.0),
    max_fpkm: float | None = Query(default=None, ge=0.0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Search expression rows, joined with library info, within the release.

    Every row is bound to a library whose assembly belongs to the resolved
    published release; when ``gene_id`` is given the library must additionally
    share that gene's assembly.
    """
    conditions = [_library_scope(release_context)]
    if gene_id:
        gene = await _resolve_release_gene(
            db, gene_id, assembly_id=assembly_id, release_context=release_context
        )
        conditions.append(ExpressionData.gene_id == gene.gene_pk)
        conditions.append(ExpressionLibrary.assembly_id == gene.assembly_id)
    if library is not None:
        resolved_library = await _resolve_library(
            db, library, release_context=release_context
        )
        conditions.append(ExpressionData.library_id == resolved_library.id)
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if min_fpkm is not None:
        conditions.append(ExpressionData.fpkm >= min_fpkm)
    if max_fpkm is not None:
        conditions.append(ExpressionData.fpkm <= max_fpkm)

    where_clause = and_(*conditions)

    # Base query with join.
    base_query = (
        select(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
    )

    # Total count.
    count_stmt = (
        select(func.count())
        .select_from(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .join(Assembly, ExpressionLibrary.assembly_id == Assembly.id)
        .where(where_clause)
    )
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows.
    offset = (page - 1) * page_size
    stmt = (
        base_query.where(where_clause)
        .order_by(ExpressionData.id.asc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for row in rows:
        lib = row.library
        items.append({
            "gene_id": row.gene.accession,
            "library_public_id": _library_public_id(lib),
            "library_name": lib.library_name,
            "tissue": lib.tissue,
            "treatment": lib.treatment,
            "fpkm": row.fpkm,
            "tpm": row.tpm,
            "raw_count": row.raw_count,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}

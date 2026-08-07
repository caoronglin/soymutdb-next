"""Public expression data API: list libraries, query expression values by gene."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...models.expression import ExpressionData, ExpressionLibrary

router = APIRouter(prefix="/expression", tags=["expression"])


# ---------------------------------------------------------------------------
# 1. List expression libraries
# ---------------------------------------------------------------------------


@router.get("/libraries")
async def list_libraries(
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    assembly_id: int | None = Query(default=None),
) -> dict:
    """Paginated list of expression libraries with optional filters."""
    conditions = []
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if assembly_id is not None:
        conditions.append(ExpressionLibrary.assembly_id == assembly_id)

    where_clause = and_(*conditions) if conditions else None

    # Total count.
    count_stmt = select(func.count()).select_from(ExpressionLibrary)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows.
    offset = (page - 1) * page_size
    stmt = select(ExpressionLibrary).order_by(ExpressionLibrary.id.asc())
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.offset(offset).limit(page_size)
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

    items = []
    for lib in libraries:
        expr_count = counts_map.get(lib.id, 0)
        items.append({
            "id": lib.id,
            "sample_id": lib.sample_id,
            "library_name": lib.library_name,
            "tissue": lib.tissue,
            "treatment": lib.treatment,
            "developmental_stage": lib.developmental_stage,
            "study_ref": lib.study_ref,
            "source": lib.source,
            "assembly_id": lib.assembly_id,
            "extra_metadata": lib.extra_metadata,
            "expression_data_count": expr_count,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 2. Get single library
# ---------------------------------------------------------------------------


@router.get("/libraries/{library_id}")
async def get_library(
    library_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single expression library with full detail."""
    result = await db.execute(
        select(ExpressionLibrary).where(ExpressionLibrary.id == library_id)
    )
    lib = result.scalar_one_or_none()
    if lib is None:
        raise NotFoundError(f"Expression library {library_id} not found")

    # Count expression data rows.
    count_result = await db.execute(
        select(func.count()).select_from(ExpressionData).where(
            ExpressionData.library_id == lib.id
        )
    )
    expr_count = int(count_result.scalar() or 0)

    return {
        "id": lib.id,
        "sample_id": lib.sample_id,
        "library_name": lib.library_name,
        "tissue": lib.tissue,
        "treatment": lib.treatment,
        "developmental_stage": lib.developmental_stage,
        "study_ref": lib.study_ref,
        "source": lib.source,
        "assembly_id": lib.assembly_id,
        "extra_metadata": lib.extra_metadata,
        "expression_data_count": expr_count,
    }


# ---------------------------------------------------------------------------
# 3. Get expression data for a gene
# ---------------------------------------------------------------------------


@router.get("/genes/{gene_id}/expression")
async def get_gene_expression(
    gene_id: str,
    db: AsyncSession = Depends(get_db),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    library_id: int | None = Query(default=None),
    min_fpkm: float | None = Query(default=None, ge=0.0),
    max_fpkm: float | None = Query(default=None, ge=0.0),
) -> dict:
    """Get expression data for a specific gene, with optional filters."""
    conditions = [ExpressionData.gene_id == gene_id]
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if library_id is not None:
        conditions.append(ExpressionData.library_id == library_id)
    if min_fpkm is not None:
        conditions.append(ExpressionData.fpkm >= min_fpkm)
    if max_fpkm is not None:
        conditions.append(ExpressionData.fpkm <= max_fpkm)

    stmt = (
        select(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .where(and_(*conditions))
        .order_by(ExpressionData.library_id.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    expressions = []
    for row in rows:
        lib = row.library
        expressions.append({
            "library_id": lib.id,
            "library_name": lib.library_name,
            "tissue": lib.tissue,
            "treatment": lib.treatment,
            "fpkm": row.fpkm,
            "tpm": row.tpm,
            "raw_count": row.raw_count,
        })

    return {"gene_id": gene_id, "expressions": expressions}


# ---------------------------------------------------------------------------
# 4. Search expression data
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_expression(
    db: AsyncSession = Depends(get_db),
    gene_id: str | None = Query(default=None),
    library_id: int | None = Query(default=None),
    tissue: str | None = Query(default=None),
    treatment: str | None = Query(default=None),
    min_fpkm: float | None = Query(default=None, ge=0.0),
    max_fpkm: float | None = Query(default=None, ge=0.0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Search expression data rows, joined with library info, with pagination."""
    conditions = []
    if gene_id:
        conditions.append(ExpressionData.gene_id == gene_id)
    if library_id is not None:
        conditions.append(ExpressionData.library_id == library_id)
    if tissue:
        conditions.append(ExpressionLibrary.tissue == tissue)
    if treatment:
        conditions.append(ExpressionLibrary.treatment == treatment)
    if min_fpkm is not None:
        conditions.append(ExpressionData.fpkm >= min_fpkm)
    if max_fpkm is not None:
        conditions.append(ExpressionData.fpkm <= max_fpkm)

    where_clause = and_(*conditions) if conditions else None

    # Base query with join.
    base_query = select(ExpressionData).join(
        ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id
    )

    # Total count.
    count_stmt = select(func.count()).select_from(ExpressionData).join(
        ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id
    )
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    # Paginated rows.
    offset = (page - 1) * page_size
    stmt = base_query
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.order_by(ExpressionData.id.asc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    items = []
    for row in rows:
        lib = row.library
        items.append({
            "id": row.id,
            "gene_id": row.gene_id,
            "library_id": lib.id,
            "library_name": lib.library_name,
            "tissue": lib.tissue,
            "treatment": lib.treatment,
            "fpkm": row.fpkm,
            "tpm": row.tpm,
            "raw_count": row.raw_count,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}

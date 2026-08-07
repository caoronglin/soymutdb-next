"""Expression pattern analysis service: gene × condition matrix aggregation + row clustering.

Data source mirrors ``app/api/v1/expression.py`` — PostgreSQL tables
``ExpressionData`` / ``ExpressionLibrary`` (the same tables the expression
endpoints read from).  Each *condition* is an expression library, identified
by its ``library_name``; the matrix value is the gene's ``fpkm`` in that
library (``None`` when the gene has no record for the library).

Clustering is deliberately lightweight: when SciPy is installed, rows are
ordered with average-linkage hierarchical clustering on pairwise euclidean
distance (missing values imputed with the row mean for distance computation
only); otherwise rows are sorted by mean expression.  The method actually
used is reported in the response ``clustering`` field.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import ValidationError
from ..models.expression import ExpressionData, ExpressionLibrary

MAX_GENES = 50
MAX_CONDITIONS = 200

# Optional SciPy backend for hierarchical clustering.  Imported at module
# level so tests can monkeypatch these names directly.
try:
    from scipy.cluster.hierarchy import leaves_list, linkage
    from scipy.spatial.distance import pdist
except ImportError:  # pragma: no cover - fallback path exercised in tests
    linkage = None
    leaves_list = None
    pdist = None


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a database)
# ---------------------------------------------------------------------------


def zscore_rows(matrix: list[list[float | None]]) -> list[list[float | None]]:
    """Row-wise z-score (population std, ddof=0) over non-null values.

    ``None`` cells stay ``None``; a row with no non-null values is returned
    untouched; a constant row becomes all zeros (undefined z-score).
    """
    out: list[list[float | None]] = []
    for row in matrix:
        vals = [v for v in row if v is not None]
        if not vals:
            out.append(list(row))
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = var**0.5
        if std == 0:
            out.append([0.0 if v is not None else None for v in row])
        else:
            out.append([(v - mean) / std if v is not None else None for v in row])
    return out


def _impute_matrix(matrix: list[list[float | None]]) -> list[list[float]]:
    """Replace ``None`` cells with the row mean (0.0 for fully-empty rows).

    Used only for distance computation in clustering — the reported matrix
    is never modified.
    """
    out: list[list[float]] = []
    for row in matrix:
        vals = [v for v in row if v is not None]
        mean = (sum(vals) / len(vals)) if vals else 0.0
        out.append([v if v is not None else mean for v in row])
    return out


def cluster_row_order(matrix: list[list[float | None]]) -> tuple[list[int], str]:
    """Return a row index permutation for heatmap display.

    * ``hierarchical`` — SciPy average-linkage clustering on euclidean
      distance (imputed matrix).
    * ``mean_sort`` — fallback: rows ordered by mean value, descending.
    * ``none`` — fewer than 2 rows.
    """
    n = len(matrix)
    if n <= 1:
        return list(range(n)), "none"

    if pdist is not None and linkage is not None and leaves_list is not None:
        try:
            dist = pdist(_impute_matrix(matrix), metric="euclidean")
            link = linkage(dist, method="average")
            return [int(i) for i in leaves_list(link)], "hierarchical"
        except Exception:
            pass  # pragma: no cover - fall through to mean sort

    means: list[tuple[float, int]] = []
    for i, row in enumerate(matrix):
        vals = [v for v in row if v is not None]
        mean = (sum(vals) / len(vals)) if vals else float("-inf")
        means.append((mean, i))
    means.sort(key=lambda item: item[0], reverse=True)
    return [i for _, i in means], "mean_sort"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def fetch_expression_pattern(
    db: AsyncSession,
    genes: list[str],
    conditions: list[str] | None = None,
    *,
    cluster_rows: bool = False,
    scale: str = "zscore",
) -> dict[str, Any]:
    """Aggregate expression values into a gene × condition matrix.

    * ``genes`` — gene ids, 1..50 (duplicates are de-duplicated).
    * ``conditions`` — library names to include; ``None``/empty means all.
    * ``cluster_rows`` — reorder rows (hierarchical if SciPy present, else
      mean sort); the method is reported in the response.
    * ``scale`` — ``"zscore"`` (row-wise, default) or ``"none"`` (raw fpkm).

    Raises :class:`ValidationError` (HTTP 422) when the request exceeds the
    50 genes × 200 conditions scale limit — either from the payload or from
    the libraries resolved in the database.
    """
    if len(genes) > MAX_GENES:
        raise ValidationError(
            f"Too many genes: {len(genes)} > {MAX_GENES}",
            details={"limit": MAX_GENES},
        )
    if conditions is not None and len(conditions) > MAX_CONDITIONS:
        raise ValidationError(
            f"Too many conditions: {len(conditions)} > {MAX_CONDITIONS}",
            details={"limit": MAX_CONDITIONS},
        )
    genes = list(dict.fromkeys(genes))  # preserve order, drop duplicates

    # Resolve condition set (libraries).  library_name may repeat across
    # libraries; de-duplicate by name, first occurrence wins.
    lib_stmt = select(ExpressionLibrary).order_by(ExpressionLibrary.id.asc())
    if conditions:
        lib_stmt = lib_stmt.where(ExpressionLibrary.library_name.in_(conditions))
    lib_result = await db.execute(lib_stmt)
    libraries = lib_result.scalars().all()
    condition_names = list(dict.fromkeys(lib.library_name for lib in libraries))
    if len(condition_names) > MAX_CONDITIONS:
        raise ValidationError(
            f"Too many conditions: {len(condition_names)} > {MAX_CONDITIONS}",
            details={"limit": MAX_CONDITIONS},
        )

    # Fetch expression rows for the requested genes (same join as
    # app/api/v1/expression.py).
    data_stmt = (
        select(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .where(ExpressionData.gene_id.in_(genes))
        .order_by(ExpressionData.library_id.asc())
    )
    if conditions:
        data_stmt = data_stmt.where(ExpressionLibrary.library_name.in_(conditions))
    data_result = await db.execute(data_stmt)
    rows = data_result.scalars().all()

    # Build matrix: rows = genes, columns = conditions, value = fpkm.
    col_index = {name: i for i, name in enumerate(condition_names)}
    row_index = {g: i for i, g in enumerate(genes)}
    matrix: list[list[float | None]] = [
        [None] * len(condition_names) for _ in genes
    ]
    found: set[str] = set()
    for row in rows:
        gene_id = row.gene_id
        col = col_index.get(row.library.library_name)
        if gene_id not in row_index or col is None:
            continue
        matrix[row_index[gene_id]][col] = row.fpkm
        found.add(gene_id)

    if scale == "zscore":
        matrix_out = zscore_rows(matrix)
    else:
        matrix_out = [list(r) for r in matrix]

    if cluster_rows:
        row_order, clustering = cluster_row_order(matrix_out)
    else:
        row_order, clustering = list(range(len(genes))), "input"

    flat = [v for row in matrix_out for v in row if v is not None]
    value_range = [min(flat), max(flat)] if flat else [None, None]

    return {
        "genes": genes,
        "conditions": condition_names,
        "matrix": matrix_out,
        "row_order": row_order,
        "clustering": clustering,
        "value_range": value_range,
        "missing_genes": [g for g in genes if g not in found],
        "scale": scale,
    }


__all__ = [
    "MAX_CONDITIONS",
    "MAX_GENES",
    "cluster_row_order",
    "fetch_expression_pattern",
    "zscore_rows",
]

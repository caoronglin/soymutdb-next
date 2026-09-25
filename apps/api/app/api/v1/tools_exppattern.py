"""Public expression-pattern analysis tool: gene × condition matrix + row clustering.

POST /api/v1/tools/exppattern — builds an expression matrix (rows = genes,
columns = expression libraries), optionally row-wise z-scored and reordered
by clustering.  Data comes from the same PostgreSQL tables the
``/api/v1/expression`` endpoints read from.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.exppattern import ExpPatternRequest, ExpPatternResponse
from ...services.exppattern_service import fetch_expression_pattern
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/exppattern", response_model=ExpPatternResponse)
async def exppattern(
    request: ExpPatternRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> ExpPatternResponse:
    """Return a gene × condition expression matrix, optionally scaled/clustered.

    Response: ``genes`` (row ids), ``conditions`` (column ids), ``matrix``
    (row-major, ``None`` for missing expression), ``row_order`` (row index
    permutation), ``clustering`` (method used), ``value_range`` ``[min, max]``
    over non-null cells, plus ``missing_genes`` / ``scale`` annotations.
    """
    return ExpPatternResponse.model_validate(await fetch_expression_pattern(
        db,
        request.assembly_id,
        request.genes,
        request.conditions,
        release_id=release_context.release_id,
        cluster_rows=request.cluster_rows,
        scale=request.scale,
    ))


__all__ = ["ExpPatternRequest", "router"]

"""Public expression-pattern analysis tool: gene × condition matrix + row clustering.

POST /api/v1/tools/exppattern — builds an expression matrix (rows = genes,
columns = expression libraries), optionally row-wise z-scored and reordered
by clustering.  Data comes from the same PostgreSQL tables the
``/api/v1/expression`` endpoints read from.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...services.exppattern_service import fetch_expression_pattern

router = APIRouter(prefix="/tools", tags=["tools"])


class ExpPatternRequest(BaseModel):
    """Request body for ``POST /api/v1/tools/exppattern``."""

    genes: list[str] = Field(
        min_length=1,
        max_length=50,
        description="Gene IDs to include in the matrix (1–50).",
    )
    conditions: list[str] | None = Field(
        default=None,
        max_length=200,
        description=(
            "Expression library names to use as matrix columns; "
            "defaults to all libraries (max 200)."
        ),
    )
    cluster_rows: bool = Field(
        default=False,
        description=(
            "Reorder matrix rows by clustering (hierarchical when SciPy is "
            "available, otherwise mean-expression sort)."
        ),
    )
    scale: Literal["zscore", "none"] = Field(
        default="zscore",
        description="Row scaling: 'zscore' (default) or 'none' for raw fpkm.",
    )

    @field_validator("genes")
    @classmethod
    def _genes_not_blank(cls, v: list[str]) -> list[str]:
        cleaned = [g.strip() for g in v if g.strip()]
        if not cleaned:
            raise ValueError("genes must contain at least one non-empty id")
        return cleaned


@router.post("/exppattern")
async def exppattern(
    request: ExpPatternRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a gene × condition expression matrix, optionally scaled/clustered.

    Response: ``genes`` (row ids), ``conditions`` (column ids), ``matrix``
    (row-major, ``None`` for missing expression), ``row_order`` (row index
    permutation), ``clustering`` (method used), ``value_range`` ``[min, max]``
    over non-null cells, plus ``missing_genes`` / ``scale`` annotations.
    """
    return await fetch_expression_pattern(
        db,
        request.genes,
        request.conditions,
        cluster_rows=request.cluster_rows,
        scale=request.scale,
    )


__all__ = ["ExpPatternRequest", "router"]

"""Request and response contracts for expression-pattern analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ExpPatternRequest(BaseModel):
    """Request one expression matrix from exactly one genome assembly."""

    assembly_id: int = Field(
        ge=1,
        description=(
            "Genome assembly database id; genes and expression libraries "
            "are restricted to it."
        ),
    )
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
    def _genes_not_blank(cls, genes: list[str]) -> list[str]:
        cleaned = [gene.strip() for gene in genes if gene.strip()]
        if not cleaned:
            raise ValueError("genes must contain at least one non-empty id")
        return cleaned


class ExpPatternResponse(BaseModel):
    """Assembly-labelled expression matrix; ``row_order`` maps display rows to genes."""

    assembly_id: int = Field(ge=1)
    release_id: int = Field(ge=1)
    assembly_name: str
    assembly_version: str
    genes: list[str]
    conditions: list[str]
    matrix: list[list[float | None]]
    row_order: list[int]
    clustering: Literal["input", "hierarchical", "mean_sort", "none"]
    value_range: tuple[float | None, float | None]
    missing_genes: list[str]
    scale: Literal["zscore", "none"]

    @model_validator(mode="after")
    def _matrix_and_display_order_match_genes(self) -> ExpPatternResponse:
        if len(self.matrix) != len(self.genes) or any(
            len(row) != len(self.conditions) for row in self.matrix
        ):
            raise ValueError("matrix dimensions must match genes and conditions")
        if sorted(self.row_order) != list(range(len(self.genes))):
            raise ValueError("row_order must be a permutation of the gene row indexes")
        return self


__all__ = ["ExpPatternRequest", "ExpPatternResponse"]

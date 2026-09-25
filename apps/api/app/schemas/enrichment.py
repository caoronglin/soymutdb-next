"""Schemas for the GO/KEGG enrichment analysis tool."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Maximum number of input genes accepted by the enrichment endpoint.
MAX_INPUT_GENES = 500
# Maximum number of member genes reported per enriched term.
MAX_TERM_GENES = 20

Ontology = Literal["go", "kegg"]
Mode = Literal["ora", "gsea"]


class EnrichmentRequest(BaseModel):
    """POST /api/v1/tools/enrichment payload.

    ``assembly_id`` is mandatory: both annotations and the statistical
    background must be scoped to the selected assembly.
    ``genes`` are gene ids (e.g. ``Glyma.01G000100``); duplicates are
    tolerated and deduplicated server-side.  ``mode`` selects between the
    classic over-representation test (default, backwards compatible) and the
    rank-based GSEA mode.  ``values`` (one per gene, e.g. log2 fold-changes)
    is required in ``gsea`` mode and must align with ``genes`` 1:1.
    """

    assembly_id: int = Field(
        ge=1,
        description=(
            "Assembly database id; input genes, annotations, and background "
            "are restricted to it."
        ),
    )
    genes: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_INPUT_GENES,
        description="Gene ids to test for GO/KEGG enrichment (1-500)",
    )
    mode: Mode = Field(
        default="ora",
        description=(
            "Analysis mode: 'ora' (over-representation, default) or 'gsea' "
            "(rank-based gene-set test)"
        ),
    )
    values: list[float] | None = Field(
        default=None,
        max_length=MAX_INPUT_GENES,
        description=(
            "Per-gene numeric values (e.g. log2 fold-changes) used to rank "
            "genes in 'gsea' mode; required there and must align with 'genes' 1:1"
        ),
    )
    ontology: Ontology = Field(
        default="go", description="Annotation source: 'go' or 'kegg'"
    )
    p_threshold: float = Field(
        default=0.05, gt=0.0, le=1.0, description="Raw p-value significance cutoff"
    )
    max_terms: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of enriched terms to return (sorted by q-value)",
    )
    min_genes: int = Field(
        default=5,
        ge=1,
        le=MAX_INPUT_GENES,
        description=(
            "Minimum term size (member genes present in the ranked input) "
            "required for a term to be tested in 'gsea' mode"
        ),
    )

    @field_validator("genes")
    @classmethod
    def _strip_blank_genes(cls, genes: list[str]) -> list[str]:
        cleaned: list[str] = []
        for gene in genes:
            stripped = gene.strip()
            if not stripped:
                raise ValueError("Gene ids must not be blank")
            cleaned.append(stripped)
        return cleaned

    @field_validator("values")
    @classmethod
    def _reject_non_finite_values(
        cls, values: list[float] | None
    ) -> list[float] | None:
        if values is not None and not all(math.isfinite(v) for v in values):
            raise ValueError("Values must be finite numbers")
        return values

    @model_validator(mode="after")
    def _gsea_mode_requires_values(self) -> EnrichmentRequest:
        if self.mode == "gsea":
            if self.values is None:
                raise ValueError("values is required when mode is 'gsea'")
            if len(self.values) != len(self.genes):
                raise ValueError(
                    "values must contain exactly one entry per gene in gsea mode"
                )
        return self


class EnrichmentTerm(BaseModel):
    """A single enriched term (ORA mode)."""

    id: str = Field(..., description="Term id, e.g. GO:0008150 or ko00010")
    name: str = Field(..., description="Term name (falls back to the term id)")
    p_value: float = Field(..., description="Hypergeometric right-tail p-value")
    q_value: float = Field(..., description="Benjamini-Hochberg adjusted p-value")
    gene_count: int = Field(..., description="Input genes annotated to this term")
    genes: list[str] = Field(
        ..., description=f"Member input genes (first {MAX_TERM_GENES})"
    )


class EnrichmentGseaTerm(BaseModel):
    """A single enriched term (GSEA mode, rank-based test)."""

    id: str = Field(..., description="Term id, e.g. GO:0008150 or ko00010")
    name: str = Field(..., description="Term name (falls back to the term id)")
    es: float = Field(
        ...,
        description=(
            "Enrichment score: signed running-sum statistic over the "
            "value-descending ranked list (positive = concentrated at high "
            "values, negative = at low values)"
        ),
    )
    nes: float = Field(
        ...,
        description=(
            "Normalized enrichment score: z-score of ES under the analytic "
            "null (ES * sqrt(k(n-k)/n)); a simplification of the permutation "
            "normalization used by the reference GSEA implementation"
        ),
    )
    p_value: float = Field(
        ...,
        description=(
            "Rank-based p-value from the one-sided Smirnov asymptotic "
            "exp(-2 * k(n-k)/n * ES^2)"
        ),
    )
    q_value: float = Field(..., description="Benjamini-Hochberg adjusted p-value")
    size: int = Field(..., description="Term genes present in the ranked input")
    genes: list[str] = Field(
        ..., description=f"Member input genes (first {MAX_TERM_GENES})"
    )


class EnrichmentCalculationResponse(BaseModel):
    """Internal ORA result before assembly context is attached."""

    mode: Literal["ora"] = Field(..., description="Analysis mode")
    ontology: Ontology
    input_genes: int = Field(..., description="Number of unique input genes")
    background_genes: int = Field(
        ...,
        description="Number of annotated genes in the background set "
        "(all genes with annotations for the requested ontology)",
    )
    terms: list[EnrichmentTerm] = Field(
        default_factory=list, description="Enriched terms sorted by q-value (asc)"
    )
    message: str | None = Field(
        default=None,
        description="Explanatory note, e.g. when no input gene has annotations",
    )


class EnrichmentSource(BaseModel):
    """Public, reproducible source identity for the annotation snapshot."""

    name: str = Field(..., description="Annotation provider or dataset name")
    version: str = Field(..., description="Provider's data release/version")
    url: str = Field(..., description="Public HTTPS source page or download URL")
    sha256: str = Field(..., description="SHA-256 of the imported source file")
    imported_at: datetime = Field(..., description="UTC import timestamp")


class EnrichmentResponse(EnrichmentCalculationResponse):
    """ORA result with assembly, release, and annotation source context."""

    assembly_id: int = Field(ge=1)
    release_id: int = Field(ge=1)
    assembly_name: str
    assembly_version: str
    annotation_source: EnrichmentSource | None


class EnrichmentGseaCalculationResponse(BaseModel):
    """Internal GSEA result before assembly context is attached."""

    mode: Literal["gsea"] = Field(..., description="Analysis mode")
    ontology: Ontology
    input_genes: int = Field(
        ..., description="Number of unique input genes (the ranked list)"
    )
    background_genes: int = Field(
        ...,
        description="Number of annotated genes in the background set "
        "(all genes with annotations for the requested ontology)",
    )
    terms: list[EnrichmentGseaTerm] = Field(
        default_factory=list, description="GSEA terms sorted by q-value (asc)"
    )
    message: str | None = Field(
        default=None,
        description="Explanatory note, e.g. when no term passes min_genes",
    )


class EnrichmentGseaResponse(EnrichmentGseaCalculationResponse):
    """GSEA result with assembly, release, and annotation source context."""

    assembly_id: int = Field(ge=1)
    release_id: int = Field(ge=1)
    assembly_name: str
    assembly_version: str
    annotation_source: EnrichmentSource | None

"""Schemas for the GO/KEGG enrichment analysis tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Maximum number of input genes accepted by the enrichment endpoint.
MAX_INPUT_GENES = 500
# Maximum number of member genes reported per enriched term.
MAX_TERM_GENES = 20

Ontology = Literal["go", "kegg"]


class EnrichmentRequest(BaseModel):
    """POST /api/v1/tools/enrichment payload.

    ``genes`` are gene ids (e.g. ``Glyma.01G000100``); duplicates are
    tolerated and deduplicated server-side.
    """

    genes: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_INPUT_GENES,
        description="Gene ids to test for GO/KEGG enrichment (1-500)",
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


class EnrichmentTerm(BaseModel):
    """A single enriched term."""

    id: str = Field(..., description="Term id, e.g. GO:0008150 or ko00010")
    name: str = Field(..., description="Term name (falls back to the term id)")
    p_value: float = Field(..., description="Hypergeometric right-tail p-value")
    q_value: float = Field(..., description="Benjamini-Hochberg adjusted p-value")
    gene_count: int = Field(..., description="Input genes annotated to this term")
    genes: list[str] = Field(
        ..., description=f"Member input genes (first {MAX_TERM_GENES})"
    )


class EnrichmentResponse(BaseModel):
    """Enrichment analysis result."""

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

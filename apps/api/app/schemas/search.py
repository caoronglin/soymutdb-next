"""Pydantic v2 schemas for global and advanced search endpoints."""

from __future__ import annotations

from ..core.compat import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SearchResultType(StrEnum):
    GENE = "gene"
    VARIANT = "variant"
    MUTANT_LINE = "mutant_line"
    PHENOTYPE = "phenotype"
    PUBLICATION = "publication"


class MatchType(StrEnum):
    """How a search hit matched the query.

    ``exact`` — canonical identifier equality; ``alias`` — curated alias
    equality; ``cross_version`` — provenance-bearing cross-assembly mapping;
    ``text`` — substring/prose match. Never inferred from similarity alone.
    """

    EXACT = "exact"
    ALIAS = "alias"
    CROSS_VERSION = "cross-version"
    TEXT = "text"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class GlobalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, examples=["GmFT2a"])
    types: list[SearchResultType] | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=50)
    assembly_id: int | None = Field(default=None, ge=1)


class SearchHit(BaseModel):
    id: str
    type: SearchResultType
    title: str
    subtitle: str | None = None
    highlight: str | None = None
    score: float = Field(..., ge=0.0)
    match_type: MatchType = MatchType.TEXT
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchSuggestion(BaseModel):
    text: str
    type: SearchResultType | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResultItem(BaseModel):
    """A single global-search hit (stable public contract).

    ``id`` is the canonical public identity of the entity: gene accession
    for genes, ``public_id`` for mutant lines. Private persistence keys are
    never placed here.
    """

    type: SearchResultType
    id: str
    name: str | None = None
    description: str | None = None
    score: float = Field(default=0.0, ge=0.0)
    match_type: MatchType = MatchType.TEXT
    url: str | None = None
    source: str = "internal"
    release_id: int | None = None
    assembly_id: int | None = None


class GlobalSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    by_type: dict[str, int] = Field(default_factory=dict)
    # Assembly-aware discovery context: counts per assembly and whether the
    # unscoped query matched several assemblies. Unscoped queries MUST NOT
    # silently pick a default assembly; clients group by ``assembly_id``.
    by_assembly: dict[str, int] = Field(default_factory=dict)
    ambiguous: bool = False
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = Field(default=0, ge=0)


class InternalMutantSearchItem(BaseModel):
    """Internal-search mutant hit: both identities plus the matched field.

    Only served by the authenticated internal search endpoint; never by
    external routes.
    """

    entity_type: SearchResultType = SearchResultType.MUTANT_LINE
    public_id: str
    internal_id: str
    name: str
    matched_field: str  # "public_id" | "name"
    match_type: MatchType = MatchType.TEXT
    is_public: bool
    release_id: int | None = None
    url: str | None = None


class InternalGeneSearchItem(BaseModel):
    entity_type: SearchResultType = SearchResultType.GENE
    gene_id: str
    internal_id: str
    name: str | None = None
    matched_field: str  # "accession" | "name" | "alias"
    match_type: MatchType = MatchType.TEXT
    assembly_id: int | None = None
    release_id: int | None = None
    url: str | None = None


class InternalSearchResponse(BaseModel):
    query: str
    mutants: list[InternalMutantSearchItem] = Field(default_factory=list)
    genes: list[InternalGeneSearchItem] = Field(default_factory=list)
    total_count: int = Field(default=0, ge=0)


class SortSpec(BaseModel):
    field: str
    order: SortOrder = SortOrder.ASC


class FilterCondition(BaseModel):
    field: str
    operator: str
    value: Any

    @field_validator("operator")
    @classmethod
    def _validate_operator(cls, v: str) -> str:
        allowed = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "like", "between"}
        if v not in allowed:
            raise ValueError(f"operator must be one of {sorted(allowed)}")
        return v


class AdvancedSearchRequest(BaseModel):
    filters: list[FilterCondition] = Field(default_factory=list)
    sort: list[SortSpec] = Field(max_length=5, default_factory=list)
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)

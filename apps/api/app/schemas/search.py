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


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class GlobalSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, examples=["GmFT2a"])
    types: list[SearchResultType] | None = None
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class SearchHit(BaseModel):
    id: str
    type: SearchResultType
    title: str
    subtitle: str | None = None
    highlight: str | None = None
    score: float = Field(..., ge=0.0)
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchSuggestion(BaseModel):
    text: str
    type: SearchResultType | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    description: str | None = None


class SearchResultItem(BaseModel):
    """A single global-search hit (stable public contract)."""

    type: SearchResultType
    id: str
    name: str | None = None
    description: str | None = None
    score: float = Field(default=0.0, ge=0.0)
    url: str | None = None
    source: str = "internal"


class GlobalSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    by_type: dict[str, int] = Field(default_factory=dict)
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = Field(default=0, ge=0)


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
    sort: list[SortSpec] = Field(default_factory=list, max_length=5)
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)

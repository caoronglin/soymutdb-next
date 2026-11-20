"""Strict schemas for saved admin data views.

A view is validated against the vocabulary of its data source, so a stored
configuration can never name a field or filter the source does not expose.
That keeps the saved-view layer a presentation of the release-scoped public
APIs rather than a parallel query surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataViewSource = Literal["genes", "variants", "mutant_lines"]
DataViewKind = Literal["grid", "kanban", "gallery"]
DataViewSortDir = Literal["asc", "desc"]
# A presentation flag, not a permission: ``hidden`` views stay stored and stay
# readable by id, they are only excluded from the saved-view list.
DataViewVisibility = Literal["visible", "hidden"]

# Field vocabulary of each read-only source, mirroring the row payloads the
# public API returns. Order is the natural fallback presentation order.
SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "genes": (
        "gene_id",
        "symbol",
        "name",
        "biotype",
        "assembly_name",
        "chromosome",
        "start_pos",
        "end_pos",
        "strand",
        "description",
        "variant_count",
        "high_impact_variants",
    ),
    "variants": (
        "variant_id",
        "chromosome",
        "position",
        "ref_allele",
        "alt_allele",
        "variant_type",
        "assembly",
        "consequence",
        "impact",
        "gene_id",
        "gene_symbol",
        "hgvs_p",
        "hgvs_c",
        "quality",
        "filter",
        "allele_frequency",
    ),
    "mutant_lines": (
        "public_id",
        "name",
        "mutagen",
        "cultivar",
        "variant_count",
    ),
}

# Query parameters each source's list endpoint accepts. A saved filter may only
# use these keys; unsupported keys are rejected rather than silently dropped.
SOURCE_FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "genes": (
        "q",
        "assembly_id",
        "chromosome",
        "biotype",
        "start_pos",
        "end_pos",
    ),
    "variants": (
        "assembly",
        "chromosome",
        "start",
        "end",
        "ref",
        "alt",
        "gene_id",
        "mutant_line_public_id",
        "variant_type",
        "consequence",
        "impact",
        "min_af",
        "max_af",
    ),
    "mutant_lines": ("q", "mutagen"),
}

# Default presentation per source: identity, locus and the count that explains
# why the row matters. Operators reorder or extend these in a saved view.
DEFAULT_VISIBLE_FIELDS: dict[str, tuple[str, ...]] = {
    "genes": ("gene_id", "symbol", "chromosome", "start_pos", "end_pos", "biotype"),
    "variants": (
        "variant_id",
        "chromosome",
        "position",
        "ref_allele",
        "alt_allele",
        "impact",
        "gene_id",
    ),
    "mutant_lines": ("public_id", "name", "mutagen", "cultivar", "variant_count"),
}


def _clean_field_list(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for field in value:
        normalized = field.strip()
        if not normalized:
            raise ValueError("field keys must not be blank")
        if normalized in cleaned:
            raise ValueError(f"duplicate field: {normalized}")
        cleaned.append(normalized)
    return cleaned


def _clean_filters(value: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, raw in value.items():
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("filter keys must not be blank")
        text = raw.strip()
        if not text:
            continue
        if len(text) > 512:
            raise ValueError(f"filter value for {normalized_key} is too long")
        cleaned[normalized_key] = text
    return cleaned


def _validate_vocabulary(
    *,
    source: str,
    view_type: str,
    visible_fields: list[str],
    searchable_fields: list[str],
    filters: dict[str, str],
    sort_field: str | None,
    sort_dir: str | None,
    group_field: str | None,
    title_field: str | None,
) -> None:
    fields = SOURCE_FIELDS.get(source)
    if fields is None:
        raise ValueError(f"unknown data source: {source}")
    filter_fields = SOURCE_FILTER_FIELDS[source]

    unknown_fields = [field for field in visible_fields if field not in fields]
    if unknown_fields:
        raise ValueError(f"fields not available for {source}: {', '.join(unknown_fields)}")

    unknown_searchable = [field for field in searchable_fields if field not in fields]
    if unknown_searchable:
        raise ValueError(
            f"searchable fields not available for {source}: {', '.join(unknown_searchable)}"
        )

    unknown_filters = [key for key in filters if key not in filter_fields]
    if unknown_filters:
        raise ValueError(f"filters not available for {source}: {', '.join(unknown_filters)}")

    if sort_field is not None and sort_field not in fields:
        raise ValueError(f"sort field not available for {source}: {sort_field}")
    if sort_dir is not None and sort_field is None:
        raise ValueError("sort_dir requires sort_field")
    if group_field is not None and group_field not in fields:
        raise ValueError(f"group field not available for {source}: {group_field}")
    if title_field is not None and title_field not in fields:
        raise ValueError(f"title field not available for {source}: {title_field}")
    if view_type == "kanban" and group_field is None:
        raise ValueError("kanban views require group_field")


class AdminDataViewBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    source: DataViewSource
    view_type: DataViewKind = "grid"
    visible_fields: list[str] = Field(min_length=1, max_length=40)
    searchable_fields: list[str] = Field(default_factory=list, max_length=40)
    filters: dict[str, str] = Field(default_factory=dict)
    sort_field: str | None = Field(default=None, max_length=64)
    sort_dir: DataViewSortDir | None = None
    group_field: str | None = Field(default=None, max_length=64)
    title_field: str | None = Field(default=None, max_length=64)
    page_size: int = Field(default=25, ge=5, le=200)
    is_default: bool = False
    notes: str | None = Field(default=None, max_length=2000)
    visibility: DataViewVisibility = "visible"

    @field_validator("visible_fields")
    @classmethod
    def _validate_visible_fields(cls, value: list[str]) -> list[str]:
        return _clean_field_list(value)

    @field_validator("searchable_fields")
    @classmethod
    def _validate_searchable_fields(cls, value: list[str]) -> list[str]:
        return _clean_field_list(value)

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, value: dict[str, str]) -> dict[str, str]:
        return _clean_filters(value)

    @model_validator(mode="after")
    def _validate_source_vocabulary(self) -> AdminDataViewBase:
        _validate_vocabulary(
            source=self.source,
            view_type=self.view_type,
            visible_fields=self.visible_fields,
            searchable_fields=self.searchable_fields,
            filters=self.filters,
            sort_field=self.sort_field,
            sort_dir=self.sort_dir,
            group_field=self.group_field,
            title_field=self.title_field,
        )
        return self


class AdminDataViewCreate(AdminDataViewBase):
    pass


class AdminDataViewUpdate(BaseModel):
    """Partial update. ``source`` is immutable, so the vocabulary stays fixed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    view_type: DataViewKind | None = None
    visible_fields: list[str] | None = Field(default=None, min_length=1, max_length=40)
    searchable_fields: list[str] | None = Field(default=None, max_length=40)
    filters: dict[str, str] | None = None
    sort_field: str | None = Field(default=None, max_length=64)
    sort_dir: DataViewSortDir | None = None
    group_field: str | None = Field(default=None, max_length=64)
    title_field: str | None = Field(default=None, max_length=64)
    page_size: int | None = Field(default=None, ge=5, le=200)
    is_default: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    visibility: DataViewVisibility | None = None

    @field_validator("visible_fields")
    @classmethod
    def _validate_visible_fields(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_field_list(value)

    @field_validator("searchable_fields")
    @classmethod
    def _validate_searchable_fields(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_field_list(value)

    @field_validator("filters")
    @classmethod
    def _validate_filters(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return None if value is None else _clean_filters(value)


class AdminDataViewResponse(AdminDataViewBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class AdminDataViewListResponse(BaseModel):
    items: list[AdminDataViewResponse]
    total: int


class DataViewSourceInfo(BaseModel):
    """The vocabulary the console uses to build view editors."""

    source: DataViewSource
    fields: list[str]
    filter_fields: list[str]
    default_fields: list[str]


class DataViewSourceListResponse(BaseModel):
    items: list[DataViewSourceInfo]


__all__ = [
    "AdminDataViewBase",
    "AdminDataViewCreate",
    "AdminDataViewListResponse",
    "AdminDataViewResponse",
    "AdminDataViewUpdate",
    "DEFAULT_VISIBLE_FIELDS",
    "DataViewKind",
    "DataViewSortDir",
    "DataViewSource",
    "DataViewSourceInfo",
    "DataViewSourceListResponse",
    "DataViewVisibility",
    "SOURCE_FIELDS",
    "SOURCE_FILTER_FIELDS",
]

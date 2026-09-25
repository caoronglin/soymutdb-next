"""Schemas for configurable table views and the species instance registry.

The public contract is deliberately small and vocabulary-only: the portal
receives an ordered column list plus which optional actions are enabled. No
biological record, no internal identifier, and no other species' configuration
is ever part of the response — a caller only ever sees the layout resolved for
its own species, site variant and release.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SiteVariant = Literal["external", "internal"]


class TableColumn(BaseModel):
    """One rendered column.

    ``key`` addresses the field in the API row payload; ``label_zh`` /
    ``label_en`` are the bilingual headers. ``visible=False`` keeps a column
    configured but hidden, which is how an operator stages a column without
    publishing it.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)
    label_zh: str = Field(min_length=1, max_length=128)
    label_en: str = Field(min_length=1, max_length=128)
    visible: bool = True


class TableActions(BaseModel):
    """Optional trailing action columns of a table view."""

    model_config = ConfigDict(extra="forbid")

    jbrowse: bool = False
    genome_preview: bool = False


class TableViewTemplateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    species: str = Field(default="Glycine max", max_length=128)
    site_variant: SiteVariant = "external"
    release_id: int | None = None
    is_default: bool = False
    columns: list[TableColumn] = Field(min_length=1)
    actions: TableActions = Field(default_factory=TableActions)
    notes: str | None = None


class TableViewTemplateCreate(TableViewTemplateBase):
    """POST body. ``kind`` is fixed per create call by the operator."""

    kind: Literal["mutation_sites", "variants", "genes", "mutant_lines"] = "mutation_sites"


class TableViewTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    columns: list[TableColumn] | None = Field(default=None, min_length=1)
    actions: TableActions | None = None
    is_default: bool | None = None
    release_id: int | None = None
    notes: str | None = None


class TableViewTemplateResponse(TableViewTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    created_at: datetime
    updated_at: datetime


class TableViewTemplateListResponse(BaseModel):
    items: list[TableViewTemplateResponse]
    total: int


class ResolvedTableView(BaseModel):
    """The layout the portal should render for this request."""

    kind: str
    species: str
    site_variant: SiteVariant
    release_id: int | None
    template_id: int | None
    template_name: str
    is_builtin_default: bool
    columns: list[TableColumn]
    actions: TableActions


class SpeciesInstanceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    species: str = Field(min_length=1, max_length=128)
    api_base_url: str = Field(min_length=1, max_length=512)
    jbrowse_base_url: str | None = Field(default=None, max_length=512)
    portal_base_url: str | None = Field(default=None, max_length=512)
    is_enabled: bool = True
    is_local: bool = False
    notes: str | None = None


class SpeciesInstanceCreate(SpeciesInstanceBase):
    pass


class SpeciesInstanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    api_base_url: str | None = Field(default=None, min_length=1, max_length=512)
    jbrowse_base_url: str | None = Field(default=None, max_length=512)
    portal_base_url: str | None = Field(default=None, max_length=512)
    is_enabled: bool | None = None
    is_local: bool | None = None
    notes: str | None = None


class SpeciesInstanceResponse(SpeciesInstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class SpeciesInstanceListResponse(BaseModel):
    items: list[SpeciesInstanceResponse]
    total: int


__all__ = [
    "ResolvedTableView",
    "SpeciesInstanceBase",
    "SpeciesInstanceCreate",
    "SpeciesInstanceListResponse",
    "SpeciesInstanceResponse",
    "SpeciesInstanceUpdate",
    "SiteVariant",
    "TableActions",
    "TableColumn",
    "TableViewTemplateBase",
    "TableViewTemplateCreate",
    "TableViewTemplateListResponse",
    "TableViewTemplateResponse",
    "TableViewTemplateUpdate",
]

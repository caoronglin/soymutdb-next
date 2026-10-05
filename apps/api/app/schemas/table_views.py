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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SiteVariant = Literal["external", "internal"]
ConnectionState = Literal["unknown", "healthy", "unhealthy", "disabled", "unconfigured"]
RemoteManagementState = Literal["local", "registration_only"]


def _validated_instance_url(value: str | None, *, allow_path: bool) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    try:
        parsed = urlsplit(normalized)
        # Accessing .port validates malformed port syntax.
        port = parsed.port
    except ValueError as exc:
        raise ValueError("instance URLs must be valid absolute HTTP(S) URLs") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (not allow_path and parsed.path not in {"", "/"})
    ):
        raise ValueError("instance URLs must be absolute HTTP(S) URLs without credentials or query")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port is not None else hostname
    path = parsed.path.rstrip("/") if allow_path else ""
    return f"{parsed.scheme.lower()}://{netloc}{path}"


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

    @field_validator("api_base_url")
    @classmethod
    def _validate_api_origin(cls, value: str) -> str:
        return _validated_instance_url(value, allow_path=False) or value

    @field_validator("jbrowse_base_url", "portal_base_url")
    @classmethod
    def _validate_site_urls(cls, value: str | None) -> str | None:
        return _validated_instance_url(value, allow_path=True)

    @model_validator(mode="after")
    def _remote_api_requires_https(self) -> SpeciesInstanceBase:
        if not self.is_local and urlsplit(self.api_base_url).scheme != "https":
            raise ValueError("remote instance API origins must use HTTPS")
        return self

    @model_validator(mode="before")
    @classmethod
    def _accept_site_url_alias(cls, value):
        if not isinstance(value, dict) or "site_url" not in value:
            return value
        normalized = dict(value)
        site_url = normalized.pop("site_url")
        if "portal_base_url" in normalized and normalized["portal_base_url"] != site_url:
            raise ValueError("site_url and portal_base_url cannot disagree")
        normalized["portal_base_url"] = site_url
        return normalized


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

    @field_validator("api_base_url")
    @classmethod
    def _validate_api_origin(cls, value: str | None) -> str | None:
        return _validated_instance_url(value, allow_path=False)

    @field_validator("jbrowse_base_url", "portal_base_url")
    @classmethod
    def _validate_site_urls(cls, value: str | None) -> str | None:
        return _validated_instance_url(value, allow_path=True)

    @model_validator(mode="before")
    @classmethod
    def _accept_site_url_alias(cls, value):
        if not isinstance(value, dict) or "site_url" not in value:
            return value
        normalized = dict(value)
        site_url = normalized.pop("site_url")
        if "portal_base_url" in normalized and normalized["portal_base_url"] != site_url:
            raise ValueError("site_url and portal_base_url cannot disagree")
        normalized["portal_base_url"] = site_url
        return normalized

    @model_validator(mode="after")
    def _remote_api_requires_https(self) -> SpeciesInstanceUpdate:
        if (
            self.api_base_url is not None
            and self.is_local is not True
            and urlsplit(self.api_base_url).scheme != "https"
        ):
            raise ValueError("remote instance API origins must use HTTPS")
        return self


class SpeciesInstanceResponse(SpeciesInstanceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    site_url: str | None = None
    connection_state: ConnectionState = "unknown"
    last_checked_at: datetime | None = None
    last_error_at: datetime | None = None
    is_stale: bool = True
    remote_management: RemoteManagementState
    created_at: datetime
    updated_at: datetime


class SpeciesInstanceHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    code: str
    connection_state: ConnectionState
    checked_at: datetime
    last_checked_at: datetime | None = None
    last_error_at: datetime | None = None
    is_stale: bool
    error_code: str | None = None
    remote_management: RemoteManagementState


class SpeciesInstanceListResponse(BaseModel):
    items: list[SpeciesInstanceResponse]
    total: int


__all__ = [
    "ResolvedTableView",
    "SpeciesInstanceBase",
    "SpeciesInstanceCreate",
    "SpeciesInstanceHealthResponse",
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

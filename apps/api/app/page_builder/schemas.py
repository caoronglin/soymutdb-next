"""Pydantic v2 request/response schemas for the Page Builder API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..core.compat import StrEnum


class PageDefinitionStatusEnum(StrEnum):
    DRAFT = "draft"
    PREVIEW = "preview"
    REQUESTED = "requested"
    PUBLISHED = "published"


class PageDefinitionSummary(BaseModel):
    id: uuid.UUID
    route: str
    title_key: str
    latest_version: int
    latest_status: PageDefinitionStatusEnum
    created_at: datetime
    updated_at: datetime


class PageDefinitionDetail(PageDefinitionSummary):
    pass


class PageDefinitionVersionResponse(BaseModel):
    id: uuid.UUID
    page_id: uuid.UUID
    version: int
    status: PageDefinitionStatusEnum
    definition: dict[str, Any]
    edited_by: uuid.UUID | None = None
    edit_comment: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PageDefinitionResponse(BaseModel):
    id: uuid.UUID
    route: str
    title_key: str
    versions: list[PageDefinitionVersionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PageDefinitionListResponse(BaseModel):
    items: list[PageDefinitionSummary] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class PageDefinitionCreate(BaseModel):
    route: str = Field(..., max_length=160)
    title_key: str = Field(..., min_length=1, max_length=160)
    definition: dict[str, Any]


class PageDefinitionUpdate(BaseModel):
    """Update a draft: version conflict is signalled by ``base_version``."""

    base_version: int = Field(..., ge=1)
    definition: dict[str, Any]
    edit_comment: str | None = Field(default=None, max_length=512)


class PreviewRequest(BaseModel):
    definition: dict[str, Any]


class PreviewResponse(BaseModel):
    definition: dict[str, Any]
    version_preview: int


class PublishRequest(BaseModel):
    """Request publication of the latest draft/preview version."""

    version_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=512)


class PublishRequestResponse(BaseModel):
    page_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    status: PageDefinitionStatusEnum
    event_id: str | None = None


class ComponentDescriptor(BaseModel):
    """A registry component exposed to Admin for the palette/property panel."""

    renderer_key: str
    label: str
    config_schema: dict[str, Any]
    allowed_children: list[str] = Field(default_factory=list)


class RegistryResponse(BaseModel):
    components: list[ComponentDescriptor] = Field(default_factory=list)


__all__ = [
    "ComponentDescriptor",
    "PageDefinitionCreate",
    "PageDefinitionDetail",
    "PageDefinitionListResponse",
    "PageDefinitionResponse",
    "PageDefinitionStatusEnum",
    "PageDefinitionSummary",
    "PageDefinitionUpdate",
    "PageDefinitionVersionResponse",
    "PreviewRequest",
    "PreviewResponse",
    "PublishRequest",
    "PublishRequestResponse",
    "RegistryResponse",
]

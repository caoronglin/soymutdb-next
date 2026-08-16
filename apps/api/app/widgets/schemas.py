"""Pydantic v2 schemas for widget system request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..core.compat import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WidgetCategoryEnum(StrEnum):
    HERO = "hero"
    NAVIGATION = "navigation"
    SEARCH = "search"
    DATA_TABLE = "data_table"
    DETAIL = "detail"
    VISUALIZATION = "visualization"
    STATS = "stats"
    EXTERNAL = "external"
    LAYOUT = "layout"
    CUSTOM = "custom"


class WidgetPermissionEnum(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Widget CRUD schemas
# ---------------------------------------------------------------------------


class WidgetResponse(BaseModel):
    """Full widget descriptor returned by admin endpoints."""

    id: int
    name: str
    display_name: str
    description: str | None = None
    category: WidgetCategoryEnum
    template_path: str
    data_source: str | None = None
    params_schema: dict[str, Any] = Field(default_factory=dict)
    cache_ttl: int = Field(default=300, ge=0)
    admin_config: dict[str, Any] = Field(default_factory=dict)
    permissions: WidgetPermissionEnum = WidgetPermissionEnum.PUBLIC
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WidgetDescriptor(BaseModel):
    """Lightweight widget descriptor served to the public layout endpoint."""

    name: str
    display_name: str
    category: WidgetCategoryEnum
    params_schema: dict[str, Any] = Field(default_factory=dict)
    cache_ttl: int = 300

    model_config = {"from_attributes": True}


class WidgetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    category: WidgetCategoryEnum = WidgetCategoryEnum.CUSTOM
    template_path: str = Field(..., min_length=1, max_length=512)
    data_source: str | None = Field(default=None, max_length=256)
    params_schema: dict[str, Any] = Field(default_factory=dict)
    cache_ttl: int = Field(default=300, ge=0, le=86400)
    admin_config: dict[str, Any] = Field(default_factory=dict)
    permissions: WidgetPermissionEnum = WidgetPermissionEnum.PUBLIC
    is_active: bool = True


class WidgetUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    category: WidgetCategoryEnum | None = None
    template_path: str | None = Field(default=None, min_length=1, max_length=512)
    data_source: str | None = Field(default=None, max_length=256)
    params_schema: dict[str, Any] | None = None
    cache_ttl: int | None = Field(default=None, ge=0, le=86400)
    admin_config: dict[str, Any] | None = None
    permissions: WidgetPermissionEnum | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Layout schemas
# ---------------------------------------------------------------------------


class LayoutResponse(BaseModel):
    page_name: str
    display_name: str | None = None
    widgets: list[WidgetDescriptor] = Field(default_factory=list)


class LayoutUpdateRequest(BaseModel):
    widget_order: list[str] = Field(default_factory=list)
    display_name: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Preview / Health schemas
# ---------------------------------------------------------------------------


class WidgetPreviewRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class WidgetHealthItem(BaseModel):
    """Per-widget health/metrics summary.

    The API does not yet collect per-widget latency/history, so current
    deployments return an empty ``widgets`` list; the shape is kept stable so
    Admin can render the same contract once metrics collection exists.
    """

    name: str
    display_name: str
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    cache_hit_rate: float = 0.0
    error_count: int = 0
    request_count: int = 0
    cache_hit_history: list[dict[str, object]] = Field(default_factory=list)
    latency_history: list[dict[str, object]] = Field(default_factory=list)


class WidgetHealthResponse(BaseModel):
    total_widgets: int
    active_widgets: int
    total_layouts: int
    active_layouts: int
    builtin_templates: list[str]
    cache_backend: str = "redis"
    widgets: list[WidgetHealthItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class WidgetListResponse(BaseModel):
    items: list[WidgetResponse] = Field(default_factory=list)
    total: int = 0


__all__ = [
    "LayoutResponse",
    "LayoutUpdateRequest",
    "WidgetCategoryEnum",
    "WidgetCreate",
    "WidgetDescriptor",
    "WidgetHealthItem",
    "WidgetHealthResponse",
    "WidgetListResponse",
    "WidgetPermissionEnum",
    "WidgetPreviewRequest",
    "WidgetResponse",
    "WidgetUpdate",
]

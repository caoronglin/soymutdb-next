"""Widget system – modular, cacheable UI fragments with Jinja2 rendering.

Provides DB-backed widget definitions, page layouts, Redis-cached HTML
rendering with bleach sanitization, and public/admin FastAPI endpoints.
"""

from .engine import WidgetEngine, render_error_fragment, sanitize_html
from .cache import WidgetCache
from .models import PageLayout, Widget, WidgetCategory, WidgetPermission
from .schemas import (
    LayoutResponse,
    WidgetCreate,
    WidgetDescriptor,
    WidgetHealthResponse,
    WidgetPreviewRequest,
    WidgetResponse,
    WidgetUpdate,
)

__all__ = [
    "LayoutResponse",
    "PageLayout",
    "Widget",
    "WidgetCache",
    "WidgetCategory",
    "WidgetCreate",
    "WidgetDescriptor",
    "WidgetEngine",
    "WidgetHealthResponse",
    "WidgetPermission",
    "WidgetPreviewRequest",
    "WidgetResponse",
    "WidgetUpdate",
    "render_error_fragment",
    "sanitize_html",
]

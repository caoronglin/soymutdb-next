"""Widget and PageLayout ORM models.

Widgets are reusable UI fragments rendered via Jinja2 templates.
PageLayouts define ordered collections of widgets for named pages.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, TimestampMixin, enum_values


class WidgetCategory(StrEnum):
    """High-level categorisation for widget admin UI."""

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


class WidgetPermission(StrEnum):
    """Access level required to view a widget."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMIN = "admin"


class Widget(Base, TimestampMixin):
    """A renderable UI fragment backed by a Jinja2 template.

    ``name`` is the unique machine-readable identifier used in URLs and
    ``PageLayout.widget_order``.  ``template_path`` is resolved relative to
    the widgets templates directory.  ``data_source`` optionally names a
    Python callable that provides template context; if ``None`` the widget
    renders with only the request parameters.
    """

    __tablename__ = "widgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        Enum(
            WidgetCategory,
            name="widget_category_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=WidgetCategory.CUSTOM,
        server_default=WidgetCategory.CUSTOM.value,
        nullable=False,
    )
    template_path: Mapped[str] = mapped_column(String(512), nullable=False)
    data_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    params_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    cache_ttl: Mapped[int] = mapped_column(
        Integer, default=300, server_default="300", nullable=False
    )
    admin_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    permissions: Mapped[str] = mapped_column(
        Enum(
            WidgetPermission,
            name="widget_permission_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=WidgetPermission.PUBLIC,
        server_default=WidgetPermission.PUBLIC.value,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )

    __table_args__ = ()

    def __repr__(self) -> str:
        return f"<Widget id={self.id} name={self.name!r} category={self.category}>"


class PageLayout(Base, TimestampMixin):
    """Ordered list of widget names for a named page.

    ``widget_order`` is a JSONB array of widget name strings in render order.
    """

    __tablename__ = "page_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    widget_order: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )

    def __repr__(self) -> str:
        return f"<PageLayout id={self.id} page={self.page_name!r} widgets={len(self.widget_order)}>"


__all__ = [
    "PageLayout",
    "Widget",
    "WidgetCategory",
    "WidgetPermission",
]

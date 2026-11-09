"""Saved multi-view configurations for the admin data workspace.

A data view is an operator-authored presentation of one read-only data source
(``genes``, ``variants`` or ``mutant_lines``): which fields to show, which
filters to apply, how to sort, and whether to render the rows as a grid,
kanban board or gallery. It stores *configuration only* — no biological
records, no identifiers, and no internal persistence keys — so a view can be
shared inside the console without widening any data-access boundary.

The public read APIs stay release-scoped and public-record-only; this table
does not add a second data store or an unreleased-record bypass.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdminDataView(Base):
    """One saved view over a read-only admin data source."""

    __tablename__ = "admin_data_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    view_type: Mapped[str] = mapped_column(
        String(16), default="grid", server_default="grid", nullable=False
    )
    # Ordered field keys to render: the order in the array is the column order.
    visible_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Query filters keyed by the source's allowlisted parameter names.
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sort_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_dir: Mapped[str | None] = mapped_column(String(4), nullable=True)
    # Kanban grouping field; required for ``view_type='kanban'`` by the schema.
    group_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Gallery card title field; ``None`` falls back to the first visible field.
    title_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_size: Mapped[int] = mapped_column(
        Integer, default=25, server_default="25", nullable=False
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('genes', 'variants', 'mutant_lines')",
            name="ck_admin_data_views_source",
        ),
        CheckConstraint(
            "view_type IN ('grid', 'kanban', 'gallery')",
            name="ck_admin_data_views_view_type",
        ),
        CheckConstraint(
            "sort_dir IS NULL OR sort_dir IN ('asc', 'desc')",
            name="ck_admin_data_views_sort_dir",
        ),
        CheckConstraint(
            "jsonb_typeof(visible_fields) = 'array'",
            name="ck_admin_data_views_visible_fields_array",
        ),
        CheckConstraint(
            "jsonb_typeof(filters) = 'object'",
            name="ck_admin_data_views_filters_object",
        ),
        CheckConstraint(
            "page_size BETWEEN 5 AND 200",
            name="ck_admin_data_views_page_size",
        ),
        UniqueConstraint("source", "name", name="uq_admin_data_views_source_name"),
        Index(
            "uq_admin_data_views_default",
            "source",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


__all__ = ["AdminDataView"]
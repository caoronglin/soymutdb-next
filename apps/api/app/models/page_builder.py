"""Versioned, schema-validated page definitions (Safe Admin Page Builder).

A ``PageDefinition`` is a public route (e.g. ``/``, ``/about``, ``/search``).
Every edit produces an immutable ``PageDefinitionVersion`` with an ordered
component tree validated against the server-owned component registry
(:mod:`app.page_builder.registry`).  Publication always references an
immutable version; the raw ``definition`` JSONB is never mutated once it
carries a ``published`` status.

Version lifecycle (``status``):
  ``draft`` -> ``preview`` -> ``published`` / ``requested``
  Only a ``draft`` or ``preview`` version may be edited; ``published``
  versions are immutable and referenced by name from the publication layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.compat import StrEnum
from .base import Base, TimestampMixin, enum_values


class PageDefinitionStatus(StrEnum):
    """Lifecycle status for a versioned page definition."""

    DRAFT = "draft"
    PREVIEW = "preview"
    REQUESTED = "requested"
    PUBLISHED = "published"


class PageDefinition(Base, TimestampMixin):
    """A stable, route-addressed page in the public site tree."""

    __tablename__ = "page_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    route: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    title_key: Mapped[str] = mapped_column(String(160), nullable=False)

    versions: Mapped[list[PageDefinitionVersion]] = relationship(
        back_populates="page",
        lazy="noload",
        order_by="PageDefinitionVersion.version.desc()",
    )

    def __repr__(self) -> str:
        return f"<PageDefinition id={self.id} route={self.route!r}>"


class PageDefinitionVersion(Base, TimestampMixin):
    """An immutable snapshot of a page's component tree at a given version."""

    __tablename__ = "page_definition_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("page_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            PageDefinitionStatus,
            name="page_definition_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=PageDefinitionStatus.DRAFT,
        server_default=PageDefinitionStatus.DRAFT.value,
        nullable=False,
    )
    definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    edit_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    page: Mapped[PageDefinition] = relationship(back_populates="versions", lazy="joined")

    __table_args__ = (
        UniqueConstraint("page_id", "version", name="uq_page_def_version"),
        Index("ix_page_def_version_page_status", "page_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<PageDefinitionVersion id={self.id} page_id={self.page_id} "
            f"version={self.version} status={self.status!r}>"
        )


class PageTemplate(Base, TimestampMixin):
    """Reusable server-owned Page Builder starting point."""

    __tablename__ = "page_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    preview_image_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (Index("ix_page_templates_category_sort", "category", "sort_order"),)


__all__ = [
    "PageDefinition",
    "PageDefinitionStatus",
    "PageDefinitionVersion",
    "PageTemplate",
]

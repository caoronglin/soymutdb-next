"""Configurable table views (column templates) and the species instance registry.

Two tables back the "one admin panel, many deployed species databases"
requirement:

``table_view_templates``
    An ordered, admin-authored column set for a given *kind* of table
    (``mutation_sites`` first). A template is scoped by species + site variant +
    release, so two deployments of the same code never share a column set, and a
    release switch can show a different layout without redeploying.

``species_instances``
    One registry row per deployed species database (different servers/origins).
    The admin console reads it to know which instance it is talking to and which
    others exist; the *data* still lives in each instance's own PostgreSQL, so
    no cross-instance biological record is ever merged.

Both tables are content/configuration, not biological records: they carry no
internal identifiers of mutants, genes or variants, and the public read path
returns only the resolved column vocabulary for the caller's own
release/site-variant context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TableViewTemplate(Base):
    """An ordered column set for one kind of portal table."""

    __tablename__ = "table_view_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    species: Mapped[str] = mapped_column(
        String(128), default="Glycine max", server_default="Glycine max", nullable=False
    )
    site_variant: Mapped[str] = mapped_column(String(16), nullable=False, default="external")
    # NULL release means "applies to every release" — the deployment-wide default.
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Ordered column definitions: [{key, label_zh, label_en, visible}] — the
    # order in the JSON is the rendered column order.
    columns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Optional trailing actions: {"jbrowse": bool, "genome_preview": bool}.
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SpeciesInstance(Base):
    """One deployed species database behind the shared admin console."""

    __tablename__ = "species_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    species: Mapped[str] = mapped_column(String(128), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    jbrowse_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    portal_base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # The instance this admin console talks to by default; exactly one row per
    # deployment is expected to carry it (enforced by the unique index).
    is_local: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    connection_state: Mapped[str] = mapped_column(
        String(16), default="unknown", server_default="unknown", nullable=False
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "connection_state IN ('unknown', 'healthy', 'unhealthy', 'disabled', 'unconfigured')",
            name="ck_species_instances_connection_state",
        ),
    )


__all__ = ["TableViewTemplate", "SpeciesInstance"]

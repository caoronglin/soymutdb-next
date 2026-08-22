"""Immutable import-studio chain models.

The chain is DatasetVersion -> ImportDraft -> FieldMapping -> DataPatch ->
PageDataSource.  Raw uploads are never overwritten: every edit is recorded as
an explicit, bounded patch against the immutable version, and commit creates
a publication manifest before the draft can be bound to a PageDefinition.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import AuditMixin, Base, TimestampMixin, enum_values


class ImportDraftStatus(enum.StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    READY = "ready"
    COMMITTED = "committed"
    FAILED = "failed"


class DatasetVersion(Base, TimestampMixin, AuditMixin):
    """One immutable version of a dataset's raw object metadata."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version",
            name="uq_dataset_versions_dataset_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("data_sets.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_objects: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            ImportDraftStatus,
            name="import_draft_status_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        default=ImportDraftStatus.DRAFT.value,
        server_default=ImportDraftStatus.DRAFT.value,
    )


class ImportDraft(Base, TimestampMixin, AuditMixin):
    """A user-created editing session over one immutable dataset version."""

    __tablename__ = "import_drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    field_mapping: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    validation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        Enum(
            ImportDraftStatus,
            name="import_draft_status_enum",
            values_callable=enum_values,
        ),
        nullable=False,
        default=ImportDraftStatus.DRAFT.value,
        server_default=ImportDraftStatus.DRAFT.value,
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FieldMapping(Base, TimestampMixin, AuditMixin):
    """One source-to-target column mapping for an import draft."""

    __tablename__ = "import_field_mappings"
    __table_args__ = (
        UniqueConstraint(
            "import_draft_id",
            "source_field",
            name="uq_import_field_mappings_draft_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_draft_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("import_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_field: Mapped[str] = mapped_column(String(256), nullable=False)
    target_field: Mapped[str] = mapped_column(String(256), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transform: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )


class DataPatch(Base, TimestampMixin, AuditMixin):
    """A bounded cell-level correction; raw rows are never overwritten."""

    __tablename__ = "import_data_patches"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_draft_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("import_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_key: Mapped[str] = mapped_column(String(512), nullable=False)
    column_name: Mapped[str] = mapped_column(String(256), nullable=False)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    patch_type: Mapped[str] = mapped_column(String(32), nullable=False)
    applied: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )


class PageDataSource(Base, TimestampMixin, AuditMixin):
    """A bounded page-binding to an immutable dataset version."""

    __tablename__ = "page_data_sources"
    __table_args__ = (
        UniqueConstraint(
            "page_id",
            "source_id",
            name="uq_page_data_sources_page_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("page_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PublicationManifest(Base, TimestampMixin, AuditMixin):
    """Immutable publication evidence for one committed import draft."""

    __tablename__ = "import_publication_manifests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_draft_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("import_drafts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "DataPatch",
    "DatasetVersion",
    "FieldMapping",
    "ImportDraft",
    "ImportDraftStatus",
    "PageDataSource",
    "PublicationManifest",
]

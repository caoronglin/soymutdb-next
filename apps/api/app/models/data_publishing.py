"""Persistence models for the data publishing pipeline."""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values


class ImportStatus(str, enum.Enum):
    UPLOADING = "uploading"
    VALIDATING = "validating"
    INGESTING = "ingesting"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    QUEUED = UPLOADING
    RUNNING = VALIDATING
    COMPLETED = READY


class DataSet(Base, TimestampMixin):
    __tablename__ = "data_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id", ondelete="SET NULL"))
    source_objects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status_enum", values_callable=enum_values),
        nullable=False, server_default=ImportStatus.UPLOADING.value,
    )
    validation_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ReleaseDataSet(Base):
    __tablename__ = "release_data_sets"

    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True)
    data_set_id: Mapped[int] = mapped_column(ForeignKey("data_sets.id", ondelete="CASCADE"), primary_key=True)


class ActiveRelease(Base):
    __tablename__ = "active_release"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    release_id: Mapped[int | None] = mapped_column(ForeignKey("releases.id", ondelete="RESTRICT"))


class Provenance(Base, TimestampMixin):
    __tablename__ = "provenance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_set_id: Mapped[int] = mapped_column(ForeignKey("data_sets.id", ondelete="CASCADE"), index=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(128))
    tool_version: Mapped[str | None] = mapped_column(String(64))


__all__ = ["ActiveRelease", "DataSet", "ImportStatus", "Provenance", "ReleaseDataSet"]

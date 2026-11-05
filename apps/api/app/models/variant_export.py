"""Durable owner-scoped variant export records.

An export request is an *owned artifact*: the submitter must be able to ask
"is my export ready?" and to download the produced file.  PostgreSQL is the
system of record for that state — the transactional outbox only owns
delivery, and the Celery/Redis result backend is disposable, so neither can
answer the question (see the plan's Task 5).

Two rules shape this table:

* The status vocabulary is the shared job state machine
  (``soymutdb_jobs.status.JobStatus``: pending/running/succeeded/failed), so
  the API and the worker cannot drift apart.
* The row stores the artifact's **object key**, never a long-lived URL.
  Download links are signed on demand for the requester, so a leaked row
  never hands out a permanent public link.
"""

from __future__ import annotations

import enum
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values


class VariantExportStatus(enum.StrEnum):
    """Export lifecycle states (shared job vocabulary)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VariantExport(Base, TimestampMixin):
    __tablename__ = "variant_exports"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    #: The submitter.  ``SET NULL`` on delete keeps the audit trail when a
    #: user account is removed; a record without an owner is admin-only.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            VariantExportStatus,
            name="variant_export_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=VariantExportStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    #: Release/assembly the artifact was built from — a download always
    #: states its coordinate namespace.  ``release_key`` is the release
    #: primary key spelled the same way as the export filters and the
    #: artifact's own column, so the whole chain uses one vocabulary.
    release_key: Mapped[str] = mapped_column(String(64), nullable=False)
    assembly_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    compress: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    #: Resolved, already-authorised filters (public identities only).
    #:
    #: This column is **internal**: it holds the worker's join keys (among
    #: them the resolved mutant-line *name*, which the worker needs and
    #: which the public artifact deliberately omits) and is never serialised
    #: to a client.  The public contracts expose the status fields and the
    #: signed link, not the filter document.
    filters: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: MinIO/S3 object key of the produced artifact (never a URL).
    artifact_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: When the artifact stops being downloadable (7 days after completion).
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Provenance of the exact bytes stored at ``artifact_path``. ``sha256``
    #: stays NULL for artifacts produced before checksum recording shipped;
    #: a manifest must say so rather than invent a digest.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license: Mapped[str | None] = mapped_column(String(256), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (
        Index("ix_variant_exports_user_id", "user_id"),
        Index("ix_variant_exports_status", "status"),
        Index("ix_variant_exports_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<VariantExport id={self.id} status={self.status!r} "
            f"format={self.format!r}>"
        )


__all__ = ["VariantExport", "VariantExportStatus"]

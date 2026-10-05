"""Analysis job model (fastp / scanpy RNA-seq pipelines).

Job rows are written by the API in the same transaction as the outbox event
(see ``app.services.analyses_service``); the worker advances the status and
writes ``result_summary`` when the pipeline completes.

The status vocabulary mirrors the shared Job state machine
(``soymutdb_jobs.status.JobStatus``) so API responses and worker updates
always agree.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values


class AnalysisType(enum.StrEnum):
    """Supported analysis pipelines."""

    FASTP = "fastp"
    SCANPY = "scanpy"


class AnalysisJobStatus(enum.StrEnum):
    """Job status values – kept in sync with ``soymutdb_jobs.status.JobStatus``."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class AnalysisJob(Base, TimestampMixin):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    analysis_type: Mapped[str] = mapped_column(
        Enum(
            AnalysisType,
            name="analysis_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    #: MinIO object keys of the uploaded inputs (always under ``analyses/``).
    input_objects: Mapped[list] = mapped_column(JSONB, nullable=False)
    #: Whitelisted pipeline parameters (validated at the API boundary).
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        Enum(
            AnalysisJobStatus,
            name="analysis_job_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=AnalysisJobStatus.QUEUED,
        server_default="queued",
        nullable=False,
    )
    #: Worker-written summary of the finished pipeline (fastp report / scanpy
    #: clustering stats); ``None`` until the job completes.
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_analysis_jobs_status", "status"),
        Index("ix_analysis_jobs_user_id", "user_id"),
        Index("ix_analysis_jobs_type_status", "analysis_type", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisJob id={self.id} type={self.analysis_type!r} "
            f"status={self.status!r}>"
        )


__all__ = ["AnalysisJob", "AnalysisJobStatus", "AnalysisType"]

"""GWAS job model (EMMAX / GEMMA association runs).

Job rows are written by the API in the same transaction as the outbox event
(see ``app.services.gwas_service``); the worker advances the status and
writes ``result_summary`` (MinIO object keys of the Manhattan / QQ / HTML /
raw assoc outputs) when the association run completes.

The status vocabulary mirrors the shared Job state machine
(``soymutdb_jobs.status.JobStatus``) with the BLAST-style spelling
(``pending/running/completed/failed/cancelled``), matching the PostgreSQL
enum created by migration 0011.
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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values


class GwasMethod(enum.StrEnum):
    """Supported association-testing engines."""

    EMMAX = "emmax"
    GEMMA = "gemma"


class GwasFileType(enum.StrEnum):
    """Phenotype/genotype input file family.

    ``snp`` is the EMMAX-style single-column-per-SNP phenotype format; the
    ``other`` bucket covers tabular genotype/phenotype layouts handled by the
    worker's parser.
    """

    SNP = "snp"
    OTHER = "other"


class GwasJobStatus(enum.StrEnum):
    """Job status values – BLAST-style spelling aligned with the shared state
    machine (``soymutdb_jobs.status.JobStatus``)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GwasJob(Base, TimestampMixin):
    __tablename__ = "gwas_jobs"

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
    #: MinIO object key of the uploaded phenotype file (``gwas/{job}/input/``).
    phenotype_file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    #: Optional MinIO object keys for genotype / kinship / covariate inputs.
    genotype_file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    kinship_file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    covariate_file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    object_type: Mapped[str] = mapped_column(
        Enum(
            GwasFileType,
            name="gwas_file_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=GwasFileType.SNP,
        server_default="snp",
        nullable=False,
    )
    method: Mapped[str] = mapped_column(
        Enum(
            GwasMethod,
            name="gwas_method_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    #: Whitelisted association parameters (validated at the API boundary).
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            GwasJobStatus,
            name="gwas_job_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=GwasJobStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    #: Worker-written summary: MinIO object keys of manhattan.json / qq.json /
    #: Manhattan_QQ.html / raw assoc TSV plus association statistics.
    result_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_gwas_jobs_status", "status"),
        Index("ix_gwas_jobs_user_id", "user_id"),
        Index("ix_gwas_jobs_method_status", "method", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<GwasJob id={self.id} method={self.method!r} status={self.status!r}>"
        )


__all__ = ["GwasFileType", "GwasJob", "GwasJobStatus", "GwasMethod"]

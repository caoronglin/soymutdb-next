"""Import task model for tracking data import jobs (VCF, GFF3, FASTA, etc.)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values

if TYPE_CHECKING:
    pass


class ImportTaskType(str, enum.Enum):
    """Type of data being imported."""

    VCF = "vcf"
    GFF3 = "gff3"
    FASTA = "fasta"
    BLAST_DB = "blast_db"
    SEED_DATA = "seed_data"
    EXPRESSION_CSV = "expression_csv"
    HOMOLOG_CSV = "homolog_csv"


class ImportTaskStatus(str, enum.Enum):
    """Status of an import task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportTask(Base, TimestampMixin):
    __tablename__ = "import_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(
        Enum(ImportTaskType, name="import_task_type_enum", create_constraint=True, values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(ImportTaskStatus, name="import_task_status_enum", create_constraint=True, values_callable=enum_values),
        nullable=False,
        default=ImportTaskStatus.QUEUED,
        server_default="queued",
    )
    progress: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_records: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    processed_records: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    submitted_by: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ImportTask id={self.id} filename={self.filename!r} "
            f"type={self.type!r} status={self.status!r}>"
        )


__all__ = [
    "ImportTask",
    "ImportTaskType",
    "ImportTaskStatus",
]

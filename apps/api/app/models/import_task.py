"""Import task model for tracking data import jobs (VCF, GFF3, FASTA, etc.)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, enum_values
from .data_publishing import ImportStatus

if TYPE_CHECKING:
    pass


class ImportTaskType(StrEnum):
    """Type of data being imported."""

    VCF = "vcf"
    GFF3 = "gff3"
    FASTA = "fasta"
    BLAST_DB = "blast_db"
    SEED_DATA = "seed_data"
    EXPRESSION_CSV = "expression_csv"
    HOMOLOG_CSV = "homolog_csv"
    MODULE_TSV = "module_tsv"


ImportTaskStatus = ImportStatus


class ImportTask(Base, TimestampMixin):
    __tablename__ = "import_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(
        Enum(
            ImportTaskType,
            name="import_task_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(ImportStatus, name="import_status_enum", values_callable=enum_values),
        nullable=False,
        default=ImportStatus.UPLOADING,
        server_default=ImportStatus.UPLOADING.value,
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
    celery_task_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    submitted_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    data_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sets.id", ondelete="SET NULL"
    ), nullable=True)
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"
    ), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(256
    ), nullable=False, unique=True, default=lambda: "legacy")
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failed_batch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_import_tasks_idempotency_key"),)

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

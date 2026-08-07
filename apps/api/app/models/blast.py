"""BLAST database and job models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

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
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class BlastDbType(str, enum.Enum):
    NUCL = "nucl"
    PROT = "prot"


class BlastProgram(str, enum.Enum):
    BLASTN = "blastn"
    BLASTP = "blastp"
    BLASTX = "blastx"
    TBLASTN = "tblastn"
    TBLASTX = "tblastx"


class BlastJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BlastDatabase(Base, TimestampMixin):
    __tablename__ = "blast_databases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    db_type: Mapped[str] = mapped_column(
        Enum(BlastDbType, name="blast_db_type_enum", create_constraint=True),
        nullable=False,
    )
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    assembly = relationship("Assembly", lazy="joined")
    jobs: Mapped[list["BlastJob"]] = relationship(
        back_populates="database", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<BlastDatabase id={self.id} name={self.name!r}>"


class BlastJob(Base):
    __tablename__ = "blast_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    program: Mapped[str] = mapped_column(
        Enum(BlastProgram, name="blast_program_enum", create_constraint=True),
        nullable=False,
    )
    database_id: Mapped[int] = mapped_column(
        ForeignKey("blast_databases.id", ondelete="CASCADE"), nullable=False
    )
    query_sequence: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(BlastJobStatus, name="blast_job_status_enum", create_constraint=True),
        default=BlastJobStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    result_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    database: Mapped["BlastDatabase"] = relationship(
        back_populates="jobs", lazy="joined"
    )

    __table_args__ = (
        Index("ix_blast_job_user", "user_id"),
        Index("ix_blast_job_status", "status"),
        Index("ix_blast_job_submitted", "submitted_at"),
    )

    def __repr__(self) -> str:
        return f"<BlastJob id={self.id} program={self.program} status={self.status}>"


__all__ = [
    "BlastDatabase",
    "BlastDbType",
    "BlastJob",
    "BlastJobStatus",
    "BlastProgram",
]

"""BLAST database and job models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_values


class BlastDbType(StrEnum):
    NUCL = "nucl"
    PROT = "prot"


class BlastProgram(StrEnum):
    BLASTN = "blastn"
    BLASTP = "blastp"
    BLASTX = "blastx"
    TBLASTN = "tblastn"
    TBLASTX = "tblastx"


class BlastJobStatus(StrEnum):
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
        Enum(
            BlastDbType,
            name="blast_db_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
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
    jobs: Mapped[list[BlastJob]] = relationship(
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
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    program: Mapped[str] = mapped_column(
        Enum(
            BlastProgram,
            name="blast_program_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    database_id: Mapped[int] = mapped_column(
        ForeignKey("blast_databases.id", ondelete="CASCADE"), nullable=False
    )
    query_sequence: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            BlastJobStatus,
            name="blast_job_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=BlastJobStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    result_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    hit_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    query_len: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    database: Mapped[BlastDatabase] = relationship(
        back_populates="jobs", lazy="joined"
    )
    hits: Mapped[list[BlastHit]] = relationship(
        back_populates="job", lazy="noload", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_blast_job_user", "user_id"),
        Index("ix_blast_job_status", "status"),
        Index("ix_blast_job_submitted", "submitted_at"),
    )

    def __repr__(self) -> str:
        return f"<BlastJob id={self.id} program={self.program} status={self.status}>"


class BlastHit(Base):
    """One parsed HSP row from a completed BLAST job."""

    __tablename__ = "blast_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blast_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hsp_num: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    subject_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    percent_identity: Mapped[float] = mapped_column(Float, nullable=False)
    alignment_length: Mapped[int] = mapped_column(Integer, nullable=False)
    mismatches: Mapped[int] = mapped_column(Integer, nullable=False)
    gap_opens: Mapped[int] = mapped_column(Integer, nullable=False)
    query_start: Mapped[int] = mapped_column(Integer, nullable=False)
    query_end: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_start: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_end: Mapped[int] = mapped_column(Integer, nullable=False)
    evalue: Mapped[float] = mapped_column(Float, nullable=False)
    bit_score: Mapped[float] = mapped_column(Float, nullable=False)
    query_strand: Mapped[str] = mapped_column(
        String(8), default="plus", nullable=False
    )
    subject_strand: Mapped[str] = mapped_column(
        String(8), default="plus", nullable=False
    )

    job: Mapped[BlastJob] = relationship(back_populates="hits")

    __table_args__ = (
        Index("ix_blast_hits_job_evalue", "job_id", "evalue"),
        Index("ix_blast_hits_job_bit_score", "job_id", "bit_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<BlastHit job={self.job_id} subject={self.subject_id!r} "
            f"evalue={self.evalue}>"
        )


__all__ = [
    "BlastDatabase",
    "BlastDbType",
    "BlastHit",
    "BlastJob",
    "BlastJobStatus",
    "BlastProgram",
]

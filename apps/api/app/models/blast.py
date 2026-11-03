"""BLAST database and job models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
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
    __table_args__ = (
        CheckConstraint("engine IN ('diamond', 'ncbi_blast')", name="ck_blast_catalog_engine"),
        CheckConstraint(
            "sequence_type IS NULL OR sequence_type IN "
            "('genome', 'cds', 'transcript', 'protein', 'repeat_masked', "
            "'pan_genome', 'family_consensus', 'custom')",
            name="ck_blast_catalog_sequence_type",
        ),
        CheckConstraint(
            "build_status IN ('pending', 'building', 'validating', "
            "'published', 'failed', 'ready')",
            name="ck_blast_catalog_build_status",
        ),
        # Only a published (or legacy-ready) index carries an immutable
        # identity. Nothing may silently overwrite a live index directory.
        CheckConstraint(
            "index_version IS NULL OR index_version ~ '^[a-f0-9]{64}$'",
            name="ck_blast_catalog_index_identity",
        ),
        CheckConstraint("sequence_count >= 0", name="ck_blast_catalog_sequence_count"),
        CheckConstraint("total_length >= 0", name="ck_blast_catalog_total_length"),
        CheckConstraint(
            "fasta_sha256 IS NULL OR fasta_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_blast_catalog_fasta_sha256",
        ),
        Index(
            "uq_blast_catalog_active_default", "assembly_id", "engine", "db_type",
            unique=True, postgresql_where=text("is_active AND is_default"),
        ),
    )

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

    # Legacy rows are known DIAMOND indexes. Unknown source/annotation/license
    # remain NULL rather than fabricated provenance.
    engine: Mapped[str] = mapped_column(
        String(16), default="diamond", server_default="diamond", nullable=False
    )
    sequence_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    annotation_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    sequence_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    total_length: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    fasta_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_version: Mapped[str | None] = mapped_column(String(256), nullable=True)
    build_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    license: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    query_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
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


class BlastIndexBuild(Base, TimestampMixin):
    """One immutable NCBI index construction request (worker-only execution).

    The API records the request and writes an outbox event in the same
    transaction; only the Celery worker runs ``makeblastdb``. Every rebuild
    creates a new row and a new content-addressed ``index_identity`` — an
    existing published index is never mutated or overwritten.
    """

    __tablename__ = "blast_index_builds"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'building', 'validating', 'published', 'failed', 'ready')",
            name="ck_blast_index_build_state",
        ),
        CheckConstraint(
            "db_type IN ('nucl', 'prot')", name="ck_blast_index_build_db_type"
        ),
        CheckConstraint(
            "index_identity IS NULL OR index_identity ~ '^[a-f0-9]{64}$'",
            name="ck_blast_index_build_identity",
        ),
        CheckConstraint(
            "sequence_count >= 0", name="ck_blast_index_build_sequence_count"
        ),
        Index("ix_blast_index_build_state", "state"),
        Index("ix_blast_index_build_catalog", "database_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    #: Catalog row the published index will be bound to. NULL for a rebuild
    #: that has not yet been assigned a catalog entry.
    database_id: Mapped[int | None] = mapped_column(
        ForeignKey("blast_databases.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    #: MinIO object key of the reviewed source FASTA (not a local path).
    source_object_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Plain string: migration 0052 owns the check constraint. Reusing the
    # PostgreSQL enum type here would make create_all depend on enum lifecycle.
    db_type: Mapped[str] = mapped_column(String(4), nullable=False)
    #: Frozen assembly/release/annotation/source provenance for this build.
    build_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False)
    index_identity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_length: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Sanitized failure reason; child stderr, paths and sequences never land here.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<BlastIndexBuild id={self.id} state={self.state!r}>"




__all__ = [
    "BlastDatabase",
    "BlastDbType",
    "BlastHit",
    "BlastIndexBuild",
    "BlastJob",
    "BlastJobStatus",
    "BlastProgram",
]

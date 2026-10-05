"""Track and track category models."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, enum_values

if TYPE_CHECKING:
    from .auth import User
    from .genomic import Assembly


class TrackType(StrEnum):
    VARIANT = "variant"
    ALIGNMENT = "alignment"
    ANNOTATION = "annotation"
    QUANTITATIVE = "quantitative"
    DENSITY = "density"
    SV = "structural_variant"
    PHENOTYPE = "phenotype"


class FileFormat(StrEnum):
    VCF = "vcf"
    BAM = "bam"
    CRAM = "cram"
    BIGWIG = "bigwig"
    BIGBED = "bigbed"
    GFF3 = "gff3"
    BED = "bed"
    BW = "bw"


class TrackVisibility(StrEnum):
    PUBLIC = "public"
    PROJECT = "project"
    PRIVATE = "private"


class TrackStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    READY = "ready"
    ERROR = "error"
    DELETED = "deleted"


class TrackCategory(Base, TimestampMixin):
    __tablename__ = "track_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    tracks: Mapped[list[Track]] = relationship(
        back_populates="category", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<TrackCategory id={self.id} name={self.name!r}>"


class Track(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    track_type: Mapped[str] = mapped_column(
        Enum(
            TrackType,
            name="track_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    file_format: Mapped[str] = mapped_column(
        Enum(
            FileFormat,
            name="file_format_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    # Legacy databases already carry this nullable release pin.  Keep it in
    # the ORM so release-scoped projections can fail closed instead of silently
    # treating an unscoped track as belonging to the selected release.
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("track_categories.id", ondelete="SET NULL"), nullable=True
    )
    file_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    index_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[str] = mapped_column(
        Enum(
            TrackVisibility,
            name="track_visibility_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=TrackVisibility.PUBLIC,
        server_default="public",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum(
            TrackStatus,
            name="track_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=TrackStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    assembly: Mapped[Assembly] = relationship(lazy="joined")
    category: Mapped[TrackCategory | None] = relationship(
        back_populates="tracks", lazy="joined"
    )
    owner: Mapped[User | None] = relationship(lazy="joined")

    __table_args__ = (
        Index("ix_track_assembly", "assembly_id"),
        Index("ix_track_owner", "owner_id"),
        Index("ix_track_visibility", "visibility"),
        Index("ix_track_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Track id={self.id} name={self.name!r} type={self.track_type}>"


__all__ = [
    "FileFormat",
    "Track",
    "TrackCategory",
    "TrackStatus",
    "TrackType",
    "TrackVisibility",
]

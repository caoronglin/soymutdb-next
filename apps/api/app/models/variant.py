"""Variant summary, mutant-line and phenotype models.

Fix vs. reference: ``VariantType`` enum is unified to SNP/INS/DEL/MNV/SV
(the reference used inconsistent INSERTION/MNP/COMPLEX values).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, enum_values

if TYPE_CHECKING:
    from .content import Release
    from .genomic import Assembly, Chromosome, Gene
    from .seed import SeedInventory, SeedRequest


class VariantType(StrEnum):
    """Unified variant type enum: SNP / INS / DEL / MNV / SV."""

    SNP = "SNP"
    INS = "INS"
    DEL = "DEL"
    MNV = "MNV"
    SV = "SV"


class Impact(StrEnum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    MODIFIER = "MODIFIER"


class Consequence(StrEnum):
    MISSENSE = "missense_variant"
    NONSENSE = "stop_gained"
    SYNONYMOUS = "synonymous_variant"
    FRAMESHIFT = "frameshift_variant"
    SPLICE_DONOR = "splice_donor_variant"
    SPLICE_ACCEPTOR = "splice_acceptor_variant"
    INTRON = "intron_variant"
    UTR_5 = "5_prime_UTR_variant"
    UTR_3 = "3_prime_UTR_variant"
    UPSTREAM = "upstream_gene_variant"
    DOWNSTREAM = "downstream_gene_variant"
    INTERGENIC = "intergenic_variant"
    START_LOST = "start_lost"
    STOP_LOST = "stop_lost"
    INFRAME_INS = "inframe_insertion"
    INFRAME_DEL = "inframe_deletion"


class VariantSummary(Base):
    """Light PG table for FK references.

    Bulk variant data lives in ClickHouse (``variant_facts``).
    """

    __tablename__ = "variant_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    chromosome_id: Mapped[int] = mapped_column(
        ForeignKey("chromosomes.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ref: Mapped[str] = mapped_column(String(4096), nullable=False)
    alt: Mapped[str] = mapped_column(String(4096), nullable=False)
    variant_type: Mapped[str] = mapped_column(
        Enum(
            VariantType,
            name="variant_type_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    gene_id: Mapped[int | None] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="SET NULL"), nullable=True,
        comment="FK to genes.gene_pk (surrogate)",
    )
    consequence: Mapped[str | None] = mapped_column(String(128), nullable=True)
    impact: Mapped[str | None] = mapped_column(
        Enum(
            Impact,
            name="impact_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    mutant_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("mutant_lines.id", ondelete="SET NULL"), nullable=True
    )
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )

    assembly: Mapped[Assembly] = relationship(
        back_populates="variant_summaries", lazy="joined"
    )
    chromosome: Mapped[Chromosome] = relationship(
        back_populates="variant_summaries", lazy="joined"
    )
    gene: Mapped[Gene | None] = relationship(
        back_populates="variant_summaries", lazy="joined"
    )
    mutant_line: Mapped[MutantLine | None] = relationship(
        back_populates="variant_summaries", lazy="joined"
    )
    release: Mapped[Release | None] = relationship(
        back_populates="variant_summaries", lazy="noload"
    )

    __table_args__ = (
        Index("ix_vs_chr_pos", "chromosome_id", "position"),
        Index("ix_vs_gene", "gene_id"),
        Index("ix_vs_mutant_line", "mutant_line_id"),
        Index("ix_vs_release", "release_id"),
        Index("ix_vs_type_impact", "variant_type", "impact"),
    )

    def __repr__(self) -> str:
        return f"<VariantSummary id={self.id} chr={self.chromosome_id} pos={self.position}>"


class MutantLine(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "mutant_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable public identifier for external URLs/search/citation. Never
    # derived from the persistence key (``id``) or the lab designation
    # (``name``). Nullable only while unpublished; publication requires it.
    public_id: Mapped[str | None] = mapped_column(
        String(32), unique=True, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    species: Mapped[str] = mapped_column(
        String(128),
        default="Glycine max",
        server_default="Glycine max",
        nullable=False,
    )
    cultivar: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mutagen: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mutagen_dose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phenotype_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    release_id: Mapped[int | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )

    phenotypes: Mapped[list[Phenotype]] = relationship(
        back_populates="mutant_line",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    variant_summaries: Mapped[list[VariantSummary]] = relationship(
        back_populates="mutant_line", lazy="noload"
    )
    seed_inventory: Mapped[list[SeedInventory]] = relationship(
        back_populates="mutant_line", lazy="noload"
    )
    seed_requests: Mapped[list[SeedRequest]] = relationship(
        back_populates="mutant_line", lazy="noload"
    )
    release: Mapped[Release | None] = relationship(
        back_populates="mutant_lines", lazy="noload"
    )

    __table_args__ = (
        Index("ix_ml_mutagen", "mutagen"),
        Index("ix_ml_cultivar", "cultivar"),
        Index("ix_ml_release", "release_id"),
    )

    def __repr__(self) -> str:
        return f"<MutantLine id={self.id} name={self.name!r} public_id={self.public_id!r}>"


class Phenotype(Base, TimestampMixin):
    __tablename__ = "phenotypes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mutant_line_id: Mapped[int] = mapped_column(
        ForeignKey("mutant_lines.id", ondelete="CASCADE"), nullable=False
    )
    trait_category: Mapped[str] = mapped_column(String(128), nullable=False)
    trait_name: Mapped[str] = mapped_column(String(256), nullable=False)
    trait_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    measurement_method: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    mutant_line: Mapped[MutantLine] = relationship(
        back_populates="phenotypes", lazy="joined"
    )

    __table_args__ = (
        Index("ix_phenotype_ml", "mutant_line_id"),
        Index("ix_phenotype_trait", "trait_category", "trait_name"),
    )

    def __repr__(self) -> str:
        return f"<Phenotype id={self.id} trait={self.trait_name!r}>"


__all__ = [
    "Consequence",
    "Impact",
    "MutantLine",
    "Phenotype",
    "VariantSummary",
    "VariantType",
]

"""Genomic reference models: assemblies, chromosomes, genes, transcripts, exons, aliases."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .content import Release
    from .expression import ExpressionData, ExpressionLibrary
    from .gene_data_cache import GeneDataCache
    from .homolog import GeneHomolog
    from .variant import MutantLine, VariantSummary


class Assembly(Base, TimestampMixin):
    __tablename__ = "assemblies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    species: Mapped[str] = mapped_column(
        String(128), nullable=False, default="Glycine max"
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fasta_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    fai_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )

    chromosomes: Mapped[List["Chromosome"]] = relationship(
        back_populates="assembly",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    genes: Mapped[List["Gene"]] = relationship(
        back_populates="assembly", lazy="noload"
    )
    variant_summaries: Mapped[List["VariantSummary"]] = relationship(
        back_populates="assembly", lazy="noload"
    )
    expression_libraries: Mapped[List["ExpressionLibrary"]] = relationship(
        back_populates="assembly", lazy="noload"
    )
    release: Mapped[Optional["Release"]] = relationship(
        back_populates="assemblies",
        foreign_keys=[release_id],
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Assembly id={self.id} name={self.name!r}>"


class Chromosome(Base):
    __tablename__ = "chromosomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assembly: Mapped["Assembly"] = relationship(
        back_populates="chromosomes", lazy="joined"
    )
    genes: Mapped[List["Gene"]] = relationship(
        back_populates="chromosome", lazy="noload"
    )
    variant_summaries: Mapped[List["VariantSummary"]] = relationship(
        back_populates="chromosome", lazy="noload"
    )

    __table_args__ = (
        UniqueConstraint("assembly_id", "name", name="uq_chromosome_assembly_name"),
        Index("ix_chromosome_assembly_order", "assembly_id", "order"),
    )

    def __repr__(self) -> str:
        return f"<Chromosome id={self.id} name={self.name!r} length={self.length}>"


class Gene(Base, TimestampMixin):
    __tablename__ = "genes"

    # Surrogate persistence key. Gene accessions are only unique per assembly
    # (v4 and v5 are distinct namespaces), so the string accession can never
    # be the primary key. Child tables reference ``gene_pk``.
    gene_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    accession: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="e.g. Glyma.01G000100"
    )
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    chromosome_id: Mapped[int] = mapped_column(
        ForeignKey("chromosomes.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    biotype: Mapped[str] = mapped_column(
        String(64),
        default="protein_coding",
        server_default="protein_coding",
        nullable=False,
    )
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strand: Mapped[str] = mapped_column(String(1), nullable=False, comment="'+' or '-'")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    assembly: Mapped["Assembly"] = relationship(
        back_populates="genes", lazy="joined"
    )
    chromosome: Mapped["Chromosome"] = relationship(
        back_populates="genes", lazy="joined"
    )
    transcripts: Mapped[List["Transcript"]] = relationship(
        back_populates="gene",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    aliases: Mapped[List["GeneAlias"]] = relationship(
        back_populates="gene",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    variant_summaries: Mapped[List["VariantSummary"]] = relationship(
        back_populates="gene", lazy="noload"
    )
    expression_data: Mapped[List["ExpressionData"]] = relationship(
        back_populates="gene", lazy="noload"
    )
    homologs: Mapped[List["GeneHomolog"]] = relationship(
        back_populates="gene", lazy="noload"
    )
    data_cache: Mapped[Optional["GeneDataCache"]] = relationship(
        back_populates="gene", lazy="joined", uselist=False
    )

    __table_args__ = (
        UniqueConstraint(
            "assembly_id", "accession", name="uq_gene_assembly_accession"
        ),
        Index("ix_gene_accession", "accession"),
        Index("ix_gene_assembly_chr", "assembly_id", "chromosome_id"),
        Index("ix_gene_location", "chromosome_id", "start", "end"),
        Index("ix_gene_name", "name"),
        Index("ix_gene_biotype", "biotype"),
    )

    def __repr__(self) -> str:
        return f"<Gene gene_pk={self.gene_pk} accession={self.accession!r}>"


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    gene_id: Mapped[int] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="CASCADE"), nullable=False,
        comment="FK to genes.gene_pk (surrogate)",
    )
    name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    biotype: Mapped[str] = mapped_column(
        String(64), default="mRNA", server_default="mRNA", nullable=False
    )
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    strand: Mapped[str] = mapped_column(String(1), nullable=False)
    is_canonical: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    gene: Mapped["Gene"] = relationship(back_populates="transcripts", lazy="joined")
    exons: Mapped[List["Exon"]] = relationship(
        back_populates="transcript",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Exon.order",
    )

    __table_args__ = (
        Index("ix_transcript_gene", "gene_id"),
        Index("ix_transcript_location", "start", "end"),
    )

    def __repr__(self) -> str:
        return f"<Transcript id={self.id!r} gene={self.gene_id!r}>"


class Exon(Base):
    __tablename__ = "exons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[str] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    start: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    transcript: Mapped["Transcript"] = relationship(
        back_populates="exons", lazy="joined"
    )

    __table_args__ = (
        Index("ix_exon_transcript_order", "transcript_id", "order"),
    )

    def __repr__(self) -> str:
        return f"<Exon id={self.id} transcript={self.transcript_id!r} order={self.order}>"


class GeneAlias(Base):
    __tablename__ = "gene_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gene_id: Mapped[int] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="CASCADE"), nullable=False,
        comment="FK to genes.gene_pk (surrogate)",
    )
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    gene: Mapped["Gene"] = relationship(back_populates="aliases", lazy="joined")

    __table_args__ = (
        UniqueConstraint("gene_id", "alias", name="uq_gene_alias"),
        Index("ix_gene_alias_alias", "alias"),
    )

    def __repr__(self) -> str:
        return f"<GeneAlias gene={self.gene_id!r} alias={self.alias!r}>"


class GeneCrosswalk(Base, TimestampMixin):
    """Explicit, provenance-bearing cross-version gene mapping (e.g. v4↔v5).

    Equivalence between genes in different assemblies is ONLY expressed by
    rows in this table. It must never be inferred from string similarity or
    coordinate proximity.

    One row per (source, target) pair; one-to-many / many-to-one relations
    are represented by multiple rows, with ``relation_type`` carrying the
    curated semantics.
    """

    __tablename__ = "gene_crosswalks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_gene_id: Mapped[int] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="CASCADE"), nullable=False
    )
    target_gene_id: Mapped[int] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance_source: Mapped[str] = mapped_column(String(256), nullable=False)
    provenance_evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )

    source_gene: Mapped["Gene"] = relationship(
        foreign_keys=[source_gene_id], lazy="joined"
    )
    target_gene: Mapped["Gene"] = relationship(
        foreign_keys=[target_gene_id], lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_gene_id",
            "target_gene_id",
            "relation_type",
            name="uq_gene_crosswalk_pair_type",
        ),
        Index("ix_gene_crosswalk_source", "source_gene_id"),
        Index("ix_gene_crosswalk_target", "target_gene_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<GeneCrosswalk source={self.source_gene_id} "
            f"target={self.target_gene_id} type={self.relation_type!r}>"
        )


__all__ = [
    "Assembly",
    "Chromosome",
    "Exon",
    "Gene",
    "GeneCrosswalk",
    "GeneAlias",
    "Transcript",
]

"""Release-scoped gene annotation snapshots and their source provenance."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GeneAnnotationSet(Base):
    """One immutable, source-attributed ontology snapshot for a release."""

    __tablename__ = "gene_annotation_sets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assembly_id", "release_id"],
            ["assemblies.id", "assemblies.release_id"],
            name="fk_gene_annotation_sets_assembly_release",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "assembly_id",
            "release_id",
            "ontology",
            name="uq_gene_annotation_sets_scope",
        ),
        UniqueConstraint(
            "id",
            "assembly_id",
            "release_id",
            "ontology",
            name="uq_gene_annotation_sets_identity_scope",
        ),
        CheckConstraint("ontology IN ('go', 'kegg')", name="ck_gene_annotation_sets_ontology"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gene_annotation_sets_sha256",
        ),
        CheckConstraint("row_count > 0", name="ck_gene_annotation_sets_row_count"),
        Index(
            "ix_gene_annotation_sets_release_assembly_ontology",
            "release_id",
            "assembly_id",
            "ontology",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ontology: Mapped[str] = mapped_column(String(8), nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    importer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GeneAnnotation(Base):
    """One gene-to-term assertion, retaining its source evidence fields."""

    __tablename__ = "gene_annotations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["annotation_set_id", "assembly_id", "release_id", "ontology"],
            [
                "gene_annotation_sets.id",
                "gene_annotation_sets.assembly_id",
                "gene_annotation_sets.release_id",
                "gene_annotation_sets.ontology",
            ],
            name="fk_gene_annotations_set_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["assembly_id", "gene_id"],
            ["genes.assembly_id", "genes.accession"],
            name="fk_gene_annotations_gene_assembly",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "annotation_set_id",
            "gene_id",
            "term_id",
            "evidence_code",
            "reference",
            "qualifier",
            name="uq_gene_annotations_evidence",
        ),
        CheckConstraint("ontology IN ('go', 'kegg')", name="ck_gene_annotations_ontology"),
        Index(
            "ix_gene_annotations_release_assembly_ontology",
            "release_id",
            "assembly_id",
            "ontology",
        ),
        Index(
            "ix_gene_annotations_scope_term",
            "release_id",
            "assembly_id",
            "ontology",
            "term_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    annotation_set_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ontology: Mapped[str] = mapped_column(String(8), nullable=False)
    gene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    term_id: Mapped[str] = mapped_column(String(128), nullable=False)
    term_name: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_code: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("''")
    )
    reference: Mapped[str] = mapped_column(
        String(512), nullable=False, server_default=text("''")
    )
    qualifier: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default=text("''")
    )


__all__ = ["GeneAnnotation", "GeneAnnotationSet"]

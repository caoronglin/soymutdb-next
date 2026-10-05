"""Local-only records for the unpublished SoyMutDB test-data preview.

Rows in this table are deliberately separate from ``variant_summaries`` and
ClickHouse ``variant_facts``. The source TSV provides mutation-site locations
but no reference/alternate alleles, so these rows must never be represented as
variants or enter a publication release.

The table is created only by the guarded local import command. It is not part
of the Alembic production migration sequence.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class LocalTestMutationSite(Base, TimestampMixin):
    """Unpublished point records imported from the local ``03_soymut`` sample."""

    __tablename__ = "local_preview_mutation_sites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_site_key: Mapped[str] = mapped_column(String(128), nullable=False)
    mutant_line_name: Mapped[str] = mapped_column(String(128), nullable=False)
    assembly_id: Mapped[int] = mapped_column(Integer, nullable=False)
    release_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chromosome_id: Mapped[int] = mapped_column(
        ForeignKey("chromosomes.id", ondelete="CASCADE"), nullable=False
    )
    gene_pk: Mapped[int] = mapped_column(
        ForeignKey("genes.gene_pk", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[str] = mapped_column(String(1), nullable=False)
    feature: Mapped[str] = mapped_column(String(256), nullable=False)
    #: Operator-editable availability flag. Unlike the imported columns this one
    #: is meant to be changed after the fact from the admin console, so a
    #: re-import must not clobber an existing value.
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Homolog accessions supplied by the same source TSV: the Wm82.a2.v1 and
    #: Wm82.a4.v1 names and the DN53 v1 equivalent of the mutated gene. Nullable
    #: because the source rows do not always carry all three.
    gene_v2: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gene_v4: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gene_dn53: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_file: Mapped[str] = mapped_column(String(256), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    annotation_file: Mapped[str] = mapped_column(String(256), nullable=False)
    annotation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    annotation_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["assembly_id", "release_id"],
            ["assemblies.id", "assemblies.release_id"],
            name="fk_local_preview_site_assembly_release",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "dataset_key",
            "source_site_key",
            name="uq_local_preview_site_dataset_source_key",
        ),
        CheckConstraint("position >= 1", name="ck_local_preview_site_position_positive"),
        CheckConstraint(
            "confidence IN ('H', 'M', 'L')",
            name="ck_local_preview_site_confidence",
        ),
        Index(
            "ix_local_preview_sites_region",
            "dataset_key",
            "assembly_id",
            "chromosome_id",
            "position",
        ),
        Index(
            "ix_local_preview_sites_gene",
            "dataset_key",
            "assembly_id",
            "gene_pk",
        ),
    )


__all__ = ["LocalTestMutationSite"]

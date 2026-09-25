"""Add immutable assembly/release-scoped GO and KEGG annotation imports."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_assemblies_id_release",
        "assemblies",
        ["id", "release_id"],
    )

    op.create_table(
        "gene_annotation_sets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("ontology", sa.String(length=8), nullable=False),
        sa.Column("source_name", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("importer_version", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ontology IN ('go', 'kegg')", name="ck_gene_annotation_sets_ontology"
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_gene_annotation_sets_sha256",
        ),
        sa.CheckConstraint("row_count > 0", name="ck_gene_annotation_sets_row_count"),
        sa.ForeignKeyConstraint(
            ["assembly_id", "release_id"],
            ["assemblies.id", "assemblies.release_id"],
            name="fk_gene_annotation_sets_assembly_release",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assembly_id",
            "release_id",
            "ontology",
            name="uq_gene_annotation_sets_scope",
        ),
        sa.UniqueConstraint(
            "id",
            "assembly_id",
            "release_id",
            "ontology",
            name="uq_gene_annotation_sets_identity_scope",
        ),
    )
    op.create_index(
        "ix_gene_annotation_sets_release_assembly_ontology",
        "gene_annotation_sets",
        ["release_id", "assembly_id", "ontology"],
    )

    op.create_table(
        "gene_annotations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("annotation_set_id", sa.Integer(), nullable=False),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("ontology", sa.String(length=8), nullable=False),
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column("term_id", sa.String(length=128), nullable=False),
        sa.Column("term_name", sa.String(length=512), nullable=False),
        sa.Column(
            "evidence_code", sa.String(length=32), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("reference", sa.String(length=512), server_default=sa.text("''"), nullable=False),
        sa.Column("qualifier", sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.CheckConstraint("ontology IN ('go', 'kegg')", name="ck_gene_annotations_ontology"),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["assembly_id", "gene_id"],
            ["genes.assembly_id", "genes.accession"],
            name="fk_gene_annotations_gene_assembly",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "annotation_set_id",
            "gene_id",
            "term_id",
            "evidence_code",
            "reference",
            "qualifier",
            name="uq_gene_annotations_evidence",
        ),
    )
    op.create_index(
        "ix_gene_annotations_release_assembly_ontology",
        "gene_annotations",
        ["release_id", "assembly_id", "ontology"],
    )
    op.create_index(
        "ix_gene_annotations_scope_term",
        "gene_annotations",
        ["release_id", "assembly_id", "ontology", "term_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gene_annotations_scope_term", table_name="gene_annotations")
    op.drop_index(
        "ix_gene_annotations_release_assembly_ontology", table_name="gene_annotations"
    )
    op.drop_table("gene_annotations")
    op.drop_index(
        "ix_gene_annotation_sets_release_assembly_ontology",
        table_name="gene_annotation_sets",
    )
    op.drop_table("gene_annotation_sets")
    op.drop_constraint(
        "uq_assemblies_id_release", "assemblies", type_="unique"
    )

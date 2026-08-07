"""Add expression, homolog, import-task and gene-data-cache models.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create expression, homolog, import-task and gene-data-cache tables."""
    # ── Enums ─────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE import_task_type_enum AS ENUM "
        "('vcf', 'gff3', 'fasta', 'blast_db', 'seed_data', "
        "'expression_csv', 'homolog_csv')"
    )
    op.execute(
        "CREATE TYPE import_task_status_enum AS ENUM "
        "('queued', 'running', 'completed', 'failed')"
    )
    op.execute(
        "CREATE TYPE expression_tissue_enum AS ENUM "
        "('leaf', 'root', 'seed', 'nodule', 'flower', 'pod', "
        "'stem', 'cotyledon', 'shoot_apex')"
    )
    op.execute(
        "CREATE TYPE expression_treatment_enum AS ENUM "
        "('control', 'drought', 'salt', 'cold', 'heat', "
        "'flooding', 'pathogen', 'nutrient_deficiency')"
    )
    op.execute(
        "CREATE TYPE homolog_type_enum AS ENUM ('ortholog', 'paralog')"
    )

    # ── Import Tasks ──────────────────────────────────────────────────────
    op.create_table(
        "import_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column(
            "type",
            sa.Enum(name="import_task_type_enum"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(name="import_task_status_enum"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "total_records", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "processed_records", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "celery_task_id", sa.String(length=36), nullable=True
        ),
        sa.Column("submitted_by", sa.String(length=64), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_tasks")),
    )

    # ── Expression Libraries ──────────────────────────────────────────────
    op.create_table(
        "expression_libraries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sample_id", sa.String(length=128), nullable=False),
        sa.Column("library_name", sa.String(length=256), nullable=False),
        sa.Column(
            "tissue",
            sa.Enum(name="expression_tissue_enum"),
            nullable=False,
        ),
        sa.Column(
            "treatment",
            sa.Enum(name="expression_treatment_enum"),
            nullable=False,
        ),
        sa.Column(
            "developmental_stage", sa.String(length=32), nullable=True
        ),
        sa.Column("study_ref", sa.String(length=256), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("assembly_id", sa.Integer(), nullable=False),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assembly_id"],
            ["assemblies.id"],
            name=op.f("fk_expression_libraries_assembly_id_assemblies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expression_libraries")),
    )
    op.create_index(
        "ix_expr_lib_assembly",
        "expression_libraries",
        ["assembly_id"],
    )
    op.create_index(
        "ix_expr_lib_tissue",
        "expression_libraries",
        ["tissue"],
    )
    op.create_index(
        "ix_expr_lib_treatment",
        "expression_libraries",
        ["treatment"],
    )

    # ── Expression Data ───────────────────────────────────────────────────
    op.create_table(
        "expression_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("fpkm", sa.Float(), nullable=True),
        sa.Column("tpm", sa.Float(), nullable=True),
        sa.Column("raw_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["gene_id"],
            ["genes.id"],
            name=op.f("fk_expression_data_gene_id_genes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["expression_libraries.id"],
            name=op.f("fk_expression_data_library_id_expression_libraries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expression_data")),
        sa.UniqueConstraint(
            "gene_id",
            "library_id",
            name="uq_expression_gene_library",
        ),
    )
    op.create_index(
        "ix_expr_data_gene",
        "expression_data",
        ["gene_id"],
    )
    op.create_index(
        "ix_expr_data_library",
        "expression_data",
        ["library_id"],
    )
    op.create_index(
        "ix_expr_data_fpkm",
        "expression_data",
        ["fpkm"],
    )

    # ── Gene Homologs ─────────────────────────────────────────────────────
    op.create_table(
        "gene_homologs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column("homolog_species", sa.String(length=128), nullable=False),
        sa.Column("homolog_gene_id", sa.String(length=64), nullable=False),
        sa.Column(
            "homolog_type",
            sa.Enum(name="homolog_type_enum"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["gene_id"],
            ["genes.id"],
            name=op.f("fk_gene_homologs_gene_id_genes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gene_homologs")),
        sa.UniqueConstraint(
            "gene_id",
            "homolog_species",
            "homolog_gene_id",
            "homolog_type",
            name="uq_gene_homolog",
        ),
    )
    op.create_index(
        "ix_homolog_gene",
        "gene_homologs",
        ["gene_id"],
    )
    op.create_index(
        "ix_homolog_species",
        "gene_homologs",
        ["homolog_species"],
    )

    # ── Gene Data Cache ───────────────────────────────────────────────────
    op.create_table(
        "gene_data_cache",
        sa.Column("gene_id", sa.String(length=64), nullable=False),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["gene_id"],
            ["genes.id"],
            name=op.f("fk_gene_data_cache_gene_id_genes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "gene_id", name=op.f("pk_gene_data_cache")
        ),
    )


def downgrade() -> None:
    """Drop tables and enums created in upgrade."""
    op.drop_table("gene_data_cache")
    op.drop_table("gene_homologs")
    op.drop_table("expression_data")
    op.drop_table("expression_libraries")
    op.drop_table("import_tasks")

    op.execute("DROP TYPE IF EXISTS homolog_type_enum")
    op.execute("DROP TYPE IF EXISTS expression_treatment_enum")
    op.execute("DROP TYPE IF EXISTS expression_tissue_enum")
    op.execute("DROP TYPE IF EXISTS import_task_status_enum")
    op.execute("DROP TYPE IF EXISTS import_task_type_enum")

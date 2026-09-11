"""Add gene_crosswalks: explicit, provenance-bearing cross-version mapping.

Cross-assembly gene equivalence (e.g. v4↔v5) may only be expressed by
rows in this table; it must never be inferred from string similarity or
coordinate proximity. One row per (source, target) pair and relation
type; one-to-many / many-to-one relations are multiple rows.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gene_crosswalks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_gene_id", sa.BigInteger(), nullable=False),
        sa.Column("target_gene_id", sa.BigInteger(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("provenance_source", sa.String(length=256), nullable=False),
        sa.Column("provenance_evidence", postgresql.JSONB(), nullable=True),
        sa.Column("release_id", sa.Integer(), nullable=True),
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
            ["source_gene_id"], ["genes.gene_pk"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_gene_id"], ["genes.gene_pk"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["release_id"], ["releases.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "source_gene_id",
            "target_gene_id",
            "relation_type",
            name="uq_gene_crosswalk_pair_type",
        ),
    )
    op.create_index(
        "ix_gene_crosswalk_source", "gene_crosswalks", ["source_gene_id"]
    )
    op.create_index(
        "ix_gene_crosswalk_target", "gene_crosswalks", ["target_gene_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_gene_crosswalk_target", table_name="gene_crosswalks")
    op.drop_index("ix_gene_crosswalk_source", table_name="gene_crosswalks")
    op.drop_table("gene_crosswalks")

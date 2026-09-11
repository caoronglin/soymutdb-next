"""Add releases columns required by the ORM but absent from the chain.

Runtime consumers read ``releases.assembly_id`` (search release-context),
``published_at``/``published_by`` (search ordering, publication state
machine) and ``variant_count``/``gene_count``/``mutant_line_count``
(stats). The migration chain only ever carried ``status``/``assembly``/
``manifest``/``active_at``/``rolled_back_at``/``reason``, so databases
migrated from Alembic (unlike ``create_all`` test runs) failed with
``UndefinedColumnError`` at the public search endpoint.

Pure expand step: nullable columns and zero-defaulted counters, no data
written. ``approved_by``/``notes`` complete the publication audit shape;
downgrade is fully reversible.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("releases", sa.Column("assembly_id", sa.Integer(), nullable=True))
    op.add_column(
        "releases",
        sa.Column("variant_count", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "releases",
        sa.Column("gene_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "releases",
        sa.Column(
            "mutant_line_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "releases",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "releases",
        sa.Column(
            "published_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "releases", sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("releases", sa.Column("notes", sa.Text(), nullable=True))
    # Releases scope a single assembly (H04/H05); a release row may never
    # claim two assemblies, while a release may exist without a scope yet.
    op.create_index(
        "ix_releases_assembly_id", "releases", ["assembly_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_releases_assembly_id", table_name="releases")
    for column in (
        "notes",
        "approved_by",
        "published_by",
        "published_at",
        "mutant_line_count",
        "gene_count",
        "variant_count",
        "assembly_id",
    ):
        op.drop_column("releases", column)

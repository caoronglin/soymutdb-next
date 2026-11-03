"""Extend the BLAST catalog build lifecycle with resumable, auditable states.

Additive only: the historical ``pending/ready/building/failed`` vocabulary is
retained. ``validating``/``publishing`` let a crashed index build be resumed
instead of silently leaving a half-published index. Bookkeeping columns record
the build attempt, failure reason and health-check time without exposing any
worker-local filesystem path. Downgrade refuses any row in the new states.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_blast_catalog_build_status", "blast_databases", type_="check")
    op.create_check_constraint(
        "ck_blast_catalog_build_status", "blast_databases",
        "build_status IN ('pending','building','validating','publishing','ready','failed')",
    )
    for column in (
        sa.Column("build_error", sa.Text(), nullable=True),
        sa.Column("build_attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("build_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("build_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_health_checked_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("blast_databases", column)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM blast_databases
                WHERE build_status IN ('validating','publishing','building','failed')
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade BLAST catalog with unfinished index '
                    'builds; reconcile those rows before rollback';
            END IF;
        END $$;
    """)
    for name in (
        "index_health_checked_at", "build_finished_at", "build_started_at",
        "build_attempt", "build_error",
    ):
        op.drop_column("blast_databases", name)
    op.drop_constraint("ck_blast_catalog_build_status", "blast_databases", type_="check")
    op.create_check_constraint(
        "ck_blast_catalog_build_status", "blast_databases",
        "build_status IN ('pending','ready','building','failed')",
    )

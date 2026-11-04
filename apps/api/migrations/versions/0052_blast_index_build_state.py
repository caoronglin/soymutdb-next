"""Extend the BLAST catalog build lifecycle with resumable, auditable states.

The catalog vocabulary becomes ``pending -> building -> validating ->
publishing -> published`` (any in-flight state may land on ``failed``). The
spelling is owned by ``soymutdb_jobs.blast_catalog_state.STATES``; a status the
constraint rejects would make the worker's guarded UPDATE fail at runtime, so
the three lists must stay identical.

``ready`` is kept as the *legacy* terminal spelling: catalogs built before
asynchronous indexing already carry it and discovery reads it as published.
``validating``/``publishing`` let a crashed build be resumed or failed cleanly
instead of leaving a half-published index. Bookkeeping columns record the build
attempt, the sanitized failure reason and the health-check time without
exposing any worker-local filesystem path. Downgrade refuses rows that an old
binary could not interpret.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


#: Legacy terminal spelling kept readable by the current binary.
_LEGACY_STATES = ("ready",)
#: Lifecycle order, ending in the terminal published state.
_STATES = ("pending", "building", "validating", "publishing", "published", "failed")
_CHECK = ", ".join(f"'{name}'" for name in _STATES + _LEGACY_STATES)


def upgrade() -> None:
    op.drop_constraint("ck_blast_catalog_build_status", "blast_databases", type_="check")
    op.create_check_constraint(
        "ck_blast_catalog_build_status", "blast_databases",
        f"build_status IN ({_CHECK})",
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
                WHERE build_status IN ('building','validating','publishing','failed')
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

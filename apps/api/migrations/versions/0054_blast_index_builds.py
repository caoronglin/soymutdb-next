"""Asynchronous, immutable BLAST index builds (worker-only execution).

Adds the build lifecycle record, the published-identity guard and the
permissive catalog status check. The vocabulary itself is owned by
``0052_blast_index_build_state`` (which runs first); this revision repeats the
same unrestricted list because the two were written independently, and it
records ``publishing`` so a build between the guarded swap and its terminal
write is representable.

Downgrade refuses any non-legacy state so an old binary cannot reinterpret a
published/validating NCBI index as a ready DIAMOND index.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_NEW_STATES = (
    "pending", "building", "validating", "publishing", "published", "failed", "ready",
)


def upgrade() -> None:
    op.create_table(
        "blast_index_builds",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  nullable=False),
        sa.Column("database_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(20), server_default="pending", nullable=False),
        sa.Column("source_object_key", sa.String(2048), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("db_type", sa.String(4), nullable=False),
        sa.Column("build_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("index_identity", sa.String(64), nullable=True),
        sa.Column("sequence_count", sa.BigInteger(), nullable=True),
        sa.Column("total_length", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_blast_index_builds"),
        sa.ForeignKeyConstraint(["database_id"], ["blast_databases.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            f"state IN ({', '.join(repr(name) for name in _NEW_STATES)})",
            name="ck_blast_index_build_state",
        ),
        sa.CheckConstraint("db_type IN ('nucl', 'prot')", name="ck_blast_index_build_db_type"),
        sa.CheckConstraint(
            "index_identity IS NULL OR index_identity ~ '^[a-f0-9]{64}$'",
            name="ck_blast_index_build_identity",
        ),
        sa.CheckConstraint("sequence_count >= 0", name="ck_blast_index_build_sequence_count"),
    )
    op.create_index("ix_blast_index_build_state", "blast_index_builds", ["state"])
    op.create_index("ix_blast_index_build_catalog", "blast_index_builds", ["database_id"])

    # Republish the catalog vocabulary once more, now that the lifecycle can
    # actually reach `publishing`; the constraint stays the union of both
    # revisions rather than the narrower list 0052 first installed.
    op.drop_constraint("ck_blast_catalog_build_status", "blast_databases", type_="check")
    op.create_check_constraint(
        "ck_blast_catalog_build_status", "blast_databases",
        f"build_status IN ({', '.join(repr(name) for name in _NEW_STATES)})",
    )
    op.create_check_constraint(
        "ck_blast_catalog_index_identity", "blast_databases",
        "index_version IS NULL OR index_version ~ '^[a-f0-9]{64}$'",
    )
    # A published row must be bound to one immutable identity and one checksum.
    op.create_check_constraint(
        "ck_blast_catalog_published_identity", "blast_databases",
        "build_status <> 'published' OR (index_version IS NOT NULL AND fasta_sha256 IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM blast_databases
                WHERE build_status IN (
                    'building', 'validating', 'publishing', 'published', 'failed'
                )
            ) OR EXISTS (SELECT 1 FROM blast_index_builds) THEN
                RAISE EXCEPTION 'Cannot downgrade BLAST catalog with asynchronous '
                    'index builds; reconcile these rows before rollback';
            END IF;
        END $$;
    """)
    op.drop_constraint("ck_blast_catalog_published_identity", "blast_databases", type_="check")
    op.drop_constraint("ck_blast_catalog_index_identity", "blast_databases", type_="check")
    op.drop_constraint("ck_blast_catalog_build_status", "blast_databases", type_="check")
    op.create_check_constraint(
        "ck_blast_catalog_build_status", "blast_databases",
        "build_status IN ('pending', 'ready', 'building', 'failed')",
    )
    op.drop_index("ix_blast_index_build_catalog", table_name="blast_index_builds")
    op.drop_index("ix_blast_index_build_state", table_name="blast_index_builds")
    op.drop_table("blast_index_builds")

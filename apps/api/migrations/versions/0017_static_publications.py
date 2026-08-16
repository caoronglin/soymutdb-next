"""Immutable multi-target static publications (Phase 3)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE publication_target_enum AS ENUM "
        "('local', 'github_pages', 'cloudflare_pages')"
    )
    op.execute(
        "CREATE TYPE publication_status_enum AS ENUM "
        "('requested', 'building', 'validating', 'deploying', "
        "'published', 'failed', 'rolled_back', 'superseded')"
    )

    op.create_table(
        "publication_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "target",
            postgresql.ENUM(name="publication_target_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("last_id", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publication_counters")),
        sa.UniqueConstraint("target", name="uq_publication_counters_target"),
    )

    op.create_table(
        "publication_target_leases",
        sa.Column(
            "target",
            postgresql.ENUM(name="publication_target_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "latest_publication_id",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.PrimaryKeyConstraint("target", name="pk_publication_target_leases"),
    )

    op.create_table(
        "static_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column(
            "target",
            postgresql.ENUM(name="publication_target_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="publication_status_enum", create_type=False),
            nullable=False,
            server_default="requested",
        ),
        sa.Column(
            "release_id",
            sa.Integer(),
            sa.ForeignKey("releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("page_definition_version", sa.Integer(), nullable=True),
        sa.Column("manifest_digest", sa.String(64), nullable=True),
        sa.Column("artifact_url", sa.Text(), nullable=True),
        sa.Column("remote_id", sa.Text(), nullable=True),
        sa.Column(
            "previous_publication_id",
            sa.Integer(),
            sa.ForeignKey("static_publications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column("superseded_by_publication_id", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_static_publications"),
        sa.UniqueConstraint(
            "target",
            "publication_id",
            name="uq_static_publications_target_publication_id",
        ),
    )
    op.create_index(
        "ix_static_publications_target_status",
        "static_publications",
        ["target", "status"],
    )
    op.create_index(
        "ix_static_publications_release_id",
        "static_publications",
        ["release_id"],
    )

    # Seed one counter row per target so allocation with ``FOR UPDATE`` can
    # update instead of upsert.
    op.execute(
        "INSERT INTO publication_counters (target, last_id) VALUES "
        "('local', 0), ('github_pages', 0), ('cloudflare_pages', 0)"
    )
    # Seed a lease row per target (single-row advisory lock).
    op.execute(
        "INSERT INTO publication_target_leases (target, latest_publication_id) "
        "VALUES ('local', 0), ('github_pages', 0), ('cloudflare_pages', 0)"
    )


def downgrade() -> None:
    op.drop_index("ix_static_publications_release_id", table_name="static_publications")
    op.drop_index(
        "ix_static_publications_target_status", table_name="static_publications"
    )
    op.drop_table("static_publications")
    op.drop_table("publication_target_leases")
    op.drop_table("publication_counters")
    op.execute("DROP TYPE IF EXISTS publication_status_enum")
    op.execute("DROP TYPE IF EXISTS publication_target_enum")

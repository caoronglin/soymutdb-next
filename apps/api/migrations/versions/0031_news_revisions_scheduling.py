"""Add bounded persistence foundations for news revisions and publication schedules.

This migration intentionally does not backfill revision history or schedule rows,
and it does not add operational worker/service behavior. Those remain a later slice.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS schedule_generation "
        "INTEGER NOT NULL DEFAULT 0"
    )

    op.create_table(
        "news_article_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "article_id", "version", name="uq_news_article_revisions_article_version"
        ),
    )
    op.create_index(
        "ix_news_article_revisions_article_id", "news_article_revisions", ["article_id"]
    )

    schedule_state = sa.Enum(
        "pending", "leased", "completed", "cancelled", name="news_schedule_state_enum"
    )
    # NOTE: no explicit ``schedule_state.create()`` here — ``op.create_table``
    # below already emits CREATE TYPE for the native enum (create_type=True
    # default); creating it twice in the same transaction fails on PostgreSQL.
    op.create_table(
        "news_publication_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", schedule_state, nullable=False, server_default="pending"),
        sa.Column("leased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(state = 'leased') = (leased_at IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_news_publication_schedules_leased_lease",
        ),
        sa.ForeignKeyConstraint(["article_id"], ["news_articles.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "article_id", "generation", name="uq_news_publication_schedules_article_generation"
        ),
    )
    op.create_index(
        "ix_news_publication_schedules_due",
        "news_publication_schedules",
        ["state", "scheduled_for"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM news_article_revisions)
               OR EXISTS (SELECT 1 FROM news_publication_schedules) THEN
                RAISE EXCEPTION
                    'Cannot downgrade migration 0031 while revision or schedule rows exist';
            END IF;
        END
        $$;
        """
    )
    op.drop_index("ix_news_publication_schedules_due", table_name="news_publication_schedules")
    op.drop_table("news_publication_schedules")
    op.execute("DROP TYPE IF EXISTS news_schedule_state_enum")
    op.drop_index("ix_news_article_revisions_article_id", table_name="news_article_revisions")
    op.drop_table("news_article_revisions")
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS schedule_generation")
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS lock_version")

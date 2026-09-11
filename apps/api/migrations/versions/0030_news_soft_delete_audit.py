"""Add reversible deletion fields for news lifecycle operations.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-31
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_news_articles_deleted_at"
_FOREIGN_KEY = "fk_news_articles_deleted_by_users"


def upgrade() -> None:
    # The production migration process may be restarted after a partial apply;
    # all additive DDL therefore has an idempotent guard.
    op.execute(
        "ALTER TABLE news_articles "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE news_articles "
        "ADD COLUMN IF NOT EXISTS deleted_by UUID NULL"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_news_articles_deleted_by_users'
            ) THEN
                ALTER TABLE news_articles
                ADD CONSTRAINT fk_news_articles_deleted_by_users
                FOREIGN KEY (deleted_by) REFERENCES users(id) ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
    # ``IF NOT EXISTS`` does not repair an index left INVALID by an interrupted
    # build, so surface that operational condition instead of silently accepting
    # a broken lifecycle-query index on a restart.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_index AS index_metadata
                JOIN pg_class AS index_relation
                  ON index_relation.oid = index_metadata.indexrelid
                JOIN pg_namespace AS index_schema
                  ON index_schema.oid = index_relation.relnamespace
                WHERE index_relation.relname = '{_INDEX_NAME}'
                  AND index_schema.nspname = current_schema()
                  AND NOT index_metadata.indisvalid
            ) THEN
                RAISE EXCEPTION
                    'Invalid index {_INDEX_NAME}; repair it before rerunning migration 0030';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_articles_deleted_at "
        "ON news_articles (deleted_at)"
    )


def downgrade() -> None:
    # Dropping these fields after live lifecycle transitions would reactivate
    # deleted records and strand their audit history. Operators must first
    # restore or otherwise resolve every deleted record deliberately.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM news_articles WHERE deleted_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade migration 0030 while soft-deleted news exists';
            END IF;
        END
        $$;
        """
    )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    op.execute(
        f"ALTER TABLE news_articles DROP CONSTRAINT IF EXISTS {_FOREIGN_KEY}"
    )
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE news_articles DROP COLUMN IF EXISTS deleted_at")

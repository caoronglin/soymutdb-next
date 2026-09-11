"""Persist controlled external-source provenance for CMS news articles.

Revision ID: 0029
Revises: 0028

External previews remain explicit, review-only fetches.  These nullable columns
record the source only after an editor saves a normal CMS draft.  A unique URL
index prevents a canonical WeChat/X-MOL article from being claimed twice while
keeping locally authored news unconstrained (PostgreSQL unique indexes allow
multiple NULL values).
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_news_articles_source_url"
_SOURCE_CONSTRAINT = "ck_news_articles_external_source"
_HASH_CONSTRAINT = "ck_news_articles_source_hash"

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("source_platform", "VARCHAR(16)"),
    ("source_url", "VARCHAR(2048)"),
    ("source_content_hash", "VARCHAR(64)"),
    ("source_published_at", "TIMESTAMPTZ"),
    ("source_synced_at", "TIMESTAMPTZ"),
)


def upgrade() -> None:
    for name, ddl in _COLUMNS:
        op.execute(f"ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS {name} {ddl}")

    # PostgreSQL has no ADD CONSTRAINT IF NOT EXISTS, so guard each narrow
    # invariant.  Application code performs the platform-specific URL
    # canonicalization; the database prevents incomplete or invalid state.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{_SOURCE_CONSTRAINT}'
            ) THEN
                ALTER TABLE news_articles ADD CONSTRAINT {_SOURCE_CONSTRAINT}
                    CHECK (
                        (source_platform IS NULL AND source_url IS NULL)
                        OR (
                            source_platform IN ('wechat', 'xmol')
                            AND source_url IS NOT NULL
                        )
                    );
            END IF;
        END $$
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{_HASH_CONSTRAINT}'
            ) THEN
                ALTER TABLE news_articles ADD CONSTRAINT {_HASH_CONSTRAINT}
                    CHECK (
                        source_content_hash IS NULL
                        OR source_content_hash ~ '^[a-f0-9]{{64}}$'
                    );
            END IF;
        END $$
        """
    )

    # Build outside the migration transaction so a table scan cannot block CMS
    # writes. Never drop a valid uniqueness index during an idempotent rerun:
    # doing so creates a window where duplicate source claims can be inserted.
    # An INVALID index signals an interrupted deployment and must be repaired
    # deliberately, rather than silently weakening the invariant here.
    with op.get_context().autocommit_block():
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
                        'Invalid index {_INDEX_NAME}; repair it before rerunning migration 0029';
                END IF;
            END $$
            """
        )
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
            "ON news_articles (source_url)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
    op.execute(
        f"ALTER TABLE news_articles DROP CONSTRAINT IF EXISTS {_HASH_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE news_articles DROP CONSTRAINT IF EXISTS {_SOURCE_CONSTRAINT}"
    )
    for name, _ddl in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE news_articles DROP COLUMN IF EXISTS {name}")

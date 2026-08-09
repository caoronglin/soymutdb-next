"""News operations fields (B1): category / cover_url / featured_sort /
carousel_group / carousel_sort / status / visible_from / visible_to.

Contract (see docs/design/upgrade-plan.md §三):
- ``is_published`` is KEPT and double-written together with the new
  ``status`` column (draft / published / archived).  Existing published rows
  are backfilled to ``status='published'``, everything else to ``draft``.
- Migration 0011 (after one week of observation) will switch queries to
  ``status`` and drop ``is_published``; the downgrade of THIS migration only
  rolls back to the pre-0010 shape and never drops ``is_published``.
- All statements are idempotent (``ADD COLUMN IF NOT EXISTS`` /
  ``CREATE INDEX IF NOT EXISTS``) because the historical 0001 migration and
  the ORM model have drifted (model already carries ``category``/``slug``).

New indexes:
- ``ix_news_status_window`` on (status, visible_from, visible_to) — the
  public list/detail/featured hot path.
- ``ix_news_articles_slug`` unique — matches the ORM model declaration
  (slug already unique per the pre-existing unique index; the IF NOT EXISTS
  guard makes this a no-op where it already exists).

A CHECK constraint pins ``status`` to the three allowed values.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None

#: PostgreSQL-compatible column additions (idempotent).
_NEW_COLUMNS: list[tuple[str, str]] = [
    # (name, DDL fragment after the column name)
    ("category", "VARCHAR(64)"),
    ("cover_url", "VARCHAR(1024)"),
    ("featured_sort", "INTEGER NOT NULL DEFAULT 0"),
    ("carousel_group", "VARCHAR(64)"),
    ("carousel_sort", "INTEGER NOT NULL DEFAULT 0"),
    ("status", "VARCHAR(16) NOT NULL DEFAULT 'draft'"),
    ("visible_from", "TIMESTAMPTZ"),
    ("visible_to", "TIMESTAMPTZ"),
]


def upgrade() -> None:
    """Add the news operations columns, backfill status, create indexes."""
    for name, ddl in _NEW_COLUMNS:
        op.execute(
            f"ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS {name} {ddl}"
        )

    # Double-write backfill: keep is_published in sync with status.
    op.execute(
        "UPDATE news_articles SET status = 'published' "
        "WHERE is_published = TRUE AND status = 'draft'"
    )

    # Status values are pinned by a guarded CHECK constraint (PostgreSQL has
    # no IF NOT EXISTS for constraints, so a DO block is used).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_news_articles_status'
            ) THEN
                ALTER TABLE news_articles ADD CONSTRAINT ck_news_articles_status
                    CHECK (status IN ('draft', 'published', 'archived'));
            END IF;
        END $$
        """
    )

    # Hot-path indexes (idempotent).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_news_status_window "
        "ON news_articles (status, visible_from, visible_to)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_news_articles_slug "
        "ON news_articles (slug)"
    )


def downgrade() -> None:
    """Roll back to the pre-0010 shape (never drops ``is_published``)."""
    op.execute("DROP INDEX IF EXISTS ix_news_status_window")
    op.execute(
        "ALTER TABLE news_articles DROP CONSTRAINT IF EXISTS ck_news_articles_status"
    )
    # Only columns introduced by this migration are dropped; category/slug
    # existed in the ORM model before 0010 and are left untouched, as is
    # is_published (double-write contract).
    for name, _ddl in _NEW_COLUMNS:
        if name == "category":
            continue  # pre-existing model field
        op.execute(f"ALTER TABLE news_articles DROP COLUMN IF EXISTS {name}")

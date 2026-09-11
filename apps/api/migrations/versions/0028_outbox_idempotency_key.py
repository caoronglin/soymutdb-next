"""Enforce outbox idempotency keys at the database boundary.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_INDEX_NAME = "uq_outbox_events_idempotency_key"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE outbox_events "
        "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)"
    )

    # Preserve every historical row. If legacy races produced duplicate JSON
    # keys, only the oldest row becomes the canonical keyed record; duplicate
    # audit rows remain present with a NULL column value.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                payload ->> 'idempotency_key' AS key,
                row_number() OVER (
                    PARTITION BY payload ->> 'idempotency_key'
                    ORDER BY id
                ) AS occurrence
            FROM outbox_events
            WHERE jsonb_typeof(payload -> 'idempotency_key') = 'string'
              AND length(payload ->> 'idempotency_key') BETWEEN 1 AND 255
        )
        UPDATE outbox_events AS event
        SET idempotency_key = ranked.key
        FROM ranked
        WHERE event.id = ranked.id
          AND ranked.occurrence = 1
        """
    )

    # Avoid blocking outbox producers while PostgreSQL scans existing rows.
    with op.get_context().autocommit_block():
        # A failed concurrent build leaves an INVALID index with the same name;
        # remove it so a retried migration performs a real rebuild.
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY {_INDEX_NAME} "
            "ON outbox_events (idempotency_key) "
            "WHERE idempotency_key IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
    op.execute(
        "ALTER TABLE outbox_events DROP COLUMN IF EXISTS idempotency_key"
    )

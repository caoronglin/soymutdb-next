"""Add durable fenced leases to transactional outbox claims."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def _replace_status_enum(labels: tuple[str, ...]) -> None:
    """Transactionally replace the PostgreSQL enum with *labels*."""
    rendered_labels = ", ".join(f"'{label}'" for label in labels)
    op.execute("ALTER TABLE outbox_events ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TYPE outbox_event_status_enum "
        "RENAME TO outbox_event_status_enum_previous"
    )
    op.execute(
        f"CREATE TYPE outbox_event_status_enum AS ENUM ({rendered_labels})"
    )
    op.execute(
        "ALTER TABLE outbox_events ALTER COLUMN status "
        "TYPE outbox_event_status_enum "
        "USING status::text::outbox_event_status_enum"
    )
    op.execute(
        "ALTER TABLE outbox_events ALTER COLUMN status "
        "SET DEFAULT 'pending'::outbox_event_status_enum"
    )
    op.execute("DROP TYPE outbox_event_status_enum_previous")


def upgrade() -> None:
    """Add processing state, lease metadata, fencing, and expiry lookup."""
    _replace_status_enum(("pending", "processing", "sent", "failed"))
    op.add_column(
        "outbox_events",
        sa.Column("lease_owner", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_outbox_events_processing_lease",
        "outbox_events",
        "(status = 'processing' AND lease_owner IS NOT NULL "
        "AND lease_until IS NOT NULL) OR "
        "(status <> 'processing' AND lease_owner IS NULL "
        "AND lease_until IS NULL)",
    )
    op.create_index(
        "ix_outbox_events_status_lease_until",
        "outbox_events",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    """Requeue in-flight rows, remove lease metadata, and restore the enum."""
    op.execute(
        "UPDATE outbox_events SET status = 'pending', lease_owner = NULL, "
        "lease_until = NULL WHERE status = 'processing'"
    )
    op.drop_index(
        "ix_outbox_events_status_lease_until", table_name="outbox_events"
    )
    op.drop_constraint(
        "ck_outbox_events_processing_lease",
        "outbox_events",
        type_="check",
    )
    op.drop_column("outbox_events", "lease_until")
    op.drop_column("outbox_events", "lease_owner")
    _replace_status_enum(("pending", "sent", "failed"))

"""Notifications table for the in-app notification centre (D2).

The worker writes ``notifications`` rows directly (narrow
``soymutdb_worker.repositories.NotifyStore``) when a background job
completes or fails; the API reads them back for the authenticated
notification endpoints.  ``type`` is a plain string vocabulary
(``blast_completed`` / ``blast_failed`` / ``analysis_completed`` /
``analysis_failed`` / ``gwas_completed`` / ``gwas_failed`` / ...) so new
kinds never require a schema migration; ``link`` carries the app route
opened on click (e.g. ``/blast/jobs/{job_id}``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0013"
# Chain serialization fix (D2): 0012 (seed_requests, D1) exists in the
# working tree, so 0013 (notifications) depends on it.  If the integration
# owner re-orders the chain, re-point this to the actual predecessor.
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the ``notifications`` table."""
    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=512), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index(
        "ix_notifications_user_read", "notifications", ["user_id", "read_at"]
    )


def downgrade() -> None:
    """Drop the ``notifications`` table."""
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")

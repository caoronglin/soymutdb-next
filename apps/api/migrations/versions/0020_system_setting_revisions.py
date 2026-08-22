"""Add immutable revision snapshots for typed runtime settings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Expand the schema with settings revision storage."""
    op.create_table(
        "system_setting_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("section", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rollback_from_version", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_setting_revision_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_system_setting_revisions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_setting_revisions")),
        sa.UniqueConstraint(
            "section",
            "version",
            name="uq_setting_revision_section_version",
        ),
    )
    op.create_index(
        "ix_system_setting_revisions_section",
        "system_setting_revisions",
        ["section"],
    )


def downgrade() -> None:
    """Remove settings revision storage."""
    op.drop_index(
        "ix_system_setting_revisions_section",
        table_name="system_setting_revisions",
    )
    op.drop_table("system_setting_revisions")

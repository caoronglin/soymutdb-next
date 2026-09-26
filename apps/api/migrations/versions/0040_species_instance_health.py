"""Persist bounded health summaries for registered species instances.

Health probes are operational metadata only. They never copy or expose
biological records and do not authorize remote administration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "species_instances",
        sa.Column(
            "connection_state",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "species_instances",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "species_instances",
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "species_instances",
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_species_instances_connection_state",
        "species_instances",
        "connection_state IN ('unknown', 'healthy', 'unhealthy', 'disabled', 'unconfigured')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_species_instances_connection_state",
        "species_instances",
        type_="check",
    )
    op.drop_column("species_instances", "last_error_code")
    op.drop_column("species_instances", "last_error_at")
    op.drop_column("species_instances", "last_checked_at")
    op.drop_column("species_instances", "connection_state")

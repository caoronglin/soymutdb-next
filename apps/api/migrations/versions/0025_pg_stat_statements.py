"""Enable pg_stat_statements for the weekly slow-query baseline."""
from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL must start with shared_preload_libraries=pg_stat_statements.
    # The compose/deployment configuration owns that restart-required setting.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    # Keep historical statistics intact during a code downgrade; removing the
    # extension is an operational decision and would invalidate comparisons.
    pass

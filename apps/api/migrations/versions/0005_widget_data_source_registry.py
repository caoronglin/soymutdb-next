"""Migrate widget data sources from dotted paths to registry identifiers."""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Replace the legacy SRA dotted path with its stable registry ID."""
    op.execute(
        """
        UPDATE widgets
        SET data_source = 'sra_run'
        WHERE data_source = 'app.widgets.data_sources.sra.sra_run_context'
        """
    )


def downgrade() -> None:
    """Restore the legacy value when rolling back this migration."""
    op.execute(
        """
        UPDATE widgets
        SET data_source = 'app.widgets.data_sources.sra.sra_run_context'
        WHERE data_source = 'sra_run'
        """
    )

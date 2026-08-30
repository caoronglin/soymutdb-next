"""Add optional PostgreSQL trigram indexes for global search."""
from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm is part of standard PostgreSQL contrib; IF NOT EXISTS keeps
    # deployments without the extension compatible (queries still work).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, column in (
        ("ix_genes_name_trgm", "genes", "name"),
        ("ix_mutant_lines_name_trgm", "mutant_lines", "name"),
        ("ix_publications_title_trgm", "publications", "title"),
    ):
        op.execute(f"CREATE INDEX {name} ON {table} USING gin ({column} gin_trgm_ops)")


def downgrade() -> None:
    for name in ("ix_publications_title_trgm", "ix_mutant_lines_name_trgm", "ix_genes_name_trgm"):
        op.execute(f"DROP INDEX IF EXISTS {name}")

"""Expand global-search trigram indexes without blocking writes."""
from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_genes_description_trgm", "genes", "description"),
    ("ix_mutant_lines_cultivar_trgm", "mutant_lines", "cultivar"),
    ("ix_mutant_lines_mutagen_trgm", "mutant_lines", "mutagen"),
    ("ix_mutant_lines_description_trgm", "mutant_lines", "description"),
    ("ix_publications_authors_trgm", "publications", "authors"),
    ("ix_publications_abstract_trgm", "publications", "abstract"),
)


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside Alembic's transaction.
    # The autocommit block avoids blocking concurrent production writes.
    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for name, table, column in _INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} USING gin ({column} gin_trgm_ops)"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _table, _column in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")

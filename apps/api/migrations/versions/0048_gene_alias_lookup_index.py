"""Index the curated gene alias lookup used by the second gene-search arm.

Global search widens an identifier-shaped query with curated alias equality
(``lower(gene_aliases.alias) = lower(query)``). That comparison is now a
standalone ``UNION`` arm rather than a term inside the text arm's ``OR`` list,
which is what lets the text arm keep the migration 0046 trigram indexes — see
``services/search_service._gene_match_query``.

Giving the alias arm its own arm made its cost visible: it had no usable index.
``ix_gene_alias_alias`` is a plain btree over ``alias`` and cannot serve a
``lower(...)`` comparison, so PostgreSQL scanned the whole alias table once per
search. This index is that comparison's only access path.

Built ``CONCURRENTLY`` inside an ``autocommit_block`` (the same shape as 0027
and 0046) so a large ``gene_aliases`` table does not take a write lock. It is a
lookup accelerator only: it changes nothing about which rows a query may return.
"""

from __future__ import annotations

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_gene_aliases_alias_lower"


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside Alembic's transaction.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            "ON gene_aliases (lower(alias))"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")

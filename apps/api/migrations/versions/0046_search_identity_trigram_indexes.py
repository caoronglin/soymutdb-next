"""Add trigram indexes for the two identifier columns global search matches.

``0027`` gave the fuzzy-search columns trigram indexes (``genes.description``,
``mutant_lines.cultivar`` / ``mutagen`` / ``description``, publication author
and abstract). The two identifier columns a search box is actually typed into
were never covered:

* ``genes.accession`` — the assembly-scoped gene identifier a user types.
* ``mutant_lines.public_id`` — the stable public identifier used in external
  links and lookups.

Both are plain ``VARCHAR`` columns, so ``gin_trgm_ops`` applies directly. This
index is a lookup accelerator only: it changes nothing about which rows a query
may return, so release visibility, internal/external identifier rules and
assembly scoping still live entirely in the query predicates.

Both indexes are built ``CONCURRENTLY`` inside an ``autocommit_block`` (the same
shape as 0027) so a large ``genes`` / ``mutant_lines`` table does not take a
write lock while the migration runs.
"""

from __future__ import annotations

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


_INDEXES = (
    ("ix_genes_accession_trgm", "genes", "accession"),
    ("ix_mutant_lines_public_id_trgm", "mutant_lines", "public_id"),
)


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside Alembic's transaction.
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

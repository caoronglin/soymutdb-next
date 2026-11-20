"""Restore the gene_id constraints and indexes dropped by 0033.

Migration 0033 swapped the gene primary key by running ``ALTER TABLE <child>
DROP COLUMN gene_id`` on every child table. PostgreSQL cascades that drop into
every object that references the column, so the natural-key unique constraints
and lookup indexes created in 0001/0003 silently disappeared. The ORM still
declares them, and writers that rely on them fail at runtime:

* ``ON CONFLICT ON CONSTRAINT uq_gene_homolog`` (CSV homolog upsert) and
* ``ON CONFLICT ON CONSTRAINT uq_expression_gene_library`` (expression upsert)

both raised ``constraint ... does not exist``. 0033 never recreated the
objects, and ``ix_transcript_gene`` / ``ix_vs_gene`` lookups lost their access
path the same way.

This migration puts them back. Before adding each unique constraint it removes
existing duplicate rows, keeping the newest (highest ``id``) per key, because
the pre-0033 uniqueness guarantee no longer holds for data written since.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

# (table, constraint name, key columns)
_UNIQUE_KEYS = [
    ("gene_aliases", "uq_gene_alias", ("gene_id", "alias")),
    ("expression_data", "uq_expression_gene_library", ("gene_id", "library_id")),
    (
        "gene_homologs",
        "uq_gene_homolog",
        ("gene_id", "homolog_species", "homolog_gene_id", "homolog_type"),
    ),
]

# (table, index name, indexed columns)
_INDEXES = [
    ("transcripts", "ix_transcript_gene", ("gene_id",)),
    ("variant_summaries", "ix_vs_gene", ("gene_id",)),
    ("expression_data", "ix_expr_data_gene", ("gene_id",)),
    ("gene_homologs", "ix_homolog_gene", ("gene_id",)),
]


def upgrade() -> None:
    # ``--sql`` mode has no live connection to inspect; emit the DDL as-is.
    offline = op.get_context().as_sql
    inspector = None if offline else sa.inspect(op.get_bind())

    for table, constraint_name, columns in _UNIQUE_KEYS:
        existing = (
            set()
            if inspector is None
            else {c["name"] for c in inspector.get_unique_constraints(table)}
        )
        key_match = " AND ".join(f"a.{column} = b.{column}" for column in columns)
        op.execute(f"DELETE FROM {table} a USING {table} b WHERE a.id < b.id AND {key_match}")
        if constraint_name not in existing:
            op.create_unique_constraint(constraint_name, table, list(columns))

    for table, index_name, columns in _INDEXES:
        existing = (
            set()
            if inspector is None
            else {index["name"] for index in inspector.get_indexes(table)}
        )
        if index_name not in existing:
            op.create_index(index_name, table, list(columns))


def downgrade() -> None:
    for table, index_name, _columns in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    for table, constraint_name, _columns in reversed(_UNIQUE_KEYS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}")

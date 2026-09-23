"""Shared helpers for worker PostgreSQL integration tests."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Identity sequences the worker integration tests insert through. API tests
# seed rows with explicit ids, which does not advance the sequence; without
# realignment the next ``nextval`` can return an existing id and the insert
# dies with `duplicate key value violates unique constraint "pk_releases"`.
SEQUENCE_TABLES = ("releases", "assemblies")


def align_identity_sequences(engine: Engine, tables: tuple[str, ...] = SEQUENCE_TABLES) -> None:
    """Advance each table's identity sequence past the largest existing id.

    ``setval(sequence, max(id))`` makes the next ``nextval`` return max(id)+1.
    Table names are code constants (never upload-derived), so interpolating the
    identifier is safe; the sequence name is resolved by PostgreSQL itself.
    """
    with engine.begin() as connection:
        for table in tables:
            connection.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence(:table_name, 'id'), "
                    f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1)"
                    ")"
                ),
                {"table_name": table},
            )

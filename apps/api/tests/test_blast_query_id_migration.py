"""Real PostgreSQL HSP query ID migration preserves legacy unknown values."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/0051_blast_hit_query_id.py"


def run_migration(connection, method):
    spec = importlib.util.spec_from_file_location("blast_query_id_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, method)()


async def test_query_id_upgrade_downgrade_preserves_legacy_hsps(db_connection):
    schema = f"blast_query_id_{uuid.uuid4().hex}"
    await db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    await db_connection.execute(text(
        "CREATE TABLE blast_hits(id INTEGER PRIMARY KEY,subject_id VARCHAR(256) NOT NULL)"
    ))
    await db_connection.execute(text("INSERT INTO blast_hits VALUES(1,'old_target')"))
    await db_connection.run_sync(run_migration, "upgrade")
    assert (await db_connection.execute(text("SELECT * FROM blast_hits"))).one() == (
        1, "old_target", None,
    )
    await db_connection.execute(text("INSERT INTO blast_hits VALUES(2,'new_target','second')"))
    await db_connection.run_sync(run_migration, "downgrade")
    assert (await db_connection.execute(text("SELECT * FROM blast_hits ORDER BY id"))).all() == [
        (1, "old_target"), (2, "new_target"),
    ]
    await db_connection.run_sync(run_migration, "upgrade")
    restored = await db_connection.execute(text("SELECT query_id FROM blast_hits"))
    assert restored.scalars().all() == [None, None]

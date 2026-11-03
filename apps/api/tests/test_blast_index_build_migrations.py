"""PostgreSQL roundtrip for the additive index-build and hit-resolution columns.

These exercise real DDL (upgrade/downgrade) against the disposable PG fixture;
they are skipped automatically where no test database is configured.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

BUILD_STATE = Path(__file__).resolve().parents[1] / (
    "migrations/versions/0052_blast_index_build_state.py"
)
HIT_RESOLUTION = Path(__file__).resolve().parents[1] / (
    "migrations/versions/0053_blast_hit_genome_resolution.py"
)


def _run(path: Path, name: str, connection, method: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, method)()


async def _schema(db_connection) -> str:
    schema = f"blast_build_{uuid.uuid4().hex}"
    await db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    await db_connection.execute(text("""
        CREATE TABLE blast_databases (
            id INTEGER PRIMARY KEY, build_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        )
    """))
    await db_connection.execute(text("""
        CREATE TABLE blast_hits (id INTEGER PRIMARY KEY, subject_id VARCHAR(256) NOT NULL)
    """))
    await db_connection.execute(text(
        "ALTER TABLE blast_databases ADD CONSTRAINT ck_blast_catalog_build_status "
        "CHECK (build_status IN ('pending','ready','building','failed'))"
    ))
    await db_connection.execute(text(
        "INSERT INTO blast_databases(id, build_status) VALUES (1,'ready'),(2,'pending')"
    ))
    await db_connection.execute(text("INSERT INTO blast_hits VALUES(1,'old_target')"))
    return schema


async def test_build_state_and_hit_resolution_upgrade_downgrade(db_connection):
    schema = await _schema(db_connection)
    await db_connection.run_sync(
        lambda c: _run(BUILD_STATE, "blast_build_state_migration", c, "upgrade")
    )
    await db_connection.run_sync(
        lambda c: _run(HIT_RESOLUTION, "blast_hit_resolution_migration", c, "upgrade")
    )
    columns = (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = 'blast_databases'"
    ), {"schema": schema})).scalars().all()
    assert {"build_error", "build_attempt", "build_started_at", "build_finished_at",
            "index_health_checked_at"} <= set(columns)
    assert "genome_resolution" in (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = 'blast_hits'"
    ), {"schema": schema})).scalars().all()
    # The widened vocabulary accepts every state the worker writes, and it
    # still accepts the legacy terminal spelling of pre-existing rows.
    for status in ("building", "validating", "publishing", "published", "failed",
                   "ready", "pending"):
        await db_connection.execute(text(
            "UPDATE blast_databases SET build_status=:status WHERE id=2"
        ), {"status": status})
    with pytest.raises(DBAPIError, match="ck_blast_catalog_build_status"):
        async with db_connection.begin_nested():
            await db_connection.execute(text(
                "UPDATE blast_databases SET build_status='released' WHERE id=2"
            ))
    assert (await db_connection.execute(text(
        "SELECT genome_resolution FROM blast_hits"
    ))).scalar_one() is None
    # An in-flight build survives the upgrade but blocks a rollback: an old
    # binary would read a half-built index as executable.
    await db_connection.execute(text(
        "UPDATE blast_databases SET build_status='publishing' WHERE id=2"
    ))

    # Downgrade refuses an unfinished build rather than letting an old binary
    # reinterpret an in-flight index as ready.
    with pytest.raises(DBAPIError, match="unfinished index builds"):
        async with db_connection.begin_nested():
            await db_connection.run_sync(
                lambda c: _run(BUILD_STATE, "blast_build_state_migration", c, "downgrade")
            )
    await db_connection.execute(text(
        "UPDATE blast_databases SET build_status='ready' WHERE id=2"
    ))
    await db_connection.run_sync(
        lambda c: _run(HIT_RESOLUTION, "blast_hit_resolution_migration", c, "downgrade")
    )
    await db_connection.run_sync(
        lambda c: _run(BUILD_STATE, "blast_build_state_migration", c, "downgrade")
    )
    assert "genome_resolution" not in (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = 'blast_hits'"
    ), {"schema": schema})).scalars().all()
    assert "build_error" not in (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = :schema AND table_name = 'blast_databases'"
    ), {"schema": schema})).scalars().all()
    assert (await db_connection.execute(text(
        "SELECT build_status FROM blast_databases ORDER BY id"
    ))).scalars().all() == ["ready", "ready"]

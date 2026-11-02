"""Contracts for migration 0048 - the curated gene-alias lookup index.

Global search widens an identifier-shaped query with curated alias equality
(``lower(gene_aliases.alias) = lower(query)``). That comparison lives in its own
``UNION`` arm so the text arm can keep the migration 0046 trigram indexes; see
``tests/test_search_gene_index_usage.py`` for the measured reason. Giving the
alias arm its own arm made its cost visible: ``ix_gene_alias_alias`` is a plain
btree over ``alias`` and cannot serve a ``lower(...)`` comparison, so without
this index PostgreSQL scanned the whole alias table once per search.

Mirrors ``test_search_identity_indexes.py`` (migration 0046): an offline
``alembic --sql`` layer that needs no database, and a real PostgreSQL layer that
runs inside a private schema this test creates and drops itself. No planner
claim is asserted here; this file asserts that the index is created, valid,
idempotent and reversible, and that nothing else is touched.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0048_gene_alias_lookup_index.py"

INDEX_NAME = "ix_gene_aliases_alias_lower"
TABLE = "gene_aliases"


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0048", REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _alembic_environment() -> dict:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(workspace_root / "packages/jobs-py/src"),
            str(API_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment["SOYMUTDB_DATABASE_URL"] = (
        "postgresql+asyncpg://offline:offline@localhost/offline"
    )
    return environment


def _run_alembic(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=API_ROOT,
        env=_alembic_environment(),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _offline_sql(command: str, revision_range: str) -> str:
    result = _run_alembic(command, revision_range, "--sql")
    assert result.returncode == 0, result.stderr
    return result.stdout


# --------------------------------------------------------------------------- #
# Offline layer
# --------------------------------------------------------------------------- #


def test_0048_follows_the_native_analytics_revision() -> None:
    assert REVISION.is_file()
    revision = _load_revision()
    assert revision.revision == "0048"
    assert revision.down_revision == "0047"
    assert revision.INDEX_NAME == INDEX_NAME


def test_0048_upgrade_creates_the_functional_index_concurrently() -> None:
    sql = _offline_sql("upgrade", "0047:0048")
    assert (
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
        "ON gene_aliases (lower(alias))"
    ) in sql
    assert "DROP INDEX" not in sql


def test_0048_downgrade_drops_only_the_index_concurrently() -> None:
    sql = _offline_sql("downgrade", "0048:0047")
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}" in sql
    assert "CREATE INDEX" not in sql
    assert "DROP COLUMN" not in sql
    assert "DROP TABLE" not in sql


# --------------------------------------------------------------------------- #
# Real PostgreSQL layer
# --------------------------------------------------------------------------- #


def _database_url() -> str | None:
    return os.environ.get(
        "SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL"
    ) or os.environ.get("SOYMUTDB_TEST_DATABASE_URL")


def _qualified(schema: str, name: str) -> str:
    return '"' + schema + '"."' + name + '"'


def qualified_schema(schema: str) -> str:
    return '"' + schema + '"'


def _run_migration(sync_connection, function_name: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    revision = _load_revision()
    migration_context = MigrationContext.configure(sync_connection)
    with Operations.context(migration_context):
        # alembic's autocommit_block (used for CREATE/DROP INDEX CONCURRENTLY)
        # requires an open migration transaction, exactly like migrations/env.py.
        with migration_context.begin_transaction():
            getattr(revision, function_name)()


async def _index_state(connection, schema: str) -> dict:
    rows = await connection.execute(
        text(
            "SELECT c.relname, i.indisvalid, i.indisready, "
            "pg_get_indexdef(i.indexrelid) AS definition "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE n.nspname = :schema AND c.relname = :name"
        ),
        {"schema": schema, "name": INDEX_NAME},
    )
    return {row[0]: (bool(row[1] and row[2]), row[3]) for row in rows}


@pytest.fixture(scope="module")
def migrated_schema() -> dict:
    """Run 0048 upgrade/downgrade inside a private schema on a real server."""
    url = _database_url()
    if not url:
        pytest.skip(
            "no PostgreSQL URL: set SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL "
            "(or SOYMUTDB_TEST_DATABASE_URL) to run the real-database layer"
        )
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip(
            "PostgreSQL URL must use the postgresql+asyncpg:// scheme, got "
            + url.split("://", 1)[0]
            + "://"
        )

    schema = "gene_alias_lookup_" + uuid.uuid4().hex[:12]
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema + ",public"}}
    )

    async def run_step(step: str) -> dict:
        # A fresh connection per step: alembic's autocommit_block switches the
        # isolation level and leaves a transaction behind on the connection it
        # used, which would make the next MigrationContext believe it is inside
        # an external transaction and refuse to open its own.
        connection = await engine.connect()
        try:
            await connection.run_sync(_run_migration, step)
            await connection.commit()
            return await _index_state(connection, schema)
        finally:
            await connection.close()

    async def exercise() -> dict:
        outcome: dict = {}
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text("CREATE SCHEMA " + qualified_schema(schema))
                )
                await connection.commit()
                await connection.execute(
                    text(
                        "CREATE TABLE "
                        + _qualified(schema, TABLE)
                        + " (id INTEGER PRIMARY KEY, alias VARCHAR(256) NOT NULL, "
                        "gene_id BIGINT NOT NULL)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO "
                        + _qualified(schema, TABLE)
                        + " (id, alias, gene_id) VALUES (1, 'LEGACY_GLY01G000100', 7)"
                    )
                )
                await connection.commit()
                outcome["alias_rows"] = (
                    await connection.execute(
                        text("SELECT count(*) FROM " + _qualified(schema, TABLE))
                    )
                ).scalar_one()

            outcome["after_upgrade"] = await run_step("upgrade")
            outcome["after_rerun"] = await run_step("upgrade")
            outcome["after_downgrade"] = await run_step("downgrade")
        finally:
            async with engine.connect() as connection:
                await connection.rollback()
                await connection.execute(
                    text("DROP SCHEMA IF EXISTS " + qualified_schema(schema) + " CASCADE")
                )
                await connection.commit()
            await engine.dispose()
        return outcome

    return asyncio.run(exercise())


def test_0048_upgrade_creates_a_valid_functional_index(migrated_schema: dict) -> None:
    state = migrated_schema["after_upgrade"]
    assert INDEX_NAME in state, f"{INDEX_NAME} missing after upgrade: {state}"
    valid, definition = state[INDEX_NAME]
    assert valid is True, f"{INDEX_NAME} is not valid and ready: {state}"
    assert "lower" in definition.lower(), definition


def test_0048_upgrade_is_idempotent_on_real_postgres(migrated_schema: dict) -> None:
    assert migrated_schema["after_rerun"] == migrated_schema["after_upgrade"]


def test_0048_downgrade_removes_the_index_only(migrated_schema: dict) -> None:
    assert migrated_schema["after_downgrade"] == {}
    assert migrated_schema["alias_rows"] == 1

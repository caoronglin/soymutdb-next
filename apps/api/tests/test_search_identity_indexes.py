"""Contracts for migration 0046 - trigram indexes on the search identifiers.

Two layers are covered:

* Offline (alembic --sql): the emitted statements and the revision chain, which
  need no database at all.
* Real PostgreSQL: the actual CREATE INDEX CONCURRENTLY / DROP INDEX
  CONCURRENTLY execution, using a dedicated schema this test creates and drops
  itself. It never runs metadata.create_all / drop_all and never touches the
  public schema or any other schema, so it cannot collide with another test that
  is using the same database.

The PostgreSQL layer is skipped (with the reason reported by pytest) when no
database URL is provided - it is never reported as a pass. No planner or EXPLAIN
performance claim is asserted here; these tests assert only that the indexes
exist, are valid, and disappear on downgrade.
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
REVISION = API_ROOT / "migrations" / "versions" / "0046_search_identity_trigram_indexes.py"

INDEXES = (
    ("ix_genes_accession_trgm", "genes", "accession"),
    ("ix_mutant_lines_public_id_trgm", "mutant_lines", "public_id"),
)


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0046", REVISION)
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


def test_0046_revision_precedes_native_analytics_and_the_current_head() -> None:
    """0046 stays below 0047 and below whatever is currently the head.

    The chain is walked instead of pinning the head's number, so adding a later
    revision does not make this assertion stale while still failing if 0046 were
    ever re-parented above the native analytics revision or orphaned.
    """
    assert REVISION.is_file()
    revision = _load_revision()
    assert revision.revision == "0046"
    assert revision.down_revision == "0045"
    assert tuple(revision._INDEXES) == INDEXES

    heads = _run_alembic("heads")
    assert heads.returncode == 0, heads.stderr
    reported = [line.strip() for line in heads.stdout.splitlines() if line.strip()]
    assert len(reported) == 1, f"the migration chain must stay single-headed: {reported}"
    head = reported[0].split(" ", 1)[0]
    assert head != "0046", reported

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    ancestors = {revision.revision}
    for entry in scripts.walk_revisions():
        ancestors.add(entry.revision)
        if entry.revision == "0047":
            break
    assert "0047" in ancestors, sorted(ancestors)


def test_0046_upgrade_creates_both_trigram_indexes_concurrently() -> None:
    sql = _offline_sql("upgrade", "0045:0046")

    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in sql
    assert (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_genes_accession_trgm "
        "ON genes USING gin (accession gin_trgm_ops)"
    ) in sql
    assert (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_mutant_lines_public_id_trgm "
        "ON mutant_lines USING gin (public_id gin_trgm_ops)"
    ) in sql
    assert "DROP INDEX" not in sql


def test_0046_downgrade_drops_both_indexes_concurrently_in_reverse_order() -> None:
    sql = _offline_sql("downgrade", "0046:0045")

    public_id_drop = "DROP INDEX CONCURRENTLY IF EXISTS ix_mutant_lines_public_id_trgm"
    accession_drop = "DROP INDEX CONCURRENTLY IF EXISTS ix_genes_accession_trgm"
    assert public_id_drop in sql
    assert accession_drop in sql
    assert sql.index(public_id_drop) < sql.index(accession_drop)
    assert "CREATE INDEX CONCURRENTLY" not in sql
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
            "SELECT c.relname, i.indisvalid, i.indisready "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE n.nspname = :schema AND c.relname = ANY(:names)"
        ),
        {"schema": schema, "names": [name for name, _table, _column in INDEXES]},
    )
    return {row[0]: bool(row[1] and row[2]) for row in rows}


@pytest.fixture(scope="module")
def migrated_schema() -> dict:
    """Run 0046 upgrade/downgrade inside a private schema on a real server.

    The schema is created and dropped here; nothing global is touched, so this
    can share a database with other suites as long as they do not share the
    randomly named schema.
    """
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

    schema = "search_identity_trgm_" + uuid.uuid4().hex[:12]
    # server_settings puts the private schema first on every pooled connection,
    # so alembic's unqualified CREATE INDEX ... ON genes resolves to our own
    # tables and each migration step can run on a fresh connection.
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
                # Install pg_trgm in public (not in the private schema) so the
                # operator class resolves through the search path and the
                # private schema stays extension-free, which is what lets the
                # teardown below drop it.
                await connection.execute(
                    text("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public")
                )
                resolved = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_opclass "
                            "WHERE opcname = 'gin_trgm_ops'"
                        )
                    )
                ).scalar()
                assert resolved, (
                    "gin_trgm_ops is not installed in this database; a leaked "
                    "search_identity_trgm_* schema is holding pg_trgm. Drop "
                    "those schemas (and the extension) before running this test."
                )
                await connection.execute(
                    text(
                        "CREATE TABLE "
                        + _qualified(schema, "genes")
                        + " (accession VARCHAR(255) NOT NULL)"
                    )
                )
                await connection.execute(
                    text(
                        "CREATE TABLE "
                        + _qualified(schema, "mutant_lines")
                        + " (public_id VARCHAR(32))"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO "
                        + _qualified(schema, "genes")
                        + " (accession) VALUES ('Gly01g000100')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO "
                        + _qualified(schema, "mutant_lines")
                        + " (public_id) VALUES ('MUT00000001')"
                    )
                )
                outcome["gene_rows"] = (
                    await connection.execute(
                        text("SELECT count(*) FROM " + _qualified(schema, "genes"))
                    )
                ).scalar()
                await connection.commit()

            outcome["after_upgrade"] = await run_step("upgrade")
            # A rerun must be a no-op rather than an error.
            outcome["after_rerun"] = await run_step("upgrade")
            outcome["after_downgrade"] = await run_step("downgrade")
        finally:
            # Always drop the private schema, including after a failure: the
            # migration installs pg_trgm into the first schema on the search
            # path, so a leaked schema would strand the operator class and
            # break the next run.
            async with engine.connect() as connection:
                await connection.rollback()
                await connection.execute(
                    text(
                        "DROP SCHEMA IF EXISTS "
                        + qualified_schema(schema)
                        + " CASCADE"
                    )
                )
                await connection.commit()
            await engine.dispose()
        return outcome

    return asyncio.run(exercise())


def test_0046_upgrade_creates_valid_indexes_on_real_postgres(migrated_schema: dict) -> None:
    state = migrated_schema["after_upgrade"]
    assert state, "no index rows found in the isolated schema"
    for name, _table, _column in INDEXES:
        assert state.get(name) is True, f"{name} missing or invalid after upgrade: {state}"


def test_0046_upgrade_is_idempotent_on_real_postgres(migrated_schema: dict) -> None:
    assert migrated_schema["after_rerun"] == migrated_schema["after_upgrade"]


def test_0046_downgrade_removes_the_indexes_only(migrated_schema: dict) -> None:
    assert migrated_schema["after_downgrade"] == {}
    assert migrated_schema["gene_rows"] == 1

"""Contracts for migration 0057 - gene child constraints dropped by 0033.

0033 swapped the gene primary key with a ``DROP COLUMN gene_id`` on every
child table; PostgreSQL cascaded that into the unique constraints and indexes
that referenced ``gene_id``. Writers that rely on them broke at runtime:
``ON CONFLICT ON CONSTRAINT uq_gene_homolog`` (homolog CSV) and
``ON CONFLICT ON CONSTRAINT uq_expression_gene_library`` (expression CSV) both
raised ``constraint ... does not exist``.

Mirrors ``test_gene_alias_lookup_index.py``: an offline ``alembic --sql``
layer that needs no database, and a real PostgreSQL layer inside a private
schema. The real layer also proves the pre-existing duplicate rows are
deduplicated to the newest row instead of failing the constraint creation.
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
REVISION = API_ROOT / "migrations" / "versions" / "0057_gene_child_constraints.py"

UNIQUE_KEYS = {
    "gene_aliases": ("uq_gene_alias", ("gene_id", "alias")),
    "expression_data": ("uq_expression_gene_library", ("gene_id", "library_id")),
    "gene_homologs": (
        "uq_gene_homolog",
        ("gene_id", "homolog_species", "homolog_gene_id", "homolog_type"),
    ),
}
INDEXES = ("ix_transcript_gene", "ix_vs_gene", "ix_expr_data_gene", "ix_homolog_gene")


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0057", REVISION)
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
    environment["SOYMUTDB_DATABASE_URL"] = "postgresql+asyncpg://offline:offline@localhost/offline"
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


def test_0057_chains_after_the_download_provenance_revision() -> None:
    assert REVISION.is_file()
    revision = _load_revision()
    assert revision.revision == "0057"
    assert revision.down_revision == "0056"


def test_0057_upgrade_restores_every_dropped_object() -> None:
    sql = _offline_sql("upgrade", "0056:0057")
    for table, (constraint, columns) in UNIQUE_KEYS.items():
        assert f"ALTER TABLE {table} ADD CONSTRAINT {constraint} UNIQUE" in sql
        for column in columns:
            assert f"a.{column} = b.{column}" in sql
    for index_name in INDEXES:
        assert f"CREATE INDEX {index_name}" in sql
        assert f"DROP INDEX {index_name}" not in sql


def test_0057_downgrade_removes_only_the_restored_objects() -> None:
    sql = _offline_sql("downgrade", "0057:0056")
    for index_name in INDEXES:
        assert f"DROP INDEX IF EXISTS {index_name}" in sql
    for table, (constraint, _columns) in UNIQUE_KEYS.items():
        assert f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}" in sql
    assert "DROP COLUMN" not in sql
    assert "DROP TABLE" not in sql


# --------------------------------------------------------------------------- #
# Real PostgreSQL layer
# --------------------------------------------------------------------------- #


def _database_url() -> str | None:
    return os.environ.get("SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL") or os.environ.get(
        "SOYMUTDB_TEST_DATABASE_URL"
    )


def _qualified(schema: str, name: str) -> str:
    return '"' + schema + '"."' + name + '"'


def _run_migration(sync_connection, function_name: str) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    revision = _load_revision()
    migration_context = MigrationContext.configure(sync_connection)
    with Operations.context(migration_context):
        with migration_context.begin_transaction():
            getattr(revision, function_name)()


async def _constraint_state(connection, schema: str) -> dict:
    rows = await connection.execute(
        text(
            "SELECT c.relname, con.conname, con.contype "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND con.contype = 'u' "
            "AND c.relname = ANY(:tables)"
        ),
        {"schema": schema, "tables": list(UNIQUE_KEYS)},
    )
    return {(row[0], row[1]): row[2] for row in rows}


async def _index_state(connection, schema: str) -> dict:
    rows = await connection.execute(
        text("SELECT tablename, indexname FROM pg_indexes WHERE schemaname = :schema"),
        {"schema": schema},
    )
    return {(row[0], row[1]) for row in rows}


async def _ids(connection, schema: str, table: str) -> list[int]:
    rows = await connection.execute(
        text("SELECT id FROM " + _qualified(schema, table) + " ORDER BY id")
    )
    return [row[0] for row in rows]


TABLE_DDL = {
    "gene_aliases": "id INTEGER PRIMARY KEY, gene_id BIGINT NOT NULL, alias VARCHAR(256) NOT NULL",
    "expression_data": "id INTEGER PRIMARY KEY, gene_id BIGINT NOT NULL, "
    "library_id INTEGER NOT NULL",
    "gene_homologs": "id INTEGER PRIMARY KEY, gene_id BIGINT NOT NULL, "
    "homolog_species VARCHAR(64) NOT NULL, homolog_gene_id VARCHAR(128) NOT NULL, "
    "homolog_type VARCHAR(32) NOT NULL",
    "transcripts": "id VARCHAR(64) PRIMARY KEY, gene_id BIGINT NOT NULL",
    "variant_summaries": "id BIGINT PRIMARY KEY, gene_id BIGINT",
}

# Two rows per natural key: the migration must keep the newest (highest id).
SEED_SQL = [
    "INSERT INTO {schema}.gene_aliases (id, gene_id, alias) "
    "VALUES (1, 7, 'GLYMA_01G000100'), (2, 7, 'GLYMA_01G000100')",
    "INSERT INTO {schema}.expression_data (id, gene_id, library_id) VALUES (1, 7, 3), (2, 7, 3)",
    "INSERT INTO {schema}.gene_homologs "
    "(id, gene_id, homolog_species, homolog_gene_id, homolog_type) "
    "VALUES (1, 7, 'Arabidopsis thaliana', 'AT1G01010', 'ortholog'), "
    "       (2, 7, 'Arabidopsis thaliana', 'AT1G01010', 'ortholog')",
    "INSERT INTO {schema}.transcripts (id, gene_id) VALUES ('t1', 7)",
    "INSERT INTO {schema}.variant_summaries (id, gene_id) VALUES (1, 7)",
]


@pytest.fixture(scope="module")
def migrated_schema() -> dict:
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

    schema = "gene_child_constraints_" + uuid.uuid4().hex[:12]
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema + ",public"}}
    )

    async def run_step(step: str) -> dict:
        connection = await engine.connect()
        try:
            await connection.run_sync(_run_migration, step)
            await connection.commit()
            return {
                "constraints": await _constraint_state(connection, schema),
                "indexes": await _index_state(connection, schema),
            }
        finally:
            await connection.close()

    async def exercise() -> dict:
        outcome: dict = {}
        try:
            async with engine.connect() as connection:
                await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
                for table, ddl in TABLE_DDL.items():
                    await connection.execute(
                        text("CREATE TABLE " + _qualified(schema, table) + " (" + ddl + ")")
                    )
                for statement in SEED_SQL:
                    await connection.execute(text(statement.format(schema='"' + schema + '"')))
                await connection.commit()

            outcome["after_upgrade"] = await run_step("upgrade")
            outcome["after_rerun"] = await run_step("upgrade")
            outcome["deduplicated_ids"] = {}
            outcome["after_downgrade"] = await run_step("downgrade")

            async with engine.connect() as connection:
                for table in UNIQUE_KEYS:
                    outcome["deduplicated_ids"][table] = await _ids(connection, schema, table)
        finally:
            async with engine.connect() as connection:
                await connection.rollback()
                await connection.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
                await connection.commit()
            await engine.dispose()
        return outcome

    return asyncio.run(exercise())


def test_0057_upgrade_adds_the_missing_unique_constraints(
    migrated_schema: dict,
) -> None:
    constraints = migrated_schema["after_upgrade"]["constraints"]
    for table, (constraint, _columns) in UNIQUE_KEYS.items():
        assert (table, constraint) in constraints, constraints


def test_0057_upgrade_adds_the_missing_lookup_indexes(migrated_schema: dict) -> None:
    indexes = migrated_schema["after_upgrade"]["indexes"]
    names = {name for _table, name in indexes}
    for index_name in INDEXES:
        assert index_name in names, indexes


def test_0057_upgrade_keeps_the_newest_row_per_key(migrated_schema: dict) -> None:
    ids = migrated_schema["deduplicated_ids"]
    assert ids["gene_aliases"] == [2]
    assert ids["expression_data"] == [2]
    assert ids["gene_homologs"] == [2]


def test_0057_upgrade_is_idempotent_on_real_postgres(
    migrated_schema: dict,
) -> None:
    assert migrated_schema["after_rerun"] == migrated_schema["after_upgrade"]


def test_0057_downgrade_removes_only_the_restored_objects_on_real_postgres(
    migrated_schema: dict,
) -> None:
    after = migrated_schema["after_downgrade"]
    assert after["constraints"] == {}
    names = {name for _table, name in after["indexes"]}
    for index_name in INDEXES:
        assert index_name not in names

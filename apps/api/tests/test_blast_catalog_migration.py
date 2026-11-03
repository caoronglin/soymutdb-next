"""PostgreSQL roundtrip for additive catalog migration, with original jobs intact."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/0050_blast_index_catalog.py"


def migration(connection, method):
    spec = importlib.util.spec_from_file_location("blast_catalog_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, method)()


async def legacy_schema(connection):
    # A transaction-local schema exercises the actual PostgreSQL DDL while
    # leaving the fixture's current application schema untouched.
    schema = f"catalog_migration_{uuid.uuid4().hex}"
    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    await connection.execute(text("""
        CREATE TABLE blast_databases (
            id INTEGER PRIMARY KEY, name VARCHAR(256) UNIQUE NOT NULL,
            db_type VARCHAR(4) NOT NULL, assembly_id INTEGER NOT NULL,
            file_path VARCHAR(2048) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT true,
            sequence_count BIGINT NOT NULL DEFAULT 0,
            total_length BIGINT NOT NULL DEFAULT 0,
            build_status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    await connection.execute(text("""
        CREATE TABLE blast_jobs (
            id INTEGER PRIMARY KEY,
            database_id INTEGER NOT NULL REFERENCES blast_databases(id),
            query_sequence TEXT NOT NULL, parameters JSONB
        )
    """))
    await connection.execute(text("""
        INSERT INTO blast_databases(id,name,db_type,assembly_id,file_path) VALUES
        (1,'legacy_protein','prot',1,'/legacy/protein'),
        (2,'legacy_nucleotide','nucl',1,'/legacy/nucleotide')
    """))
    await connection.execute(text("""
        INSERT INTO blast_jobs VALUES(1,1,'MKVLAAGIVGLNLGGK',CAST(:parameters AS jsonb))
    """), {"parameters": '{"evalue":0.00001}'})
    return schema


async def test_catalog_migration_upgrade_downgrade_preserves_legacy_rows_jobs(db_connection):
    schema = await legacy_schema(db_connection)
    await db_connection.execute(text(
        "UPDATE blast_databases SET sequence_count=42,total_length=800,"
        "build_status='ready' WHERE id=1"
    ))
    before = (await db_connection.execute(text("SELECT * FROM blast_databases ORDER BY id"))).all()
    before_jobs = (await db_connection.execute(text("SELECT * FROM blast_jobs"))).all()
    await db_connection.run_sync(migration, "upgrade")
    rows = (await db_connection.execute(text(
        "SELECT engine,sequence_type,build_status,is_default,source_url,annotation_version,"
        "license,provenance FROM blast_databases ORDER BY id"
    ))).all()
    assert rows == [
        ("diamond", "protein", "ready", False, None, None, None, None),
        ("diamond", None, "pending", False, None, None, None, None),
    ]
    # Defaults also protect inserts by an older binary during rolling deploy.
    await db_connection.execute(text("""
        INSERT INTO blast_databases(id,name,db_type,assembly_id,file_path)
        VALUES(3,'old_writer','prot',1,'/legacy/old_writer')
    """))
    assert (await db_connection.execute(text(
        "SELECT engine,build_status,is_default,sequence_type FROM blast_databases WHERE id=3"
    ))).one() == ("diamond", "pending", False, None)
    await db_connection.run_sync(migration, "downgrade")
    assert (await db_connection.execute(text(
        "SELECT * FROM blast_databases WHERE id IN (1,2) ORDER BY id"
    ))).all() == before
    assert (await db_connection.execute(text("SELECT * FROM blast_jobs"))).all() == before_jobs
    columns = (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema "
        "AND table_name='blast_databases'"
    ), {"schema": schema})).scalars().all()
    assert "engine" not in columns and "file_path" in columns
    assert {"sequence_count", "total_length", "build_status"} <= set(columns)
    # Repeat upgrade restores metadata without touching historical jobs.
    await db_connection.run_sync(migration, "upgrade")
    assert (await db_connection.execute(text("SELECT * FROM blast_jobs"))).all() == before_jobs


@pytest.mark.parametrize("field,value", [
    ("engine", "ncbi_blast"), ("build_status", "building"), ("build_status", "failed"),
])
async def test_catalog_downgrade_refuses_indexes_old_runner_cannot_read(
    db_connection, field, value,
):
    await legacy_schema(db_connection)
    await db_connection.run_sync(migration, "upgrade")
    await db_connection.execute(text(f"UPDATE blast_databases SET {field}=:value WHERE id=1"),
                                {"value": value})
    with pytest.raises(DBAPIError, match="Cannot downgrade BLAST catalog"):
        async with db_connection.begin_nested():
            await db_connection.run_sync(migration, "downgrade")
    assert (await db_connection.execute(text("SELECT count(*) FROM blast_jobs"))).scalar_one() == 1
    selected = await db_connection.execute(text(f"SELECT {field} FROM blast_databases WHERE id=1"))
    assert selected.scalar_one() == value

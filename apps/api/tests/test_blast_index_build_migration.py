"""PostgreSQL roundtrip for asynchronous immutable index builds (0052)."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/0052_blast_index_builds.py"
CATALOG = Path(__file__).resolve().parents[1] / "migrations/versions/0050_blast_index_catalog.py"


def migration(connection, path, method):
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    getattr(module, method)()


async def legacy_schema(connection):
    schema = f"build_migration_{uuid.uuid4().hex}"
    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    await connection.execute(text("""
        CREATE TABLE blast_databases (
            id INTEGER PRIMARY KEY, name VARCHAR(256) NOT NULL,
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
        INSERT INTO blast_databases(id,name,db_type,assembly_id,file_path)
        VALUES (1,'legacy','prot',1,'/legacy/index')
    """))
    await connection.run_sync(migration, CATALOG, "upgrade")
    return schema


async def test_upgrade_creates_build_table_and_widens_states(db_connection):
    schema = await legacy_schema(db_connection)
    await db_connection.run_sync(migration, MIGRATION, "upgrade")
    columns = (await db_connection.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema "
        "AND table_name='blast_index_builds'"
    ), {"schema": schema})).scalars().all()
    assert {"id", "state", "build_metadata", "index_identity", "error_message"} <= set(columns)
    await db_connection.execute(text("""
        INSERT INTO blast_index_builds(id,database_id,state,source_object_key,db_type,
                                       build_metadata)
        VALUES (gen_random_uuid(),1,'validating','blast-sources/a.fa','nucl',
                CAST('{}' AS jsonb))
    """))
    await db_connection.execute(text(
        "UPDATE blast_databases SET build_status='published', index_version=repeat('a',64), "
        "fasta_sha256=repeat('b',64) WHERE id=1"
    ))
    with pytest.raises(DBAPIError):
        async with db_connection.begin_nested():
            await db_connection.execute(text(
                "UPDATE blast_databases SET build_status='published', "
                "index_version='short' WHERE id=1"
            ))
    with pytest.raises(DBAPIError):
        async with db_connection.begin_nested():
            await db_connection.execute(text(
                "INSERT INTO blast_index_builds(id,state,source_object_key,db_type,build_metadata)"
                " VALUES (gen_random_uuid(),'unknown','blast-sources/a.fa','nucl',"
                " CAST('{}' AS jsonb))"
            ))


async def test_downgrade_refuses_unfinished_builds(db_connection):
    await legacy_schema(db_connection)
    await db_connection.run_sync(migration, MIGRATION, "upgrade")
    await db_connection.execute(text("""
        INSERT INTO blast_index_builds(id,state,source_object_key,db_type,build_metadata)
        VALUES (gen_random_uuid(),'building','blast-sources/a.fa','nucl',CAST('{}' AS jsonb))
    """))
    with pytest.raises(DBAPIError, match="Cannot downgrade BLAST catalog"):
        async with db_connection.begin_nested():
            await db_connection.run_sync(migration, MIGRATION, "downgrade")


async def test_downgrade_is_clean_for_legacy_only_rows(db_connection):
    schema = await legacy_schema(db_connection)
    await db_connection.run_sync(migration, MIGRATION, "upgrade")
    await db_connection.run_sync(migration, MIGRATION, "downgrade")
    tables = (await db_connection.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"
    ), {"schema": schema})).scalars().all()
    assert "blast_index_builds" not in tables
    assert (await db_connection.execute(text(
        "SELECT build_status FROM blast_databases WHERE id=1"
    ))).scalar_one() == "pending"

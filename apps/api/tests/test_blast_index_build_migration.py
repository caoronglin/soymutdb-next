"""PostgreSQL roundtrip for asynchronous immutable index builds (0054)."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/0054_blast_index_builds.py"
CATALOG = Path(__file__).resolve().parents[1] / "migrations/versions/0050_blast_index_catalog.py"


def migration(connection, path, method):
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The migration module assigns ``op`` at import scope; the attribute is not
    # declared on ModuleType, so set it through its __dict__.
    module.__dict__["op"] = Operations(MigrationContext.configure(connection))
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


def test_build_revision_chains_after_the_lifecycle_revision() -> None:
    """One alembic head, not two.

    Both halves of the asynchronous-index work landed as revision ``0052`` off
    ``0051``: the lifecycle/bookkeeping half and the ``blast_index_builds``
    half. Two revisions sharing an id (and two nodes off one parent) make
    ``alembic upgrade head`` ambiguous, so the build half is ``0054`` and
    chains after ``0053``. This asserts the chain, not just the filename, so a
    future rename cannot silently re-fork it.
    """
    import ast

    versions = Path(__file__).resolve().parents[1] / "migrations/versions"
    revision_of: dict[str, str] = {}
    parent_of: dict[str, str | None] = {}
    for path in versions.glob("*.py"):
        assigned: dict[str, object] = {}
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            else:
                continue
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                assigned[target.id] = node.value.value
        revision = assigned.get("revision")
        if not isinstance(revision, str):
            continue
        assert revision not in revision_of, f"duplicate revision {revision}"
        revision_of[revision] = path.name
        parent = assigned.get("down_revision")
        parent_of[revision] = parent if isinstance(parent, str) else None

    assert revision_of["0054"] == "0054_blast_index_builds.py"
    assert parent_of["0054"] == "0053"
    assert revision_of["0052"] == "0052_blast_index_build_state.py"
    assert parent_of["0052"] == "0051"
    # The revision chain must not fork: exactly one node has no children.
    # The assertion is about *one* head in the tail, not about ``0054`` being the
    # last revision ever written — pinning a literal head made every new
    # migration a red test for a reason unrelated to this file's subject.
    children = set(parent_of.values())
    # Both plain assignments and annotated assignments are scanned above.
    heads = [revision for revision in revision_of if revision not in children]
    tail_heads = [head for head in heads if head >= "0050"]
    assert len(tail_heads) == 1, f"the migration tail must have exactly one head, got {heads}"
    # And the blast revision is not it: `0054` still has a descendant.
    assert tail_heads[0] != "0054"
    assert parent_of["0055"] == "0054"
    assert parent_of["0056"] == "0055"
    assert parent_of["0057"] == "0056"
    assert parent_of["0058"] == "0057"
    # The blast lifecycle keeps its own order regardless of what chains after.
    blast_lineage = [r for r in revision_of if "0050" <= r <= "0054"]
    assert all(parent_of[r] or "" < r for r in blast_lineage if r != "0050")

"""Migration round-trip of the durable variant export records.

The export record is the system of record for "is my export ready?", so its
migration must be reversible: an operator who has to roll the deployment
back must not be left with a half-created table or a dangling enum type.

Two layers are checked:

* the **offline SQL** (the pattern the other migration contracts use): the
  upgrade creates the table, its enum and its indexes, the downgrade removes
  them;
* a **real round-trip** against a throwaway PostgreSQL database: upgrade the
  chain, downgrade 0049, upgrade again, and observe the schema each time.
  The scratch database is created and dropped by the test, so the shared
  test database is never touched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0049_variant_exports.py"

SCRATCH_DATABASE = "soymutdb_variant_exports_migration_rt"


def _offline_alembic(command: str, revision_range: str) -> str:
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
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            command,
            revision_range,
            "--sql",
        ],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_0049_offline_upgrade_creates_the_export_record() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0048:0049")

    assert "CREATE TYPE variant_export_status_enum AS ENUM" in sql
    assert "'pending', 'running', 'succeeded', 'failed'" in sql
    assert "CREATE TABLE variant_exports" in sql
    assert "user_id UUID REFERENCES users(id) ON DELETE SET NULL" in sql
    assert "artifact_path VARCHAR(2048)" in sql
    assert "expires_at TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE INDEX ix_variant_exports_user_id" in sql
    assert "CREATE INDEX ix_variant_exports_status" in sql
    assert "CREATE INDEX ix_variant_exports_created_at" in sql


def test_0049_offline_downgrade_removes_the_export_record() -> None:
    sql = _offline_alembic("downgrade", "0049:0048")

    assert "DROP TABLE IF EXISTS variant_exports" in sql
    assert "DROP TYPE IF EXISTS variant_export_status_enum" in sql


# ---------------------------------------------------------------------------
# Real round-trip against a throwaway database.
# ---------------------------------------------------------------------------


def _server_url() -> str | None:
    url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql+asyncpg://"):
        return None
    return url


def _scratch_url(server_url: str) -> str:
    head, _, _ = server_url.rpartition("/")
    return f"{head}/{SCRATCH_DATABASE}"


async def _create_database(server_url: str) -> bool:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = server_url.rpartition("/")[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE}")
            await connection.exec_driver_sql(f"CREATE DATABASE {SCRATCH_DATABASE}")
    except Exception:
        return False
    finally:
        await engine.dispose()
    return True


async def _drop_database(server_url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    admin_url = server_url.rpartition("/")[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS {SCRATCH_DATABASE} WITH (FORCE)"
            )
    except Exception:
        pass
    finally:
        await engine.dispose()


async def _schema_state(url: str) -> tuple[bool, bool]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = (
                await connection.exec_driver_sql(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename='variant_exports'"
                )
            ).fetchall()
            types = (
                await connection.exec_driver_sql(
                    "SELECT typname FROM pg_type WHERE typname='variant_export_status_enum'"
                )
            ).fetchall()
    finally:
        await engine.dispose()
    return bool(tables), bool(types)


async def _legacy_blast_state(url: str, *, seed: bool = False) -> tuple:
    """Observe genuine historical defaults and values through the full chain."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            if seed:
                await connection.exec_driver_sql(
                    "INSERT INTO blast_databases "
                    "(name,display_name,db_type,program,db_path,file_path,"
                    "sequence_count,total_length) VALUES "
                    "('legacy_rt','Legacy index','prot','blastp','/legacy/index',"
                    "'/legacy/index',42,800)"
                )
            row = (await connection.exec_driver_sql(
                "SELECT name,sequence_count,total_length,build_status,file_path "
                "FROM blast_databases WHERE name='legacy_rt'"
            )).one()
            defaults = (await connection.exec_driver_sql(
                "SELECT column_name,column_default,is_nullable,data_type "
                "FROM information_schema.columns WHERE table_schema='public' "
                "AND table_name='blast_databases' AND column_name IN "
                "('sequence_count','total_length','build_status') ORDER BY column_name"
            )).all()
            return tuple(row), defaults
    finally:
        await engine.dispose()


def _alembic(command: str, revision: str, url: str) -> None:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(workspace_root / "packages/jobs-py/src"),
            str(API_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment["SOYMUTDB_DATABASE_URL"] = url
    environment.setdefault("SOYMUTDB_JWT_SECRET", "test_jwt_secret_for_testing_only")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, revision],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_0049_round_trip_creates_and_removes_the_export_record() -> None:
    server_url = _server_url()
    if server_url is None:
        pytest.skip("SOYMUTDB_TEST_DATABASE_URL is not set; no PostgreSQL to test on")
    if not await _create_database(server_url):
        pytest.skip("the test database server refused to create a scratch database")

    url = _scratch_url(server_url)
    try:
        _alembic("upgrade", "0049", url)
        legacy = await _legacy_blast_state(url, seed=True)
        assert legacy[0] == ("legacy_rt", 42, 800, "pending", "/legacy/index")
        _alembic("upgrade", "head", url)
        assert await _legacy_blast_state(url) == legacy
        assert await _schema_state(url) == (True, True), "the upgrade must create the record"

        _alembic("downgrade", "0048", url)
        assert await _schema_state(url) == (False, False), "the downgrade must remove it"
        assert await _legacy_blast_state(url) == legacy

        # Restore through current head as well: later additive migrations must
        # remain compatible with the genuine historical chain, not just ORM DDL.
        _alembic("upgrade", "head", url)
        assert await _schema_state(url) == (True, True), "the record must be restorable"
        assert await _legacy_blast_state(url) == legacy
    finally:
        await _drop_database(server_url)

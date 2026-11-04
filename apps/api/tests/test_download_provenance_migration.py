"""0056 download provenance: additive upgrade/reversible downgrade.

The new columns are nullable so historical rows survive a rollback; the
sha256 shape constraint is the only database-level rule. Both directions are
exercised against a real PostgreSQL database (SOYMUTDB_TEST_DATABASE_URL),
because an ``ALTER TABLE ... ADD CONSTRAINT`` can compile as offline SQL and
still fail against a live catalog.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0056_download_provenance.py"
SCRATCH_DATABASE = "soymutdb_provenance_0056_rt"

_TABLES = ("download_files", "variant_exports")
_COLUMNS = ("sha256", "license", "generated_at", "source_ref")


def _server_url() -> str | None:
    url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql+asyncpg://"):
        return None
    return url


def _offline_alembic(command: str, revision_range: str) -> str:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join([
        str(workspace_root / "packages/jobs-py/src"),
        str(API_ROOT),
        environment.get("PYTHONPATH", ""),
    ])
    environment["SOYMUTDB_DATABASE_URL"] = (
        "postgresql+asyncpg://offline:offline@localhost/offline"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, revision_range, "--sql"],
        cwd=API_ROOT, env=environment, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_0056_offline_upgrade_adds_only_nullable_provenance_columns() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0055:0056")
    for table in _TABLES:
        for column in _COLUMNS:
            assert f"ALTER TABLE {table} ADD COLUMN {column}" in sql
        assert f"ck_{table}_sha256_shape" in sql
    # No table creation and no domain-data rewrite. Alembic's own
    # ``UPDATE alembic_version`` bookkeeping line is not a data change.
    assert "CREATE TABLE" not in sql
    assert "UPDATE download_files" not in sql
    assert "UPDATE variant_exports" not in sql


def test_0056_offline_downgrade_removes_the_columns_and_constraints() -> None:
    sql = _offline_alembic("downgrade", "0056:0055")
    for table in _TABLES:
        assert f"DROP CONSTRAINT ck_{table}_sha256_shape" in sql
        for column in _COLUMNS:
            assert f"DROP COLUMN {column}" in sql
    assert "DROP TABLE" not in sql


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


async def _columns(url: str, table: str) -> list[str]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (await connection.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='"
                + table.replace("'", "''")
                + "' AND column_name IN ('sha256','license','generated_at','source_ref')"
            )).all()
            return [r[0] for r in rows]
    finally:
        await engine.dispose()


async def _constraints(url: str, table: str) -> list[str]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = (await connection.exec_driver_sql(
                "SELECT conname FROM pg_constraint WHERE conrelid = "
                "('public.' || '" + table.replace("'", "''") + "')::regclass "
                "AND contype='c' AND conname LIKE 'ck_%_sha256_shape'"
            )).all()
            return [r[0] for r in rows]
    finally:
        await engine.dispose()


def _alembic(command: str, revision: str, url: str) -> None:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join([
        str(workspace_root / "packages/jobs-py/src"),
        str(API_ROOT),
        environment.get("PYTHONPATH", ""),
    ])
    environment["SOYMUTDB_DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, revision],
        cwd=API_ROOT, env=environment, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_0056_upgrade_downgrade_roundtrip() -> None:
    server_url = _server_url()
    if server_url is None:
        pytest.skip("set SOYMUTDB_TEST_DATABASE_URL to a PostgreSQL server")
    if not await _create_database(server_url):
        pytest.skip("could not create the scratch database")
    url = server_url.rpartition("/")[0] + "/" + SCRATCH_DATABASE
    try:
        _alembic("upgrade", "0055", url)
        for table in _TABLES:
            assert await _columns(url, table) == []
        _alembic("upgrade", "head", url)
        for table in _TABLES:
            assert sorted(await _columns(url, table)) == sorted(_COLUMNS)
            assert f"ck_{table}_sha256_shape" in await _constraints(url, table)
        # An invalid digest must be rejected by the database, not just by the
        # service: the shape constraint is real.
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.exec_driver_sql(
                    "INSERT INTO download_files (name, file_url, sha256) "
                    "VALUES ('legacy', 'https://example.test/f', NULL)"
                )
                with pytest.raises(Exception):
                    await connection.exec_driver_sql(
                        "INSERT INTO download_files (name, file_url, sha256) "
                        "VALUES ('bad', 'https://example.test/g', 'not-a-digest')"
                    )
        finally:
            await engine.dispose()
        _alembic("downgrade", "0055", url)
        for table in _TABLES:
            assert await _columns(url, table) == []
            assert await _constraints(url, table) == []
        _alembic("upgrade", "head", url)
        for table in _TABLES:
            assert sorted(await _columns(url, table)) == sorted(_COLUMNS)
    finally:
        await _drop_database(server_url)

"""Offline contracts for database-enforced outbox idempotency."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0028_outbox_idempotency_key.py"


def _offline_alembic(command: str, revision_range: str) -> str:
    environment = os.environ.copy()
    site_packages = next((API_ROOT / ".venv/lib").glob("python*/site-packages"))
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(workspace_root / "packages/jobs-py/src"),
            str(API_ROOT),
            str(site_packages),
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
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_0028_upgrade_backfills_one_canonical_key_and_builds_unique_index() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0027:0028")

    assert "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)" in sql
    assert "row_number() OVER" in sql
    assert "ranked.occurrence = 1" in sql
    assert "DROP INDEX CONCURRENTLY IF EXISTS uq_outbox_events_idempotency_key" in sql
    assert "CREATE UNIQUE INDEX CONCURRENTLY uq_outbox_events_idempotency_key" in sql
    assert "WHERE idempotency_key IS NOT NULL" in sql


def test_0028_downgrade_removes_index_and_column_restart_safely() -> None:
    sql = _offline_alembic("downgrade", "0028:0027")

    assert "DROP INDEX CONCURRENTLY IF EXISTS uq_outbox_events_idempotency_key" in sql
    assert "DROP COLUMN IF EXISTS idempotency_key" in sql

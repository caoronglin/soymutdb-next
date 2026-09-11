"""Offline PostgreSQL contracts for the durable outbox lease migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0018_outbox_leases.py"


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


def test_0018_offline_upgrade_adds_processing_enum_and_lease_fence() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0017:0018")

    assert "CREATE TYPE outbox_event_status_enum AS ENUM" in sql
    assert "'pending', 'processing', 'sent', 'failed'" in sql
    assert "ADD COLUMN lease_owner UUID" in sql
    assert "ADD COLUMN lease_until TIMESTAMP WITH TIME ZONE" in sql
    assert "ck_outbox_events_processing_lease" in sql
    assert "ix_outbox_events_status_lease_until" in sql


def test_0018_offline_downgrade_requeues_claimed_rows_and_restores_enum() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("downgrade", "0018:0017")

    assert "UPDATE outbox_events" in sql
    assert "status = 'pending'" in sql
    assert "DROP COLUMN lease_until" in sql
    assert "DROP COLUMN lease_owner" in sql
    assert "CREATE TYPE outbox_event_status_enum AS ENUM ('pending', 'sent', 'failed')" in sql

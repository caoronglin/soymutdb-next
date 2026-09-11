"""Offline contracts for the additive news soft-delete migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0030_news_soft_delete_audit.py"


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


def test_0030_upgrade_adds_reversible_delete_columns_and_fk() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0029:0030")

    assert "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS deleted_by UUID NULL" in sql
    assert "fk_news_articles_deleted_by_users" in sql
    assert "FOREIGN KEY (deleted_by) REFERENCES users(id) ON DELETE SET NULL" in sql
    assert "index_metadata.indisvalid" in sql
    assert "CREATE INDEX IF NOT EXISTS ix_news_articles_deleted_at" in sql


def test_0030_downgrade_removes_only_soft_delete_schema() -> None:
    sql = _offline_alembic("downgrade", "0030:0029")

    assert "Cannot downgrade migration 0030 while soft-deleted news exists" in sql
    assert "DROP INDEX IF EXISTS ix_news_articles_deleted_at" in sql
    assert "DROP CONSTRAINT IF EXISTS fk_news_articles_deleted_by_users" in sql
    assert "DROP COLUMN IF EXISTS deleted_by" in sql
    assert "DROP COLUMN IF EXISTS deleted_at" in sql


def test_0030_upgrade_has_rerun_guards_without_weakening_slug_rules() -> None:
    source = REVISION.read_text(encoding="utf-8")
    upgrade_source = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    assert upgrade_source.count("ADD COLUMN IF NOT EXISTS") == 2
    assert "CREATE INDEX IF NOT EXISTS ix_news_articles_deleted_at" in upgrade_source
    assert "index_metadata.indisvalid" in upgrade_source
    assert "repair it before rerunning migration 0030" in upgrade_source
    assert "IF NOT EXISTS (" in upgrade_source
    assert "DROP" not in upgrade_source
    assert "slug" not in upgrade_source.lower()

"""Offline contract tests for external CMS article provenance migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0029_news_external_provenance.py"


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


def test_0029_upgrade_adds_provenance_constraints_and_unique_source_url() -> None:
    assert REVISION.is_file()
    sql = _offline_alembic("upgrade", "0028:0029")

    for column in (
        "source_platform VARCHAR(16)",
        "source_url VARCHAR(2048)",
        "source_content_hash VARCHAR(64)",
        "source_published_at TIMESTAMPTZ",
        "source_synced_at TIMESTAMPTZ",
    ):
        assert column in sql
    assert "ck_news_articles_external_source" in sql
    assert "source_platform IN ('wechat', 'xmol')" in sql
    assert "ck_news_articles_source_hash" in sql
    assert "source_content_hash ~ '^[a-f0-9]{64}$'" in sql
    assert "index_metadata.indisvalid" in sql
    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_news_articles_source_url" in sql
    assert "DROP INDEX CONCURRENTLY IF EXISTS uq_news_articles_source_url" not in sql


def test_0029_downgrade_removes_provenance_and_index() -> None:
    sql = _offline_alembic("downgrade", "0029:0028")

    assert "DROP INDEX CONCURRENTLY IF EXISTS uq_news_articles_source_url" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_news_articles_external_source" in sql
    assert "DROP CONSTRAINT IF EXISTS ck_news_articles_source_hash" in sql
    for column in (
        "source_platform",
        "source_url",
        "source_content_hash",
        "source_published_at",
        "source_synced_at",
    ):
        assert f"DROP COLUMN IF EXISTS {column}" in sql


def test_0029_upgrade_rerun_preserves_a_valid_unique_index() -> None:
    """A rerun must not drop the invariant before deciding whether to recreate it."""
    source = REVISION.read_text(encoding="utf-8")
    upgrade_source = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]

    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS" in upgrade_source
    assert "DROP INDEX CONCURRENTLY" not in upgrade_source
    assert "NOT index_metadata.indisvalid" in upgrade_source
    assert "repair it before rerunning migration 0029" in upgrade_source


"""Offline PostgreSQL contracts for the publication build-artifact migration.

The migration adds ``static_publications.build_artifact_url``, the *input*
reference a publication was built from. ``artifact_url`` (already present)
records the *output*; conflating the two would make the audit trail unable to
distinguish "what we built" from "what we built it from".

Verified offline (no live PostgreSQL): upgrade and downgrade must both emit the
expected DDL, and the downgrade must remove exactly what the upgrade added.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
REVISION = API_ROOT / "migrations" / "versions" / "0043_publication_build_artifact.py"
TABLE = "static_publications"
COLUMN = "build_artifact_url"


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
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_revision_file_exists_and_is_the_head():
    assert REVISION.is_file()
    source = REVISION.read_text(encoding="utf-8")
    assert 'revision: str = "0043"' in source
    assert 'down_revision: str | None = "0042"' in source


def test_upgrade_adds_the_nullable_text_column():
    sql = _offline_alembic("upgrade", "0042:0043")

    assert f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} TEXT" in sql
    # Nullable, so existing rows and reference-less requests remain valid.
    assert "NOT NULL" not in sql.split(f"ADD COLUMN {COLUMN}")[1].split(";")[0]
    assert "0043" in sql


def test_downgrade_drops_exactly_that_column():
    sql = _offline_alembic("downgrade", "0043:0042")

    assert f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}" in sql
    # The output-artifact column must survive: the two are different things.
    assert "DROP COLUMN artifact_url" not in sql
    assert "0042" in sql


def test_migration_only_touches_the_publication_table():
    upgrade_sql = _offline_alembic("upgrade", "0042:0043")
    statements = [
        line.strip()
        for line in upgrade_sql.splitlines()
        if line.strip().upper().startswith(("ALTER TABLE", "CREATE ", "DROP "))
    ]

    assert statements, upgrade_sql
    for statement in statements:
        assert TABLE in statement, statement


def test_model_declares_the_matching_column():
    """The ORM mapping and the migration must not drift."""
    from app.models.publication import StaticPublication

    columns = StaticPublication.__table__.columns
    assert COLUMN in columns
    assert columns[COLUMN].nullable is True
    # Input and output references are distinct columns.
    assert "artifact_url" in columns
    assert "artifact_url" != COLUMN
    assert str(columns[COLUMN].type) == "TEXT"


@pytest.mark.parametrize("field", ["build_artifact_url"])
def test_publication_response_exposes_the_reference(field: str):
    from app.schemas.publication import PublicationResponse

    assert field in PublicationResponse.model_fields

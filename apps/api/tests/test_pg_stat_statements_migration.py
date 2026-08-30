"""Offline contract for the pg_stat_statements enablement migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/0025_pg_stat_statements.py"


class RecordingOperations:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement: str) -> None:
        self.executed.append(statement)


def _load_migration():
    spec = importlib.util.spec_from_file_location("pg_stat_statements_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pg_stat_statements_migration_is_additive_and_non_destructive() -> None:
    migration = _load_migration()
    operations = RecordingOperations()
    migration.op = operations

    assert migration.revision == "0025"
    assert migration.down_revision == "0024"
    migration.upgrade()

    assert operations.executed == ["CREATE EXTENSION IF NOT EXISTS pg_stat_statements"]

    migration.downgrade()
    assert operations.executed == ["CREATE EXTENSION IF NOT EXISTS pg_stat_statements"]

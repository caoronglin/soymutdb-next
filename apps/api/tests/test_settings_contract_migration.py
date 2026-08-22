"""Expand-only migration contract for versioned runtime settings."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0020_system_setting_revisions.py"
)


def test_settings_revision_migration_exists() -> None:
    assert MIGRATION.is_file(), "0020 expand-only settings revision migration is required"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("settings_revision_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Operations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def record(*args: Any, **kwargs: Any) -> str | None:
            self.calls.append((name, args, kwargs))
            return args[0] if name == "f" else None

        return record


def test_upgrade_only_expands_with_immutable_revision_storage() -> None:
    revision = _load_migration()
    operations = _Operations()
    revision.op = operations

    revision.upgrade()

    create_calls = [call for call in operations.calls if call[0] == "create_table"]
    assert create_calls, "upgrade must create the settings revision table"
    create_table = create_calls[0]
    assert create_table[1][0] == "system_setting_revisions"
    column_names = {
        element.name for element in create_table[1][1:] if hasattr(element, "name")
    }
    assert {
        "id",
        "section",
        "version",
        "action",
        "snapshot",
        "changes",
        "created_by",
        "rollback_from_version",
        "reason",
        "created_at",
    } <= column_names
    assert any(call[0] == "create_index" for call in operations.calls)
    assert not {"add_column", "alter_column", "drop_column", "drop_table"} & {
        call[0] for call in operations.calls
    }

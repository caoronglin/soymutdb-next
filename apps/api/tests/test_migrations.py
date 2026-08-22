"""Focused offline contracts for the Alembic revision chain."""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.api.v1.auth import register
from app.core.exceptions import ServiceUnavailableError
from app.core.security import RoleName
from app.schemas.auth import UserCreate

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_ROOT = API_ROOT / "migrations"


def _load_revision(filename: str) -> ModuleType:
    path = MIGRATIONS_ROOT / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if name == "f":
                return args[0]
            return None

        return record


def test_env_imports_base_from_the_model_registry() -> None:
    tree = ast.parse((MIGRATIONS_ROOT / "env.py").read_text(encoding="utf-8"))
    imports = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert ("app.models", "Base") in imports
    assert ("app.core.database", "Base") not in imports


def test_0008_preserves_the_hit_count_owned_by_0001() -> None:
    revision = _load_revision("0008_blast_result_hits.py")
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    executed_sql = "\n".join(
        str(args[0]) for name, args, _ in operations.calls if name == "execute"
    )
    assert "ADD COLUMN IF NOT EXISTS hit_count" in executed_sql

    operations.calls.clear()
    revision.downgrade()
    dropped_columns = {
        args[1] for name, args, _ in operations.calls if name == "drop_column"
    }
    assert "hit_count" not in dropped_columns


def test_0009_preserves_the_published_uppercase_enum_history() -> None:
    source = (MIGRATIONS_ROOT / "versions" / "0009_analysis_jobs.py").read_text(
        encoding="utf-8"
    )

    assert 'sa.Enum("FASTP", "SCANPY", name="analysis_type_enum")' in source
    for label in (
        "PENDING",
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCEL_REQUESTED",
        "CANCELLED",
    ):
        assert f'"{label}"' in source


def test_0019_converts_legacy_enums_and_seeds_every_application_role() -> None:
    path = MIGRATIONS_ROOT / "versions" / "0019_normalize_analysis_enums_and_seed_roles.py"
    assert path.exists(), "0019 forward migration is required"
    revision = _load_revision(path.name)
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    sql = "\n".join(
        str(args[0]) for name, args, _ in operations.calls if name == "execute"
    )

    assert "lower(analysis_type::text)::analysis_type_enum" in sql
    assert "lower(status::text)::analysis_job_status_enum" in sql
    assert "ON CONFLICT (name) DO NOTHING" in sql
    assert "WHERE role_id IS NULL" in sql
    assert {role.value for role in RoleName} <= {value for value in sql.split("'")[1::2]}


def test_0021_creates_import_studio_version_chain() -> None:
    path = MIGRATIONS_ROOT / "versions" / "0021_import_studio_chain.py"
    assert path.exists(), "0021 import-studio migration is required"
    revision = _load_revision(path.name)
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    tables = {
        args[0] if args else None
        for name, args, _ in operations.calls
        if name == "create_table"
    }
    assert {
        "dataset_versions",
        "import_drafts",
        "import_field_mappings",
        "import_data_patches",
        "page_data_sources",
        "import_publication_manifests",
    } <= tables
    sql = "\n".join(
        str(args[0]) for name, args, _ in operations.calls if name == "execute"
    )
    assert "CREATE TYPE import_draft_status_enum" in sql


class _EmptyResult:
    def scalar_one_or_none(self) -> None:
        return None


class _RegistrationSessionWithoutViewer:
    def __init__(self) -> None:
        self.add_called = False

    async def execute(self, _statement: Any) -> _EmptyResult:
        return _EmptyResult()

    def add(self, _value: Any) -> None:
        self.add_called = True

    async def commit(self) -> None:
        return None

    async def refresh(self, user: Any) -> None:
        now = datetime.now(UTC)
        user.role_rel = None
        user.is_superuser = False
        user.joined_at = now
        user.last_login_at = None
        user.created_at = now
        user.updated_at = now


async def test_registration_fails_closed_when_viewer_role_is_missing() -> None:
    payload = UserCreate(
        username="missing_viewer",
        email="missing-viewer@example.org",
        password="SecurePass123!",
        full_name="Missing Viewer",
        role_name=RoleName.VIEWER.value,
    )
    session = _RegistrationSessionWithoutViewer()

    with pytest.raises(ServiceUnavailableError, match="viewer role"):
        await register(payload, db=session)  # type: ignore[arg-type]

    assert session.add_called is False


def test_offline_upgrade_uses_model_enum_values_and_safe_blast_ddl() -> None:
    environment = os.environ.copy()
    environment["SOYMUTDB_DATABASE_URL"] = (
        "postgresql+asyncpg://offline:offline@localhost/offline"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "ADD COLUMN IF NOT EXISTS hit_count" in result.stdout
    assert "CREATE TYPE analysis_type_enum AS ENUM ('FASTP', 'SCANPY')" in result.stdout
    assert "CREATE TYPE analysis_type_enum AS ENUM ('fastp', 'scanpy')" in result.stdout
    assert "'pending', 'queued', 'running', 'succeeded', 'failed'" in result.stdout
    assert "DEFAULT 'queued'" in result.stdout
    assert "AS ENUM ();" not in result.stdout
    for enum_name in (
        "variant_type_enum",
        "impact_enum",
        "import_task_type_enum",
        "import_task_status_enum",
        "expression_tissue_enum",
        "expression_treatment_enum",
        "homolog_type_enum",
        "widget_category_enum",
        "widget_permission_enum",
    ):
        assert result.stdout.count(f"CREATE TYPE {enum_name} AS ENUM") == 1

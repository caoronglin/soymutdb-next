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


def test_testcontainer_fixture_seeds_the_role_catalog_after_create_all() -> None:
    """A ``create_all`` test database must match the migration's RBAC baseline."""
    fixture = (API_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "from app.core.security import RoleName" in fixture
    assert "from app.models.auth import Role" in fixture
    assert "insert(Role)" in fixture
    assert "for role in RoleName" in fixture


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


def test_0036_enforces_one_import_draft_per_dataset_version_and_downgrades() -> None:
    path = MIGRATIONS_ROOT / "versions" / "0036_unique_import_draft_per_dataset_version.py"
    assert path.exists(), "0036 import-draft uniqueness migration is required"
    revision = _load_revision(path.name)
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    created = [
        (args, kwargs)
        for name, args, kwargs in operations.calls
        if name == "create_unique_constraint"
    ]
    assert created == [
        (("uq_import_drafts_dataset_version", "import_drafts", ["dataset_version_id"]), {})
    ]

    operations.calls.clear()
    revision.downgrade()
    dropped = [
        (args, kwargs)
        for name, args, kwargs in operations.calls
        if name == "drop_constraint"
    ]
    assert dropped == [
        (
            ("uq_import_drafts_dataset_version", "import_drafts"),
            {"type_": "unique"},
        )
    ]


def test_0038_annotation_migration_adds_scoped_tables_and_downgrades() -> None:
    revision = _load_revision("0038_gene_annotation_provenance.py")
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    created_tables = {
        args[0]
        for name, args, _ in operations.calls
        if name == "create_table"
    }
    assert created_tables == {"gene_annotation_sets", "gene_annotations"}
    created_constraints = {
        getattr(element, "name", None)
        for name, args, _ in operations.calls
        if name == "create_table"
        for element in args[1:]
    }
    assert {
        "fk_gene_annotation_sets_assembly_release",
        "fk_gene_annotations_set_scope",
        "fk_gene_annotations_gene_assembly",
        "uq_gene_annotation_sets_scope",
        "uq_gene_annotations_evidence",
    } <= created_constraints
    assert (
        "create_unique_constraint",
        ("uq_assemblies_id_release", "assemblies", ["id", "release_id"]),
        {},
    ) in operations.calls

    operations.calls.clear()
    revision.downgrade()
    dropped_tables = {
        args[0]
        for name, args, _ in operations.calls
        if name == "drop_table"
    }
    assert dropped_tables == {"gene_annotation_sets", "gene_annotations"}
    assert any(
        name == "drop_constraint"
        and args == ("uq_assemblies_id_release", "assemblies")
        and kwargs == {"type_": "unique"}
        for name, args, kwargs in operations.calls
    )


def test_0039_table_views_migration_adds_tables_constraints_and_downgrades() -> None:
    revision = _load_revision("0039_table_views_and_species_instances.py")
    operations = _RecordingOperations()
    revision.op = operations

    revision.upgrade()
    created_tables = {
        args[0] for name, args, _ in operations.calls if name == "create_table"
    }
    assert created_tables == {"table_view_templates", "species_instances"}

    # The default-uniqueness index must key on coalesce(release_id, 0): a plain
    # unique index treats two NULL release scopes as distinct, which would let
    # two deployment-wide defaults coexist for the same kind/species/variant.
    index_sql = [
        args[0]
        for name, args, _ in operations.calls
        if name == "execute" and isinstance(args[0], str)
    ]
    assert any(
        "uq_table_view_templates_default" in statement
        and "coalesce(release_id, 0)" in statement
        and "WHERE is_default" in statement
        for statement in index_sql
    ), index_sql

    created_constraints = {
        getattr(element, "name", None)
        for name, args, _ in operations.calls
        if name == "create_table"
        for element in args[1:]
    }
    assert {
        "ck_table_view_templates_kind",
        "ck_table_view_templates_site_variant",
        "ck_table_view_templates_columns_array",
        "ck_species_instances_url",
        "fk_table_view_templates_release",
    } <= created_constraints

    operations.calls.clear()
    revision.downgrade()
    dropped_tables = {
        args[0] for name, args, _ in operations.calls if name == "drop_table"
    }
    assert dropped_tables == {"table_view_templates", "species_instances"}


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
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            os.path.relpath(workspace_root / "packages/jobs-py/src", API_ROOT),
            os.path.relpath(API_ROOT, API_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
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
        encoding="utf-8",
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
    assert "CREATE TABLE gene_annotation_sets" in result.stdout
    assert "CREATE TABLE gene_annotations" in result.stdout
    assert "fk_gene_annotations_gene_assembly" in result.stdout

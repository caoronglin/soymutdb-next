"""Focused, static tests for the A0 runtime-facts collector.

This module intentionally does not use the API test-suite fixtures.  The
collector must remain import-free with respect to the application and must
only inspect the temporary project tree supplied by each test.
"""

from __future__ import annotations

import builtins as rl_builtins
import hashlib as rl_hashlib
import importlib.util as rl_importlib_util
import json as rl_json
import os as rl_os
import re as rl_re
import subprocess as rl_subprocess
import sys as rl_sys
import types as rl_types
from pathlib import Path as rl_Path

import pytest as rl_pytest

rl_collector_path = (
    rl_Path(__file__).resolve().parents[4] / "tools" / "a0" / "rl_collect_runtime_facts.py"
)
rl_collector_spec = rl_importlib_util.spec_from_file_location(
    "rl_test_runtime_facts_collector", rl_collector_path
)
assert rl_collector_spec is not None and rl_collector_spec.loader is not None
rl_collector_module = rl_importlib_util.module_from_spec(rl_collector_spec)
rl_collector_spec.loader.exec_module(rl_collector_module)
rl_collect_runtime_facts = rl_collector_module.rl_collect_runtime_facts
rl_main = rl_collector_module.rl_main


def rl_seed_project(rl_root: rl_Path) -> None:
    """Create a small static project containing the facts under test."""

    rl_files = {
        "README.md": """
# Project
- Node.js ≥ 20 (pnpm ≥ 10)
- Python ≥ 3.10
cd apps/api && uvicorn app.main:app --reload --port 8000
""",
        "package.json": (
            '{"engines":{"node":">=20.0.0","pnpm":">=10.0.0"},"packageManager":"pnpm@10.0.0"}'
        ),
        "apps/api/pyproject.toml": """
[project]
name = "soymutdb-api"
requires-python = ">=3.14"
dependencies = ["fastapi==0.1", "asyncpg>=0.30.0"]
""",
        "apps/worker/pyproject.toml": """
[project]
name = "soymutdb-worker"
requires-python = ">=3.13"
dependencies = ["celery>=5.4.0", "psycopg2-binary>=2.9.0"]
""",
        "apps/worker/README.md": """
# SoyMutDB Worker
Celery worker application for asynchronous bioinformatics tasks.
apps/worker/src/soymutdb_worker/
celery -A soymutdb_worker.main worker --loglevel=info
""",
        "docker-compose.yml": """
services:
  postgres:
    image: postgres:18.6-alpine
  api:
    build:
      dockerfile: infra/docker/Dockerfile.api
    environment:
      DATABASE_URL: postgresql+asyncpg://db:unsafe-value@postgres:5432/soymutdb
""",
        "docker-compose.dev.yml": """
services:
  api:
    volumes:
      - ./apps/api/src:/app/src:ro
    command: uvicorn soymutdb.main:app
""",
        "apps/api/app/main.py": """app = object()\n""",
        "apps/api/app/core/config.py": """
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SOYMUTDB_", extra="ignore")
    database_url: str = "postgresql+asyncpg://soymutdb:unsafe-value@localhost:5432/soymutdb"
    jwt_secret: str = "jwt-unsafe-value"
    admin_password: str = "admin-unsafe-value"

@lru_cache
def get_settings() -> Settings:
    return Settings()
""",
        "apps/api/app/core/database.py": """
from .config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine

settings = get_settings()

def get_engine():
    return create_async_engine(settings.database_url)
""",
        "apps/api/migrations/env.py": """
from alembic import context
from app.core.config import get_settings
from app.core.database import Base
from app.models import *
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

async def run_async_migrations():
    connectable = async_engine_from_config({}, prefix="sqlalchemy.")
""",
        "apps/api/alembic.ini": """
[alembic]
script_location = migrations
sqlalchemy.url = postgresql+asyncpg://soymutdb:unsafe-value@localhost:5432/soymutdb
""",
        "infra/docker/Dockerfile.api": """
FROM python:3.14.6-slim
WORKDIR /app/apps/api
CMD ["uvicorn", "soymutdb.main:app"]
""",
        "infra/docker/Dockerfile.worker": """
FROM python:3.13-slim
WORKDIR /app/apps/worker
CMD ["celery", "-A", "soymutdb_worker.main:celery_app", "worker"]
""",
        "infra/docker/Dockerfile.web": """
FROM node:24-alpine
WORKDIR /app
CMD ["nginx", "-g", "daemon off;"]
""",
        "infra/docker/Dockerfile.admin": """
FROM node:24-alpine
WORKDIR /app
CMD ["nginx", "-g", "daemon off;"]
""",
        "apps/jbrowse/Dockerfile": """
FROM node:24-alpine
WORKDIR /app
""",
        "apps/worker/src/soymutdb_worker/main.py": """
celery_app = object()
""",
    }
    for rl_relative_path, rl_content in rl_files.items():
        rl_path = rl_root / rl_relative_path
        rl_path.parent.mkdir(parents=True, exist_ok=True)
        rl_path.write_text(rl_content, encoding="utf-8")


def test_rl_collects_static_facts_and_redacts_sensitive_values(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)

    assert rl_report["rl_schema_version"] == "a0.runtime-facts.v1"
    assert rl_report["rl_facts"]["rl_requirements"]["rl_api"]["rl_requires_python"] == ">=3.14"
    assert rl_report["rl_facts"]["rl_requirements"]["rl_worker"]["rl_requires_python"] == ">=3.13"
    assert rl_report["rl_facts"]["rl_node"]["rl_node_requirement"] == ">=20.0.0"
    assert rl_report["rl_facts"]["rl_compose"]["rl_postgresql_image"] == "postgres:18.6-alpine"
    assert rl_report["rl_facts"]["rl_api_asyncpg"]["rl_present"] is True
    assert (
        rl_report["rl_facts"]["rl_config"]["rl_database_url_default"]["rl_classification"]
        == "poisoned_default"
    )
    assert (
        rl_report["rl_facts"]["rl_alembic"]["rl_sqlalchemy_url"]["rl_classification"]
        == "poisoned_default"
    )
    assert rl_report["rl_facts"]["rl_database"]["rl_module_level_settings_capture"] is True
    assert rl_report["rl_facts"]["rl_migrations_env"]["rl_async_engine_from_config"] is True
    assert [
        rl_context["rl_context"] for rl_context in rl_report["rl_facts"]["rl_execution_contexts"]
    ] == ["OpenAPI/API cwd", "Worker/root cwd", "Alembic/API cwd", "A0/root cwd"]
    assert rl_report["rl_facts"]["rl_path_drift"]

    for rl_sensitive in (
        "unsafe-value",
        "jwt-unsafe-value",
        "admin-unsafe-value",
        "postgresql+asyncpg://soymutdb:unsafe-value@",
    ):
        assert rl_sensitive not in rl_serialized


def test_rl_missing_parse_and_command_failures_are_explicit(tmp_path: rl_Path) -> None:
    (tmp_path / "apps/api").mkdir(parents=True)
    (tmp_path / "apps/api/pyproject.toml").write_text("[project\n", encoding="utf-8")

    rl_report = rl_collect_runtime_facts(
        tmp_path,
        {"rl_missing_python": ("rl-command-that-is-not-installed", "--version")},
        rl_command_runner=lambda *rl_args, **rl_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("fake command unavailable")
        ),
    )

    rl_blocking_ids = {rl_fact["rl_fact_id"] for rl_fact in rl_report["rl_blocking_facts"]}
    assert "rl_missing_file:README.md" in rl_blocking_ids
    assert "rl_parse:apps/api/pyproject.toml" in rl_blocking_ids
    assert "rl_command_unavailable:rl_missing_python" in rl_blocking_ids


def test_rl_cli_writes_deterministic_json_to_requested_temp_output(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)
    rl_output = tmp_path / "nested" / "runtime-facts.json"

    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert rl_result.returncode == 0, rl_result.stderr
    assert rl_output.exists()
    assert rl_json.loads(rl_output.read_text(encoding="utf-8"))["rl_schema_version"] == (
        "a0.runtime-facts.v1"
    )


def test_rl_cli_success_exit_status_requires_complete_fixture(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)
    rl_output = tmp_path / "complete-runtime-facts.json"

    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert rl_result.returncode == 0, rl_result.stderr
    assert rl_json.loads(rl_output.read_text(encoding="utf-8"))["rl_blocking_facts"] == []


@rl_pytest.mark.parametrize(
    ("rl_empty_source", "rl_expected_missing_facts"),
    [
        (
            "apps/api/app/core/config.py",
            {
                "rl_missing_fact:apps/api/app/core/config.py.rl_settings_source",
                "rl_missing_fact:apps/api/app/core/config.py.rl_env_file",
                "rl_missing_fact:apps/api/app/core/config.py.rl_cache",
                "rl_missing_fact:apps/api/app/core/config.py.rl_database_url",
            },
        ),
        (
            "apps/api/app/core/database.py",
            {
                "rl_missing_fact:apps/api/app/core/database.py.rl_settings_capture",
                "rl_missing_fact:apps/api/app/core/database.py.rl_async_engine",
                "rl_missing_fact:apps/api/app/core/database.py.rl_database_url",
            },
        ),
        (
            "apps/api/migrations/env.py",
            {
                "rl_missing_fact:apps/api/migrations/env.py.rl_config_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_database_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_models_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_settings_override",
                "rl_missing_fact:apps/api/migrations/env.py.rl_async_engine",
                "rl_missing_fact:apps/api/migrations/env.py.rl_async_online_path",
            },
        ),
    ],
)
def test_rl_empty_required_python_source_is_blocking_via_cli(
    tmp_path: rl_Path,
    rl_empty_source: str,
    rl_expected_missing_facts: set[str],
) -> None:
    """Empty Python files must write a safe report and exit non-zero."""

    rl_seed_project(tmp_path)
    (tmp_path / rl_empty_source).write_text("", encoding="utf-8")
    rl_output = tmp_path / "empty-python-runtime-facts.json"

    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert rl_result.returncode != 0, rl_result.stderr
    assert rl_output.exists()
    rl_report = rl_json.loads(rl_output.read_text(encoding="utf-8"))
    rl_blocking_ids = {rl_fact["rl_fact_id"] for rl_fact in rl_report["rl_blocking_facts"]}
    assert rl_expected_missing_facts <= rl_blocking_ids
    assert "postgresql+asyncpg://" not in rl_output.read_text(encoding="utf-8")


@rl_pytest.mark.parametrize(
    ("rl_incomplete_source", "rl_expected_missing_facts"),
    [
        (
            "apps/api/app/core/config.py",
            {
                "rl_missing_fact:apps/api/app/core/config.py.rl_settings_source",
                "rl_missing_fact:apps/api/app/core/config.py.rl_env_file",
                "rl_missing_fact:apps/api/app/core/config.py.rl_cache",
                "rl_missing_fact:apps/api/app/core/config.py.rl_database_url",
            },
        ),
        (
            "apps/api/app/core/database.py",
            {
                "rl_missing_fact:apps/api/app/core/database.py.rl_settings_capture",
                "rl_missing_fact:apps/api/app/core/database.py.rl_async_engine",
                "rl_missing_fact:apps/api/app/core/database.py.rl_database_url",
            },
        ),
        (
            "apps/api/migrations/env.py",
            {
                "rl_missing_fact:apps/api/migrations/env.py.rl_config_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_database_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_models_import",
                "rl_missing_fact:apps/api/migrations/env.py.rl_settings_override",
                "rl_missing_fact:apps/api/migrations/env.py.rl_async_engine",
                "rl_missing_fact:apps/api/migrations/env.py.rl_async_online_path",
            },
        ),
    ],
)
def test_rl_nonempty_required_python_source_missing_structure_is_blocking_via_cli(
    tmp_path: rl_Path,
    rl_incomplete_source: str,
    rl_expected_missing_facts: set[str],
) -> None:
    """A syntactically valid but irrelevant module must still fail closed."""

    rl_seed_project(tmp_path)
    (tmp_path / rl_incomplete_source).write_text("rl_unrelated_value = 1\n", encoding="utf-8")
    rl_output = tmp_path / "incomplete-python-runtime-facts.json"

    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert rl_result.returncode != 0, rl_result.stderr
    rl_report = rl_json.loads(rl_output.read_text(encoding="utf-8"))
    rl_blocking_ids = {rl_fact["rl_fact_id"] for rl_fact in rl_report["rl_blocking_facts"]}
    assert rl_expected_missing_facts <= rl_blocking_ids


@rl_pytest.mark.parametrize(
    "rl_sensitive_fragment",
    ["PASSWORD=do-not-leak", "Bearer do-not-leak", "token=do-not-leak"],
)
def test_rl_redaction_does_not_emit_typical_secret_fragments(
    tmp_path: rl_Path, rl_sensitive_fragment: str
) -> None:
    rl_seed_project(tmp_path)
    (tmp_path / "README.md").write_text(rl_sensitive_fragment, encoding="utf-8")

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)

    assert "do-not-leak" not in rl_serialized


def rl_blocking_ids(rl_report: dict) -> set[str]:
    """Return blocking identifiers without coupling tests to report ordering."""

    return {rl_fact["rl_fact_id"] for rl_fact in rl_report["rl_blocking_facts"]}


def rl_run_cli(
    rl_root: rl_Path, rl_output_name: str
) -> tuple[rl_subprocess.CompletedProcess, dict]:
    """Run the real collector module and load its complete JSON output."""

    rl_output = rl_root / rl_output_name
    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(rl_root),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert rl_output.exists()
    rl_report = rl_json.loads(rl_output.read_text(encoding="utf-8"))
    return rl_result, rl_report


def test_rl_migration_import_order_is_blocking_via_cli(tmp_path: rl_Path) -> None:
    """A decoy-first import order cannot be repaired by a later correct import."""

    rl_seed_project(tmp_path)
    (tmp_path / "apps/api/migrations/env.py").write_text(
        """
from app.core.database import Base
from app.core.config import get_settings
from app.models import *
from alembic import context

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

async def run_async_migrations():
    connectable = async_engine_from_config({}, prefix="sqlalchemy.")
""",
        encoding="utf-8",
    )

    rl_result, rl_report = rl_run_cli(tmp_path, "wrong-import-order.json")
    rl_serialized = (tmp_path / "wrong-import-order.json").read_text(encoding="utf-8")

    assert rl_result.returncode != 0
    assert "rl_import_order:apps/api/migrations/env.py" in rl_blocking_ids(rl_report)
    assert "postgresql+asyncpg://" not in rl_serialized
    assert "unsafe-value" not in rl_serialized


@rl_pytest.mark.parametrize(
    ("rl_spoof_source", "rl_spoof_content", "rl_expected_fact"),
    [
        (
            "apps/api/app/core/config.py",
            '''"""
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SOYMUTDB_")
    database_url: str = "postgresql+asyncpg://spoof:secret@localhost/db"
@lru_cache
def get_settings() -> Settings:
    return Settings()
"""
''',
            "rl_missing_fact:apps/api/app/core/config.py.rl_settings_source",
        ),
        (
            "apps/api/app/core/database.py",
            '''"""
settings = get_settings()
def get_engine():
    return create_async_engine(settings.database_url)
"""
''',
            "rl_missing_fact:apps/api/app/core/database.py.rl_settings_capture",
        ),
        (
            "apps/api/migrations/env.py",
            '''"""
config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
async def run_async_migrations():
    async_engine_from_config({}, prefix="sqlalchemy.")
"""
'''
            + "\nfrom app.core.config import get_settings\n"
            + "from app.core.database import Base\n"
            + "from app.models import *\n",
            "rl_missing_fact:apps/api/migrations/env.py.rl_config_role",
        ),
    ],
)
def test_rl_comments_docstrings_and_strings_cannot_satisfy_ast_contract_via_cli(
    tmp_path: rl_Path,
    rl_spoof_source: str,
    rl_spoof_content: str,
    rl_expected_fact: str,
) -> None:
    """Text that resembles wiring is not an observed structural fact."""

    rl_seed_project(tmp_path)
    (tmp_path / rl_spoof_source).write_text(rl_spoof_content, encoding="utf-8")

    rl_result, rl_report = rl_run_cli(tmp_path, "spoofed-python.json")
    rl_serialized = (tmp_path / "spoofed-python.json").read_text(encoding="utf-8")

    assert rl_result.returncode != 0
    assert rl_expected_fact in rl_blocking_ids(rl_report)
    assert "postgresql+asyncpg://spoof:secret@localhost/db" not in rl_serialized
    assert "spoof:secret" not in rl_serialized


def test_rl_alias_equivalent_python_wiring_remains_non_blocking(tmp_path: rl_Path) -> None:
    """Known direct import aliases are accepted without importing their modules."""

    rl_seed_project(tmp_path)
    (tmp_path / "apps/api/app/core/config.py").write_text(
        """
from functools import lru_cache as rl_cache
from pydantic_settings import BaseSettings as rl_BaseSettings
from pydantic_settings import SettingsConfigDict as rl_SettingsConfigDict

class Settings(rl_BaseSettings):
    model_config = rl_SettingsConfigDict(env_file=".env", env_prefix="SOYMUTDB_")
    database_url: str = "postgresql+asyncpg://soymutdb:unsafe-value@localhost:5432/soymutdb"

@rl_cache()
def get_settings() -> "Settings":
    return Settings()
""",
        encoding="utf-8",
    )
    (tmp_path / "apps/api/app/core/database.py").write_text(
        """
from .config import get_settings as rl_get_settings
from sqlalchemy.ext.asyncio import create_async_engine as rl_create_async_engine

settings = rl_get_settings()

def get_engine():
    return rl_create_async_engine(url=settings.database_url)
""",
        encoding="utf-8",
    )
    (tmp_path / "apps/api/migrations/env.py").write_text(
        """
from alembic import context as rl_context
from app.core.config import get_settings as rl_get_settings
from app.core.database import Base as rl_Base
from app.models import *
from sqlalchemy.ext.asyncio import async_engine_from_config as rl_async_engine_from_config

config = rl_context.config
settings = rl_get_settings()
config.set_main_option(name="sqlalchemy.url", value=settings.database_url)

async def run_async_migrations():
    connectable = rl_async_engine_from_config({}, configuration={})
""",
        encoding="utf-8",
    )

    rl_result, rl_report = rl_run_cli(tmp_path, "alias-equivalent.json")

    assert rl_result.returncode == 0
    assert rl_report["rl_blocking_facts"] == []


@rl_pytest.mark.parametrize(
    ("rl_database_source", "rl_expected_fact"),
    [
        (
            """
from app.core.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine

settings = get_settings()

def get_engine():
    return create_async_engine(configuration=settings.database_url)
""",
            "rl_missing_fact:apps/api/app/core/database.py.rl_engine_url",
        ),
        (
            """
from app.core.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine

get_settings = lambda: object()
settings = get_settings()

def get_engine():
    return create_async_engine(settings.database_url)
""",
            "rl_missing_fact:apps/api/app/core/database.py.rl_settings_capture",
        ),
        (
            """
from app.core.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine

settings = get_settings()

def get_engine():
    if False:
        return create_async_engine(settings.database_url)
""",
            "rl_missing_fact:apps/api/app/core/database.py.rl_async_engine",
        ),
    ],
)
def test_rl_database_ast_helper_matrix_rejects_spoofed_wiring(
    tmp_path: rl_Path, rl_database_source: str, rl_expected_fact: str
) -> None:
    """The constrained resolver rejects wrong keywords, shadowing, and dead code."""

    rl_seed_project(tmp_path)
    (tmp_path / "apps/api/app/core/database.py").write_text(rl_database_source, encoding="utf-8")

    rl_report = rl_collect_runtime_facts(tmp_path)

    assert rl_expected_fact in rl_blocking_ids(rl_report)


@rl_pytest.mark.parametrize(
    "rl_required_path",
    [
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "apps/worker/README.md",
        "apps/api/app/main.py",
        "apps/worker/src/soymutdb_worker/main.py",
        "infra/docker/Dockerfile.api",
        "infra/docker/Dockerfile.worker",
        "infra/docker/Dockerfile.web",
        "infra/docker/Dockerfile.admin",
        "apps/jbrowse/Dockerfile",
    ],
)
def test_rl_critical_runtime_inputs_missing_are_blocking(
    tmp_path: rl_Path, rl_required_path: str
) -> None:
    rl_seed_project(tmp_path)
    (tmp_path / rl_required_path).unlink()

    rl_report = rl_collect_runtime_facts(tmp_path)

    assert f"rl_missing_file:{rl_required_path}" in rl_blocking_ids(rl_report)


@rl_pytest.mark.parametrize(
    ("rl_invalid_path", "rl_invalid_content"),
    [
        ("README.md", ""),
        ("apps/worker/README.md", ""),
        ("docker-compose.yml", "services:\n  postgres:\n    image\n"),
        ("docker-compose.dev.yml", "services:\n  api:\n    image\n"),
        ("infra/docker/Dockerfile.api", "not a dockerfile\n"),
        ("infra/docker/Dockerfile.worker", "not a dockerfile\n"),
        ("infra/docker/Dockerfile.web", "not a dockerfile\n"),
        ("infra/docker/Dockerfile.admin", "not a dockerfile\n"),
        ("apps/jbrowse/Dockerfile", "not a dockerfile\n"),
        ("apps/api/app/main.py", "def broken(:\n"),
        ("apps/worker/src/soymutdb_worker/main.py", "def broken(:\n"),
    ],
)
def test_rl_critical_runtime_inputs_unparseable_are_blocking(
    tmp_path: rl_Path, rl_invalid_path: str, rl_invalid_content: str
) -> None:
    rl_seed_project(tmp_path)
    (tmp_path / rl_invalid_path).write_text(rl_invalid_content, encoding="utf-8")

    rl_report = rl_collect_runtime_facts(tmp_path)

    assert f"rl_parse:{rl_invalid_path}" in rl_blocking_ids(rl_report)


def test_rl_collection_is_deterministic_for_identical_static_tree(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)

    rl_first = rl_json.dumps(rl_collect_runtime_facts(tmp_path), ensure_ascii=False, sort_keys=True)
    rl_second = rl_json.dumps(
        rl_collect_runtime_facts(tmp_path), ensure_ascii=False, sort_keys=True
    )

    assert rl_first == rl_second


def test_rl_env_is_presence_only_and_sentinel_never_leaves_report(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)
    rl_sentinel = "RL_ENV_SENTINEL_DO_NOT_EMIT"
    (tmp_path / ".env").write_text(
        f"SOYMUTDB_JWT_SECRET={rl_sentinel}\n"
        "SOYMUTDB_DATABASE_URL=postgresql+asyncpg://user:password@db/secret\n",
        encoding="utf-8",
    )

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)
    rl_output = tmp_path / "env-output.json"
    assert rl_main(["--project-root", str(tmp_path), "--output", str(rl_output)]) == 0
    rl_output_serialized = rl_output.read_text(encoding="utf-8")

    assert rl_report["rl_facts"]["rl_config"]["rl_env_file"] == {
        "rl_path": ".env",
        "rl_declared": True,
        "rl_present": True,
        "rl_content_emitted": False,
    }
    assert rl_sentinel not in rl_serialized
    assert rl_sentinel not in rl_output_serialized
    assert "postgresql+asyncpg://user:password@db/secret" not in rl_serialized
    assert "postgresql+asyncpg://user:password@db/secret" not in rl_output_serialized


def test_rl_config_database_migration_and_ini_defaults_are_classified_and_redacted(
    tmp_path: rl_Path,
) -> None:
    rl_seed_project(tmp_path)

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)
    rl_config_facts = rl_report["rl_facts"]["rl_config"]

    assert rl_config_facts["rl_env_prefix"] == "SOYMUTDB_"
    assert rl_config_facts["rl_lru_cache"] is True
    assert "jwt_secret" in rl_config_facts["rl_secret_default_fields"]
    assert "admin_password" in rl_config_facts["rl_secret_default_fields"]
    assert rl_report["rl_facts"]["rl_database"]["rl_settings_capture_scope"] == "module"
    assert rl_report["rl_facts"]["rl_migrations_env"]["rl_settings_override"] is True
    assert rl_report["rl_facts"]["rl_alembic"]["rl_script_location"]["rl_is_relative"] is True
    assert "unsafe-value" not in rl_serialized


def test_rl_cli_writes_complete_report_then_returns_nonzero_for_blocking_input(
    tmp_path: rl_Path,
) -> None:
    rl_seed_project(tmp_path)
    (tmp_path / "apps/api/app/main.py").unlink()
    rl_output = tmp_path / "nested" / "runtime-facts.json"

    rl_result = rl_subprocess.run(
        [
            rl_sys.executable,
            "-m",
            "tools.a0.rl_collect_runtime_facts",
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
        ],
        cwd=rl_Path(__file__).resolve().parents[4],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert rl_result.returncode != 0
    assert rl_output.exists()
    rl_report = rl_json.loads(rl_output.read_text(encoding="utf-8"))
    assert "rl_missing_file:apps/api/app/main.py" in rl_blocking_ids(rl_report)


def test_rl_cli_invalid_command_spec_is_blocking_and_safe(tmp_path: rl_Path) -> None:
    rl_seed_project(tmp_path)
    rl_output = tmp_path / "invalid-command.json"

    rl_returncode = rl_main(
        [
            "--project-root",
            str(tmp_path),
            "--output",
            str(rl_output),
            "--command-version",
            "invalid-spec",
        ]
    )

    assert rl_returncode != 0
    rl_report = rl_json.loads(rl_output.read_text(encoding="utf-8"))
    assert "rl_command_invalid:invalid-spec" in rl_blocking_ids(rl_report)


@rl_pytest.mark.parametrize(
    ("rl_runner_mode", "rl_fact_id"),
    [
        ("unavailable", "rl_command_unavailable:rl_fake"),
        ("failed", "rl_command_failed:rl_fake"),
        ("no-version", "rl_command_no_version:rl_fake"),
    ],
)
def test_rl_command_failures_are_blocking_with_injected_runner(
    tmp_path: rl_Path,
    rl_runner_mode: str,
    rl_fact_id: str,
) -> None:
    rl_seed_project(tmp_path)

    def rl_fake_runner(*rl_args, **rl_kwargs):
        assert rl_kwargs["shell"] is False
        assert rl_kwargs["cwd"] == str(tmp_path)
        if rl_runner_mode == "unavailable":
            raise FileNotFoundError("fake command unavailable")
        if rl_runner_mode == "failed":
            return rl_types.SimpleNamespace(returncode=3, stdout="", stderr="failed")
        return rl_types.SimpleNamespace(returncode=0, stdout="no version here", stderr="")

    rl_report = rl_collect_runtime_facts(
        tmp_path,
        {"rl_fake": ("fake-command", "--version")},
        rl_command_runner=rl_fake_runner,
    )

    assert rl_fact_id in rl_blocking_ids(rl_report)


def test_rl_collection_does_not_import_app_or_change_process_state(
    tmp_path: rl_Path, monkeypatch
) -> None:
    rl_seed_project(tmp_path)
    rl_original_import = rl_builtins.__import__
    rl_original_path = list(rl_sys.path)
    rl_original_environment = dict(rl_os.environ)

    def rl_guarded_import(rl_name, *rl_args, **rl_kwargs):
        if rl_name == "app" or rl_name.startswith(("app.", "sqlalchemy", "alembic")):
            raise AssertionError(f"unexpected application import: {rl_name}")
        return rl_original_import(rl_name, *rl_args, **rl_kwargs)

    monkeypatch.setattr(rl_builtins, "__import__", rl_guarded_import)
    rl_report = rl_collect_runtime_facts(tmp_path)

    assert rl_report["rl_application_imports_attempted"] is False
    assert rl_report["rl_database_connections_attempted"] is False
    assert rl_sys.path == rl_original_path
    assert dict(rl_os.environ) == rl_original_environment


def test_rl_report_has_source_provenance_roles_and_blocked_runtime_status(
    tmp_path: rl_Path,
) -> None:
    """Every attempted source has stable provenance without absolute paths/content."""

    rl_seed_project(tmp_path)
    (tmp_path / "apps/api/app/main.py").unlink()

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_provenance = rl_report["rl_source_provenance"]
    rl_paths = [rl_item["rl_path"] for rl_item in rl_provenance]

    assert rl_paths == sorted(rl_paths)
    assert all(not rl_Path(rl_path).is_absolute() for rl_path in rl_paths)
    for rl_item in rl_provenance:
        if rl_item["rl_status"] == "read":
            assert rl_re.fullmatch(r"sha256:[0-9a-f]{64}", rl_item["rl_digest"])
        else:
            assert "rl_digest" not in rl_item
    rl_readme_provenance = next(
        rl_item for rl_item in rl_provenance if rl_item["rl_path"] == "README.md"
    )
    assert rl_readme_provenance["rl_status"] == "read"
    assert rl_readme_provenance["rl_digest"] == (
        "sha256:" + rl_hashlib.sha256((tmp_path / "README.md").read_bytes()).hexdigest()
    )
    rl_missing_provenance = next(
        rl_item for rl_item in rl_provenance if rl_item["rl_path"] == "apps/api/app/main.py"
    )
    assert rl_missing_provenance["rl_status"] == "missing"
    assert "rl_digest" not in rl_missing_provenance

    assert rl_report["rl_producer"] == "rl_collect_runtime_facts"
    assert rl_report["rl_owner"] == "rl_runtime_evidence_owner"
    assert rl_report["rl_reviewer"] == "rl_runtime_reviewer"
    assert rl_report["rl_runtime_evidence_status"] == "BLOCKED"
    assert "rl_report_digest" not in rl_report


@rl_pytest.mark.parametrize("rl_unavailable_status", ["missing", "not_file", "unreadable"])
def test_rl_unavailable_source_provenance_has_no_digest(rl_unavailable_status: str) -> None:
    rl_record = rl_collector_module.rl_source_provenance_record(
        "apps/api/app/main.py",
        rl_unavailable_status,
        "source text that must not be retained",
        b"source bytes that must not be retained",
    )

    assert rl_record["rl_status"] == rl_unavailable_status
    assert "rl_digest" not in rl_record


def test_rl_read_source_provenance_uses_original_bytes_and_strict_digest() -> None:
    rl_raw_bytes = b"\xffraw source bytes\x00"
    rl_record = rl_collector_module.rl_source_provenance_record(
        "README.md",
        "read",
        rl_bytes=rl_raw_bytes,
    )

    assert rl_re.fullmatch(r"sha256:[0-9a-f]{64}", rl_record["rl_digest"])
    assert rl_record["rl_digest"] == ("sha256:" + rl_hashlib.sha256(rl_raw_bytes).hexdigest())
    assert "raw source bytes" not in rl_json.dumps(rl_record, ensure_ascii=False)


def test_rl_read_source_provenance_without_content_fails_closed() -> None:
    with rl_pytest.raises(ValueError, match="read provenance requires source content"):
        rl_collector_module.rl_source_provenance_record(
            "README.md",
            "read",
        )


@rl_pytest.mark.parametrize(
    "rl_safe_input",
    ["README.md", "apps/api/app/main.py", "."],
)
def test_rl_safe_path_preserves_normal_project_relative_paths(rl_safe_input: str) -> None:
    assert rl_collector_module.rl_safe_path(rl_safe_input) == rl_safe_input


@rl_pytest.mark.parametrize(
    "rl_unsafe_input",
    [
        "../outside",
        "foo/../../outside",
        r"C:\tmp\x",
        "C:/tmp/x",
        r"\\server\share",
        "\x00source",
        "line\nsource",
    ],
)
def test_rl_safe_path_rejects_unsafe_relative_metadata(rl_unsafe_input: str) -> None:
    assert rl_collector_module.rl_safe_path(rl_unsafe_input) == "<unsafe-relative-path>"


def test_rl_safe_path_keeps_existing_absolute_path_placeholder() -> None:
    assert rl_collector_module.rl_safe_path("/tmp/outside") == "<absolute-path>"


def test_rl_source_allowlist_redacts_before_report_sanitization() -> None:
    rl_raw_source = "../outside/rl-source-secret"
    rl_emitted = rl_collector_module.rl_emit_source_value(rl_raw_source, "relative_path")

    assert isinstance(rl_emitted, dict)
    assert rl_emitted["rl_classification"] == "redacted_source_value"
    assert "rl_value" not in rl_emitted
    assert rl_emitted["rl_digest"] == (
        "sha256:" + rl_hashlib.sha256(rl_raw_source.encode("utf-8")).hexdigest()
    )
    assert rl_raw_source not in rl_json.dumps(rl_emitted, ensure_ascii=False)
    assert rl_collector_module.rl_sanitize_report(rl_emitted) == rl_emitted

    rl_safe_source = rl_collector_module.rl_emit_source_value(
        "infra/docker/Dockerfile.api", "relative_path"
    )
    assert rl_safe_source == "infra/docker/Dockerfile.api"
    rl_safe_source_record = rl_collector_module.rl_safe_source_value(
        "infra/docker/Dockerfile.api", "relative_path"
    )
    assert rl_safe_source_record == {
        "rl_classification": "observed",
        "rl_value": "infra/docker/Dockerfile.api",
    }


def test_rl_redaction_blocks_basic_no_scheme_image_and_secret_key_shapes(
    tmp_path: rl_Path,
) -> None:
    """Credential-shaped source-derived values never leave the static report."""

    rl_seed_project(tmp_path)
    (tmp_path / "docker-compose.yml").write_text(
        """services:
  postgres:
    image: private-user:private-password@registry.example/private/db:latest
  api:
    environment:
      CLIENT_SECRET: client-secret-value
""",
        encoding="utf-8",
    )

    rl_report = rl_collect_runtime_facts(tmp_path)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)
    rl_redacted = rl_collector_module.rl_redact_text(
        "Authorization: Basic dXNlcjpwYXNz client_secret=secret-value api-key: dash-secret"
    )

    assert "private-password" not in rl_serialized
    assert "client-secret-value" not in rl_serialized
    assert "secret-value" not in rl_redacted
    assert "dash-secret" not in rl_redacted
    assert "dXNlcjpwYXNz" not in rl_redacted
    assert rl_report["rl_facts"]["rl_compose"]["rl_postgresql_image"] != (
        "private-user:private-password@registry.example/private/db:latest"
    )

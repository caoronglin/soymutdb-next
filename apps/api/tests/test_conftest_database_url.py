"""Unit tests for selecting the API test PostgreSQL backend."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


CONFTEST_PATH = Path(__file__).parent / "conftest.py"


def _load_conftest_module():
    spec = importlib.util.spec_from_file_location("test_conftest_database_url", CONFTEST_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_test_database_url_bypasses_testcontainers(monkeypatch) -> None:
    module = _load_conftest_module()
    url = "postgresql+asyncpg://tester:password@127.0.0.1:5432/soymutdb_test"
    monkeypatch.setenv("SOYMUTDB_TEST_DATABASE_URL", url)
    monkeypatch.setattr(module, "HAS_TESTCONTAINERS", False)

    fixture = module.postgres_container.__wrapped__()
    assert next(fixture) == url
    with pytest.raises(StopIteration):
        next(fixture)


def test_explicit_test_database_url_requires_asyncpg_scheme(monkeypatch) -> None:
    module = _load_conftest_module()
    monkeypatch.setenv("SOYMUTDB_TEST_DATABASE_URL", "postgresql://localhost/soymutdb_test")

    with pytest.raises(pytest.UsageError, match=r"postgresql\+asyncpg"):
        next(module.postgres_container.__wrapped__())

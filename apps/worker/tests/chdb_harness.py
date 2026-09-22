"""Shared helpers for real embedded-ClickHouse (chdb) acceptance tests.

chdb's embedded engine binds to a single on-disk path for the life of the Python
process, so every acceptance test reuses one engine session and isolates its
tables with a unique per-test database (``CREATE DATABASE ... ; USE ...``). The
pytest fixture that opens the engine lives in ``conftest.py`` (lazily importing
chdb) so tests that do not touch ClickHouse never require the engine.
"""

from __future__ import annotations

import os
import tempfile
import uuid

_SESSION_PATH: str | None = None


def session_path() -> str:
    global _SESSION_PATH
    if _SESSION_PATH is None:
        _SESSION_PATH = os.path.join(tempfile.mkdtemp(prefix="chdb-accept-"), "engine")
    return _SESSION_PATH


def unique_db() -> str:
    return "d_" + uuid.uuid4().hex[:12]


def prepare_schema(engine, database: str, ddl: list[str]) -> str:
    """Create + switch to a fresh database and apply ``ddl`` into it.

    All model statements use unqualified table names, so switching the session
    current database scopes every subsequent call to this test's database.
    """
    engine.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    engine.execute(f"USE {database}")
    for statement in ddl:
        engine.execute(statement)
    return database

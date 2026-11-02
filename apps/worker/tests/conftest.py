"""Pytest fixtures for the worker suite.

The embedded-ClickHouse engine fixture is intentionally lazy: it imports chdb
only when a chdb acceptance test runs, so the rest of the worker suite does not
require the engine to be installed. The isolated Python 3.14 legacy migration
gate provisions chdb separately from the native Worker development environment.
"""

from __future__ import annotations

import os
import sys

import pytest

from tests.test_chdb_harness import session_path

LEGACY_ENGINE_MODULES = [
    "test_clickhouse_engine.py",
    "test_clickhouse_production_ddl.py",
    "test_variant_finalize.py",
    "test_legacy_clickhouse_migration.py",
    "test_vcf_import.py",
]

# chdb's abi3 wheel bundles non-limited Python shims only through 3.14.
# These historical engine contracts run in the mandatory 3.14 migration lane.
if os.environ.get("SOYMUTDB_RUN_LEGACY_CHDB_TESTS") == "1":
    if sys.version_info[:2] != (3, 14):
        raise pytest.UsageError("legacy chdb acceptance requires Python 3.14")
    collect_ignore = []
else:
    collect_ignore = LEGACY_ENGINE_MODULES


@pytest.fixture(scope="session")
def ch_engine():
    from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine

    return ChdbEngine.open(session_path())

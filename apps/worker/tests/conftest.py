"""Pytest fixtures for the worker suite.

The embedded-ClickHouse engine fixture is intentionally lazy: it imports chdb
only when a chdb acceptance test runs, so the rest of the worker suite does not
require the engine to be installed. chdb is a worker dev extra
(``apps/worker[dev]``) that the backend gate installs.
"""

from __future__ import annotations

import pytest

from tests.chdb_harness import session_path


@pytest.fixture(scope="session")
def ch_engine():
    from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine

    return ChdbEngine.open(session_path())

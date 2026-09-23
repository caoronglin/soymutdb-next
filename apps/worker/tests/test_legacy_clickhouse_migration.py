"""Real-engine acceptance for the legacy ClickHouse migration path.

The CI clickhouse-migration job runs this SQL against a
``clickhouse/clickhouse-server:24.8`` container over HTTP. This suite runs the
same legacy fixture and upgrade SQL through chdb's embedded engine so the
migration executor and the canonical summary DDL are also exercised on the
newer engine pinned by the worker dev extra (chdb 4.4.0 / ClickHouse 26.7).

That is where the ``chromosome_summary.cnt`` drift surfaced: the migration SQL
declared a plain ``UInt64`` inside an ``AggregatingMergeTree`` while
``init.sql`` declared ``SimpleAggregateFunction(sum, UInt64)``. ClickHouse 26.7
rejects the drifted table outright:

    Code: 36. DB::Exception: Column(s) cnt of the AggregatingMergeTree table
    are neither part of the sorting key nor aggregate measures (BAD_ARGUMENTS)

and on older servers the MV merge would keep an arbitrary partial count instead
of summing, i.e. silently wrong summaries. Requires the worker dev extra
(``chdb``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

# The acceptance engine lives in the worker dev extra (apps/worker[dev]) which
# the backend gate installs; a missing engine means the migration contract is
# UNVERIFIED, so fail loudly instead of silently skipping.
import chdb.session  # noqa: F401
import pytest

from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine  # noqa: E402
from tests.test_chdb_harness import unique_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MIGRATION_LIB = ROOT / "deploy/scripts/migrate_clickhouse_lib.py"
LEGACY_FIXTURE = ROOT / "infra/clickhouse/fixture_legacy.sql"
MIGRATION_SQL = ROOT / "infra/clickhouse/upgrade_variant_facts_schema.sql"
EXPECTED_FIXTURE_ROWS = 3


def _migration_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_clickhouse_lib", MIGRATION_LIB)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ConnectClient:
    """clickhouse-connect-compatible facade over the chdb engine port.

    ``migrate_clickhouse_lib`` only uses ``command(sql)`` and
    ``query(sql).result_rows``, so this tiny adapter lets the production
    executor run unmodified against a real embedded engine.
    """

    def __init__(self, engine: ChdbEngine) -> None:
        self.engine = engine

    def command(self, sql: str) -> object:
        return self.engine.execute(sql)

    def query(self, sql: str) -> object:
        return type("Result", (), {"result_rows": self.engine.query_rows(sql)})()


@pytest.fixture()
def client(ch_engine: ChdbEngine) -> _ConnectClient:
    database = unique_db()
    ch_engine.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    ch_engine.execute(f"USE {database}")
    return _ConnectClient(ch_engine)


def test_legacy_fixture_migrates_and_reruns_idempotently(
    ch_engine: ChdbEngine, client: _ConnectClient
) -> None:
    lib = _migration_lib()
    for statement in lib._split_statements(LEGACY_FIXTURE.read_text(encoding="utf-8")):
        if statement.strip():
            ch_engine.execute(statement)

    assert lib.detect_state(client) == "S0"
    result = lib.run_migration(client, MIGRATION_SQL.read_text(encoding="utf-8"), 0.05)
    assert result["state"] == "S0"
    assert result["gate"] == (3, 3, 0, 0)
    assert lib.check_completion(client) == []
    assert (
        ch_engine.query_rows("SELECT count() FROM variant_facts")[0][0]
        == EXPECTED_FIXTURE_ROWS
    )

    def summary_rows() -> int:
        unions = " UNION ALL ".join(
            f"SELECT count() AS x FROM {table}" for table in lib.SUMMARY_TABLES
        )
        return ch_engine.query_rows(f"SELECT sum(x) FROM ({unions})")[0][0]

    before = summary_rows()
    # A re-run on the canonical base takes the S2 recovery path: the base rename
    # is skipped and the summaries are rebuilt from variant_facts. That must not
    # change the summary cardinality (the CI job asserts the same property).
    second = lib.run_migration(client, MIGRATION_SQL.read_text(encoding="utf-8"), 0.05)
    assert second["state"] == "S2"
    assert lib.check_completion(client) == []
    assert summary_rows() == before
    assert (
        ch_engine.query_rows("SELECT count() FROM variant_facts")[0][0]
        == EXPECTED_FIXTURE_ROWS
    )

"""Real-engine acceptance for the import engine port + finalize contract.

These run against chdb's embedded ClickHouse — a real single-node engine — so
the MergeTree/SummingMergeTree/MV behaviour the finalize protocol depends on is
genuinely exercised, not mocked. Requires the worker dev extra (``chdb``).
"""

from __future__ import annotations

# The acceptance engine lives in the worker dev extra (apps/worker[dev]) which
# the backend gate installs; a missing engine means the finalize contract is
# UNVERIFIED, so fail loudly instead of silently skipping.
import chdb.session  # noqa: F401
import pytest

from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine  # noqa: E402
from tests.test_chdb_harness import prepare_schema, unique_db  # noqa: E402

# A faithful, minimal slice of the canonical DDL: the fact table with the real
# (release_key, chromosome) partition key, one SummingMergeTree summary and the
# MV that feeds it. This is enough to prove the double-count + finalize
# semantics the protocol must handle (the full DDL is the CH-migration job).
DDL = [
    """CREATE TABLE variant_facts (
        variant_id UInt64, release_key String, chromosome LowCardinality(String),
        position UInt64, gene_surrogate_id UInt32
    ) ENGINE=MergeTree()
    PARTITION BY (release_key, chromosome)
    ORDER BY (release_key, chromosome, position, variant_id)""",
    """CREATE TABLE variant_facts_staging (
        variant_id UInt64, release_key String, chromosome LowCardinality(String),
        position UInt64, gene_surrogate_id UInt32, import_id String, batch_index UInt32
    ) ENGINE=MergeTree()
    PARTITION BY (release_key, chromosome)
    ORDER BY (release_key, chromosome, position, variant_id)""",
    """CREATE TABLE gene_impact_summary (
        gene_surrogate_id UInt32, release_key String, cnt UInt64
    ) ENGINE=SummingMergeTree(cnt)
    ORDER BY (gene_surrogate_id, release_key)""",
    """CREATE MATERIALIZED VIEW mv_gene_impact TO gene_impact_summary AS
    SELECT gene_surrogate_id, release_key, count() AS cnt
    FROM variant_facts GROUP BY gene_surrogate_id, release_key""",
]

SUMMARY_COLS = ["gene_surrogate_id", "release_key", "cnt"]
BASE_COLS = [
    "variant_id",
    "release_key",
    "chromosome",
    "position",
    "gene_surrogate_id",
]
STAGING_COLS = [*BASE_COLS, "import_id", "batch_index"]


@pytest.fixture()
def engine(ch_engine: ChdbEngine) -> ChdbEngine:
    prepare_schema(ch_engine, unique_db(), DDL)
    return ch_engine


def _finalize(clickhouse: ChdbEngine, release_key: str, chromosome: str, rows: list[tuple]) -> None:
    """Partition-scoped finalize: purge dependent summaries, drop base partition,
    then rewrite the release's partition from the verified rows.

    Ordering matters (H2): the release-scoped summary rows must be purged before
    the base partition is dropped and rewritten, or the MV will re-fire on top of
    stale counts.
    """
    clickhouse.execute(
        f"ALTER TABLE gene_impact_summary DELETE WHERE release_key = '{release_key}'"
    )
    clickhouse.execute(f"ALTER TABLE variant_facts DROP PARTITION ('{release_key}','{chromosome}')")
    clickhouse.insert_rows("variant_facts", rows, BASE_COLS)


def test_staging_writes_are_invisible_to_summaries(engine: ChdbEngine) -> None:
    engine.insert_rows(
        "variant_facts_staging",
        [
            (1, "R1", "Chr01", 100, 7, "imp-abc", 0),
            (2, "R1", "Chr01", 200, 8, "imp-abc", 0),
        ],
        STAGING_COLS,
    )
    # Staging has no materialized view, so a summary fed only by variant_facts
    # must remain empty: partial writes never reach analytical projections (H2).
    assert engine.scalar("SELECT count() FROM gene_impact_summary") == 0
    assert engine.scalar("SELECT count() FROM variant_facts_staging") == 2


def test_duplicate_fact_insert_double_counts_the_summary(engine: ChdbEngine) -> None:
    # The hazard ADR-0005 exists to prevent, reproduced on the real engine.
    engine.insert_rows("variant_facts", [(1, "R1", "Chr01", 100, 7)], BASE_COLS)
    engine.insert_rows("variant_facts", [(2, "R1", "Chr01", 200, 7)], BASE_COLS)
    engine.insert_rows("variant_facts", [(1, "R1", "Chr01", 100, 7)], BASE_COLS)  # retry dup
    summary = engine.scalar(
        "SELECT cnt FROM gene_impact_summary FINAL "
        "WHERE gene_surrogate_id = 7 AND release_key = 'R1'"
    )
    assert summary == 3  # two distinct facts + one duplicate, all summed
    assert engine.scalar("SELECT count() FROM variant_facts") == 3


def test_finalize_repairs_double_count_and_is_idempotent(engine: ChdbEngine) -> None:
    verified = [
        (1, "R1", "Chr01", 100, 7),
        (2, "R1", "Chr01", 200, 7),
    ]
    # Pollute with a bad retry first.
    engine.insert_rows("variant_facts", verified, BASE_COLS)
    engine.insert_rows("variant_facts", verified, BASE_COLS)  # accidental full re-insert

    _finalize(engine, "R1", "Chr01", verified)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2
    assert engine.scalar(
        "SELECT cnt FROM gene_impact_summary FINAL "
        "WHERE gene_surrogate_id = 7 AND release_key = 'R1'"
    ) == 2

    # Finalize again over the same partition: must be idempotent, not additive.
    _finalize(engine, "R1", "Chr01", verified)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2
    assert engine.scalar(
        "SELECT cnt FROM gene_impact_summary FINAL "
        "WHERE gene_surrogate_id = 7 AND release_key = 'R1'"
    ) == 2


def test_finalize_only_touches_its_own_release_partition(engine: ChdbEngine) -> None:
    engine.insert_rows("variant_facts", [(1, "OTHER", "Chr01", 100, 9)], BASE_COLS)
    engine.insert_rows("variant_facts", [(1, "R1", "Chr01", 100, 7)], BASE_COLS)
    _finalize(engine, "R1", "Chr01", [(1, "R1", "Chr01", 100, 7)])
    # The unrelated release survives untouched.
    assert engine.scalar("SELECT count() FROM variant_facts WHERE release_key = 'OTHER'") == 1
    assert engine.scalar(
        "SELECT cnt FROM gene_impact_summary FINAL WHERE gene_surrogate_id = 9"
    ) == 1


class _FakeClient:
    """Stands in for clickhouse-connect to assert the HTTP adapter maps calls."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.inserts: list[tuple] = []

    def command(self, sql: str, parameters=None):  # noqa: D401
        self.commands.append(sql)
        self._command_params = parameters
        return None

    def insert(self, table, data, column_names):  # noqa: D401
        self.inserts.append((table, list(data), list(column_names)))

    def query(self, sql, parameters=None):  # noqa: D401
        self._params = parameters
        self._sql = sql

        class _R:
            result_rows = [(42,)]

        return _R()


def test_http_engine_adapter_maps_the_port() -> None:
    from soymutdb_worker.tasks.clickhouse_engine import HttpClickHouseEngine

    client = _FakeClient()
    engine = HttpClickHouseEngine(client)
    engine.execute(
        "ALTER TABLE t DROP PARTITION ({rk:String})", params={"rk": "R1"}
    )
    engine.insert_rows("t", [(1, "a"), (2, "b")], ["id", "k"])
    assert engine.scalar("SELECT count() FROM t", {"x": "y"}) == 42
    assert client.commands == ["ALTER TABLE t DROP PARTITION ({rk:String})"]
    # The adapter forwards bound parameters instead of interpolating values.
    assert client._command_params == {"rk": "R1"}
    assert client.inserts == [("t", [(1, "a"), (2, "b")], ["id", "k"])]
    assert client._params == {"x": "y"}

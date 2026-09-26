"""Real-engine acceptance for the PRODUCTION ClickHouse DDL (empty database).

The other acceptance suites load a faithful *fixture* slice of the schema. This
one loads the canonical ``infra/clickhouse/init.sql`` itself into an empty
embedded ClickHouse (chdb), then drives the import staging -> verify -> finalize
protocol against it. It is the "empty database" half of the audit's §6 evidence
(the legacy -> canonical upgrade path is covered by
``test_legacy_clickhouse_migration``).

Why it matters: ``variant_facts_staging`` used to exist only in the test
fixture, so a fixture-green suite could still fail on a real engine whose DDL
never created the staging table. Loading the production SQL here closes that
gap and keeps the two from drifting.

Requires the worker dev extra (``chdb``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import chdb.session  # noqa: F401  (hard dep: acceptance engine lives in worker[dev])
import pytest

from soymutdb_worker.tasks import variant_finalize as vf
from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine

ROOT = Path(__file__).resolve().parents[3]
INIT_SQL = ROOT / "infra/clickhouse/init.sql"
MIGRATION_LIB = ROOT / "deploy/scripts/migrate_clickhouse_lib.py"
PRODUCTION_DB = "soymutdb"


def _migration_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_clickhouse_lib", MIGRATION_LIB)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(
    variant_id: int,
    release: str,
    chromosome: str,
    position: int,
    *,
    assembly: str = "v5",
    gene_sid: int = 7,
) -> tuple:
    """One canonical ``variant_facts`` row in BASE_COLUMNS order."""
    return (
        variant_id, release, assembly, chromosome, position, "A", "G", "SNP", "",
        1, f"gene{gene_sid}", f"g{gene_sid}", gene_sid, 0,
        "", "missense_variant", 0, "MODERATE", "", 0.0, "PASS", 0, 0.0, "", "", "unknown",
    )


@pytest.fixture()
def production_engine(ch_engine: ChdbEngine) -> ChdbEngine:
    """Load the canonical init.sql into a freshly dropped database."""
    lib = _migration_lib()
    ch_engine.execute(f"DROP DATABASE IF EXISTS {PRODUCTION_DB}")
    for statement in lib._split_statements(INIT_SQL.read_text(encoding="utf-8")):
        if statement.strip():
            ch_engine.execute(statement)
    return ch_engine


def _summary_cnt(engine: ChdbEngine, release: str, gene: int = 7) -> int:
    return int(
        engine.scalar(
            f"SELECT cnt FROM gene_impact_summary FINAL "
            f"WHERE gene_surrogate_id = {gene} AND release_key = '{release}'"
        )
        or 0
    )


def test_production_init_ddl_declares_the_staging_table(production_engine: ChdbEngine) -> None:
    """The canonical DDL must create variant_facts_staging (P1-03)."""
    columns = {
        str(row[0])
        for row in production_engine.query_rows(
            "SELECT name FROM system.columns "
            f"WHERE database = '{PRODUCTION_DB}' AND table = 'variant_facts_staging'"
        )
    }
    assert {"variant_id", "release_key", "assembly_key", "import_id", "batch_id"} <= columns


def test_production_init_ddl_accepts_the_import_protocol(production_engine: ChdbEngine) -> None:
    """stage -> verify -> finalize publishes exactly once on the real DDL."""
    engine = production_engine
    import_id = "prod-init"
    rows = [
        _row(1, "R-INIT", "Chr01", 100),
        _row(2, "R-INIT", "Chr01", 200),
        _row(3, "R-INIT", "Chr02", 300),
    ]

    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)
    assert int(engine.scalar("SELECT count() FROM variant_facts")) == 0
    assert vf.staged_distinct_count(engine, import_id) == 3
    assert vf.verify_against_expected(engine, import_id, expected_rows=3) is True

    partitions = vf.list_partitions(engine, import_id)
    assert partitions == [("R-INIT", "Chr01"), ("R-INIT", "Chr02")]
    vf.finalize_release(engine, release_key="R-INIT", import_id=import_id, partitions=partitions)

    assert int(engine.scalar("SELECT count() FROM variant_facts WHERE release_key = 'R-INIT'")) == 3
    assert _summary_cnt(engine, "R-INIT") == 3

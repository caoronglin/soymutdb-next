"""End-to-end finalize-protocol acceptance on a real embedded ClickHouse (P2-3).

Loads a faithful slice of the canonical schema (``variant_facts`` + all eight
release-scoped summary tables + their materialized views + the staging table)
from ``fixtures/variant_facts_schema.sql`` into chdb and drives staging ->
rewrite-on-retry -> finalize through ``soymutdb_worker.tasks.variant_finalize``,
asserting no duplicate facts and no double-counted summaries after retries.
"""

from __future__ import annotations

from pathlib import Path

import chdb.session  # noqa: F401  (hard dep: acceptance engine lives in worker[dev])
import pytest

from soymutdb_worker.tasks import variant_finalize as vf
from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine
from tests.chdb_harness import prepare_schema, unique_db

_SCHEMA_SQL = (
    Path(__file__).parent / "fixtures" / "variant_facts_schema.sql"
).read_text(encoding="utf-8")
_STATEMENTS = [stmt.strip() for stmt in _SCHEMA_SQL.split(";") if stmt.strip()]


@pytest.fixture()
def engine(ch_engine: ChdbEngine) -> ChdbEngine:
    prepare_schema(ch_engine, unique_db(), _STATEMENTS)
    return ch_engine


def _base_row(
    variant_id: int,
    release: str,
    chromosome: str,
    position: int,
    *,
    gene_sid: int = 7,
    mutant_sid: int = 0,
    ref: str = "A",
    alt: str = "G",
    variant_type: str = "SNP",
    impact: str = "MODERATE",
    consequence: str = "missense_variant",
) -> tuple:
    return (
        variant_id, release, "v5", chromosome, position, ref, alt, variant_type, "",
        max(len(ref), len(alt)), f"gene{gene_sid}", f"g{gene_sid}", gene_sid, mutant_sid,
        "", consequence, 0, impact, "", 0.0, "PASS", 0, 0.0, "", "", "unknown",
    )


def _summary_cnt(engine: ChdbEngine, release: str, gene: int = 7) -> int:
    return int(
        engine.scalar(
            f"SELECT cnt FROM gene_impact_summary FINAL "
            f"WHERE gene_surrogate_id = {gene} AND release_key = '{release}'"
        )
        or 0
    )


def test_stage_then_finalize_publishes_exactly_once(engine: ChdbEngine) -> None:
    import_id = "imp-A"
    rows = [
        _base_row(1, "R1", "Chr01", 100),
        _base_row(2, "R1", "Chr01", 200),
        _base_row(3, "R1", "Chr02", 300),
    ]
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)

    # Nothing reaches the base or summaries before finalize.
    assert engine.scalar("SELECT count() FROM variant_facts") == 0
    assert _summary_cnt(engine, "R1") == 0
    assert vf.staged_distinct_count(engine, import_id) == 3

    partitions = vf.list_partitions(engine, import_id)
    assert partitions == [("R1", "Chr01"), ("R1", "Chr02")]
    vf.finalize_release(engine, release_key="R1", import_id=import_id, partitions=partitions)

    # All three facts publish and the summary counts each once (multi-partition).
    assert engine.scalar("SELECT count() FROM variant_facts") == 3
    assert _summary_cnt(engine, "R1") == 3


def test_retry_after_crash_is_idempotent(engine: ChdbEngine) -> None:
    import_id = "imp-B"
    rows = [_base_row(1, "R2", "Chr01", 100), _base_row(2, "R2", "Chr01", 200)]

    # Crash mid-write: a partial staging attempt, then a full retry that clears
    # and rewrites staging before finalizing.
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows[:1])
    vf.clear_staging(engine, import_id)
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)

    partitions = vf.list_partitions(engine, import_id)
    vf.finalize_release(engine, release_key="R2", import_id=import_id, partitions=partitions)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2
    assert _summary_cnt(engine, "R2") == 2

    # A blind re-publish of the same partition must not double the counts.
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)
    partitions = vf.list_partitions(engine, import_id)
    vf.finalize_release(engine, release_key="R2", import_id=import_id, partitions=partitions)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2
    assert _summary_cnt(engine, "R2") == 2


def test_other_release_partition_is_preserved(engine: ChdbEngine) -> None:
    engine.insert_rows(
        "variant_facts",
        [_base_row(1, "OTHER", "Chr01", 500, gene_sid=9)],
        list(vf.BASE_COLUMNS),
    )
    before = engine.scalar("SELECT count() FROM variant_facts WHERE release_key = 'OTHER'")

    import_id = "imp-C"
    vf.stage_batch(
        engine, import_id=import_id, batch_index=0, base_rows=[_base_row(1, "NEW", "Chr01", 100)]
    )
    vf.finalize_release(
        engine, release_key="NEW", import_id=import_id, partitions=[("NEW", "Chr01")]
    )

    assert engine.scalar("SELECT count() FROM variant_facts WHERE release_key = 'OTHER'") == before


def test_deterministic_batch_id_is_stable() -> None:
    assert vf.deterministic_batch_id("imp", 0) == vf.deterministic_batch_id("imp", 0)
    assert vf.deterministic_batch_id("imp", 0) != vf.deterministic_batch_id("imp", 1)

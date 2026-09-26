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
from tests.test_chdb_harness import prepare_schema, unique_db

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
    assembly: str = "v5",
) -> tuple:
    return (
        variant_id, release, assembly, chromosome, position, ref, alt, variant_type, "",
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


def test_single_assembly_import_preserves_other_assembly_on_shared_chromosome(
    engine: ChdbEngine,
) -> None:
    """P1-01: re-importing v4 Chr01 must not delete v5's Chr01 rows.

    The physical partition is (release, chromosome), so v4 and v5 rows for the
    same chromosome share a partition and a partition drop removes both.
    """
    engine.insert_rows(
        "variant_facts",
        [
            _base_row(10, "R-ASM", "Chr01", 100, assembly="v4", gene_sid=4),
            _base_row(20, "R-ASM", "Chr01", 100, assembly="v5", gene_sid=5),
        ],
        list(vf.BASE_COLUMNS),
    )

    import_id = "imp-asm"
    vf.stage_batch(
        engine,
        import_id=import_id,
        batch_index=0,
        base_rows=[_base_row(11, "R-ASM", "Chr01", 100, assembly="v4", gene_sid=4)],
    )
    partitions = vf.list_partitions(engine, import_id)
    vf.finalize_release(
        engine, release_key="R-ASM", import_id=import_id, partitions=partitions
    )

    v4_count = engine.scalar(
        "SELECT count() FROM variant_facts "
        "WHERE release_key='R-ASM' AND assembly_key='v4'"
    )
    v5_count = engine.scalar(
        "SELECT count() FROM variant_facts "
        "WHERE release_key='R-ASM' AND assembly_key='v5'"
    )
    assert int(v4_count) == 1
    assert int(v5_count) == 1
    # The imported v4 fact replaced only its own id; v5's row survives.
    assert int(engine.scalar(
        "SELECT count() FROM variant_facts "
        "WHERE release_key='R-ASM' AND assembly_key='v4' AND variant_id=11"
    )) == 1
    assert int(engine.scalar(
        "SELECT count() FROM variant_facts "
        "WHERE release_key='R-ASM' AND assembly_key='v5' AND variant_id=20"
    )) == 1


def test_duplicate_staging_batch_publishes_each_fact_once(engine: ChdbEngine) -> None:
    import_id = "imp-dup"
    rows = [_base_row(1, "RD", "Chr01", 100), _base_row(2, "RD", "Chr01", 200)]
    # A retried batch appends the same facts to staging twice.
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)

    # Distinct count is stable despite the duplicate staging append...
    assert vf.staged_distinct_count(engine, import_id) == 2
    # ...and finalize still publishes each logical fact exactly once.
    partitions = vf.list_partitions(engine, import_id)
    vf.finalize_release(engine, release_key="RD", import_id=import_id, partitions=partitions)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2
    assert _summary_cnt(engine, "RD") == 2


def test_row_count_mismatch_blocks_publish(engine: ChdbEngine) -> None:
    import_id = "imp-short"
    # Parser claims three facts but only one reached staging (crash/dropped batch).
    vf.stage_batch(
        engine, import_id=import_id, batch_index=0, base_rows=[_base_row(1, "RS", "Chr01", 100)]
    )

    assert vf.verify_against_expected(engine, import_id, expected_rows=3) is False
    # The verification gate blocks finalize, so nothing is published.
    assert engine.scalar("SELECT count() FROM variant_facts") == 0
    assert engine.scalar("SELECT count() FROM gene_impact_summary") == 0


def test_verify_passes_and_publishes_when_counts_match(engine: ChdbEngine) -> None:
    import_id = "imp-ok"
    rows = [_base_row(1, "RO", "Chr01", 100), _base_row(2, "RO", "Chr01", 200)]
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=rows)

    assert vf.verify_against_expected(engine, import_id, expected_rows=2) is True
    partitions = vf.list_partitions(engine, import_id)
    vf.finalize_release(engine, release_key="RO", import_id=import_id, partitions=partitions)
    assert engine.scalar("SELECT count() FROM variant_facts") == 2


def test_different_release_for_same_chromosome_coexist(engine: ChdbEngine) -> None:
    # Assembly/release are independent namespaces: the same chromosome under two
    # releases must publish side by side without one clobbering the other.
    vf.stage_batch(
        engine, import_id="imp-a", batch_index=0, base_rows=[_base_row(1, "RA", "Chr01", 100)]
    )
    vf.finalize_release(
        engine, release_key="RA", import_id="imp-a", partitions=[("RA", "Chr01")]
    )
    vf.stage_batch(
        engine, import_id="imp-b", batch_index=0, base_rows=[_base_row(1, "RB", "Chr01", 100)]
    )
    vf.finalize_release(
        engine, release_key="RB", import_id="imp-b", partitions=[("RB", "Chr01")]
    )
    assert engine.scalar("SELECT count() FROM variant_facts") == 2


def test_incremental_import_preserves_untouched_chromosome_summaries(
    engine: ChdbEngine,
) -> None:
    """A second import touching one chromosome must not erase the others.

    Regression for the review finding on ``finalize_release``: several summaries
    (gene_impact_summary, release_dashboard, substitution_spectrum) have no
    chromosome column, so a per-partition summary purge is impossible. Purging
    the whole release and rebuilding only the touched partition used to delete
    the untouched chromosome's summaries while its base rows stayed. The
    release-complete rebuild carries those rows through staging instead.
    """
    vf.stage_batch(
        engine,
        import_id="imp-inc-1",
        batch_index=0,
        base_rows=[_base_row(1, "RINC", "Chr01", 100)],
    )
    vf.finalize_release(
        engine,
        release_key="RINC",
        import_id="imp-inc-1",
        partitions=[("RINC", "Chr01")],
    )
    assert _summary_cnt(engine, "RINC") == 1

    vf.stage_batch(
        engine,
        import_id="imp-inc-2",
        batch_index=0,
        base_rows=[_base_row(2, "RINC", "Chr02", 200)],
    )
    vf.finalize_release(
        engine,
        release_key="RINC",
        import_id="imp-inc-2",
        partitions=[("RINC", "Chr02")],
    )

    # Both chromosomes are in the base AND both are counted in the summaries.
    assert (
        engine.scalar(
            "SELECT count() FROM variant_facts WHERE release_key = 'RINC'"
        )
        == 2
    )
    assert _summary_cnt(engine, "RINC") == 2
    assert engine.scalar(
        "SELECT count() FROM chromosome_summary FINAL WHERE release_key = 'RINC'"
    ) == 2


def test_conflicting_payload_for_one_variant_fails_closed(engine: ChdbEngine) -> None:
    import_id = "imp-conflict"
    vf.stage_batch(
        engine,
        import_id=import_id,
        batch_index=0,
        base_rows=[
            _base_row(1, "RC", "Chr01", 100, impact="MODERATE"),
            _base_row(1, "RC", "Chr01", 100, impact="HIGH"),
        ],
    )

    with pytest.raises(vf.ConflictingVariantRowsError) as raised:
        vf.finalize_release(
            engine, release_key="RC", import_id=import_id, partitions=[("RC", "Chr01")]
        )
    assert raised.value.conflicts == [(1, 2)]
    # Fail closed: nothing was published.
    assert engine.scalar("SELECT count() FROM variant_facts") == 0
    assert engine.scalar("SELECT count() FROM gene_impact_summary") == 0


def test_identical_duplicate_rows_are_deterministically_deduplicated(
    engine: ChdbEngine,
) -> None:
    import_id = "imp-identical"
    row = _base_row(1, "RI", "Chr01", 100)
    vf.stage_batch(engine, import_id=import_id, batch_index=0, base_rows=[row])
    vf.stage_batch(engine, import_id=import_id, batch_index=1, base_rows=[row])
    vf.finalize_release(
        engine, release_key="RI", import_id=import_id, partitions=[("RI", "Chr01")]
    )
    assert engine.scalar("SELECT count() FROM variant_facts") == 1
    assert _summary_cnt(engine, "RI") == 1


def test_upload_derived_values_are_bound_not_interpolated(engine: ChdbEngine) -> None:
    """A quote/SQL-fragment chromosome must not alter another release's rows."""
    engine.insert_rows(
        "variant_facts",
        [_base_row(1, "SAFE", "Chr01", 100, gene_sid=11)],
        list(vf.BASE_COLUMNS),
    )
    malicious_release = "R' OR '1'='1"
    malicious_chromosome = "Chr01') OR ('1'='1"
    vf.stage_batch(
        engine,
        import_id="imp-inject",
        batch_index=0,
        base_rows=[_base_row(2, malicious_release, malicious_chromosome, 100, gene_sid=12)],
    )
    vf.finalize_release(
        engine,
        release_key=malicious_release,
        import_id="imp-inject",
        partitions=[(malicious_release, malicious_chromosome)],
    )

    # The safe release is untouched; the malicious strings round-trip as data.
    assert (
        engine.scalar("SELECT count() FROM variant_facts WHERE release_key = 'SAFE'")
        == 1
    )
    assert (
        engine.scalar(
            "SELECT count() FROM variant_facts WHERE release_key = {rk:String}",
            params={"rk": malicious_release},
        )
        == 1
    )

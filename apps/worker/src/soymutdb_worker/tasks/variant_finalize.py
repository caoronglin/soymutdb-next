"""Variant-facts staging -> verify -> finalize protocol (ADR-0005 / P2-3).

Correctness on ClickHouse is app-level, not engine-level (ADR-0005): the base
``variant_facts`` is a plain MergeTree, the analytical summaries are
SummingMergeTree/AggregatingMergeTree fed by materialized views, and those
summaries double-count on duplicate insert and are NOT un-written by dropping a
base partition. This module encodes the protocol that keeps retries safe:

- writes land only in ``variant_facts_staging`` (no MV attached), so a partial
  or repeated write is never visible to the portal or the summaries (H2);
- ``finalize_release`` purges the release-scoped summary rows, drops the base
  partition, then rewrites the partition from the de-duplicated staged rows, so
  a re-run repairs double-counts and is idempotent.

It operates purely over :class:`ClickHouseEngine`, so the same code runs against
the production HTTP client and the embedded acceptance engine.
"""

from __future__ import annotations

import hashlib

from .clickhouse_engine import ClickHouseEngine

BASE_TABLE = "variant_facts"
STAGING_TABLE = "variant_facts_staging"

# Canonical base columns persisted into variant_facts (matches infra/clickhouse
# init.sql and the worker's columnar batch). Import bookkeeping columns
# (batch_id/import_id) exist only on the staging table.
BASE_COLUMNS: tuple[str, ...] = (
    "variant_id",
    "release_key",
    "assembly_key",
    "chromosome",
    "position",
    "ref_allele",
    "alt_allele",
    "variant_type",
    "variant_subtype",
    "length",
    "gene_id",
    "gene_symbol",
    "gene_surrogate_id",
    "mutant_line_surrogate_id",
    "mutant_line_name",
    "consequence",
    "consequence_id",
    "impact",
    "rs_id",
    "quality_score",
    "filter_status",
    "read_depth",
    "allele_frequency",
    "hgvs_c",
    "hgvs_p",
    "zygosity",
)

STAGING_COLUMNS: tuple[str, ...] = (*BASE_COLUMNS, "import_id", "batch_id")

# Every analytical summary is scoped by release_key, so a release's rows can be
# purged uniformly before its base partition is rewritten. This ordering is the
# finalize correctness contract (H2): summaries must be consistent with the base
# after a rewrite, and the only way to guarantee that against MV semantics is to
# clear and rebuild them per release partition.
RELEASE_SCOPED_SUMMARY_TABLES: tuple[str, ...] = (
    "gene_impact_summary",
    "chromosome_summary",
    "mutant_line_summary",
    "release_dashboard",
    "density_10kb",
    "density_100kb",
    "density_1mb",
    "substitution_spectrum",
)


def deterministic_batch_id(import_id: str, batch_index: int) -> str:
    """Stable identity for one logical batch, so a retried batch is
    recognisable (and idempotent) rather than blindly re-appended."""
    return hashlib.sha256(f"{import_id}|{batch_index}".encode()).hexdigest()[:32]


def clear_staging(engine: ClickHouseEngine, import_id: str) -> None:
    """Remove any staged rows for this import before (re)writing it.

    Retries after a mid-write crash must not accumulate duplicate staged rows.
    """
    engine.execute(f"ALTER TABLE {STAGING_TABLE} DELETE WHERE import_id = '{import_id}'")


def stage_batch(
    engine: ClickHouseEngine,
    *,
    import_id: str,
    batch_index: int,
    base_rows: list[tuple],
) -> str:
    """Append one batch to staging (never to the base/summary tables)."""
    if not base_rows:
        return deterministic_batch_id(import_id, batch_index)
    batch_id = deterministic_batch_id(import_id, batch_index)
    rows = [(*base_row, import_id, batch_id) for base_row in base_rows]
    engine.insert_rows(STAGING_TABLE, rows, list(STAGING_COLUMNS))
    return batch_id


def staged_distinct_count(engine: ClickHouseEngine, import_id: str) -> int:
    """Number of DISTINCT logical facts staged for this import."""
    value = engine.scalar(
        f"SELECT count(DISTINCT variant_id) FROM {STAGING_TABLE} WHERE import_id = '{import_id}'"
    )
    return int(value or 0)


def list_partitions(engine: ClickHouseEngine, import_id: str) -> list[tuple[str, str]]:
    """Distinct (release_key, chromosome) partitions present in the staged rows."""
    rows = engine.query_rows(
        f"SELECT DISTINCT release_key, chromosome FROM {STAGING_TABLE} "
        f"WHERE import_id = '{import_id}'"
    )
    return sorted({(str(r[0]), str(r[1])) for r in rows})


def finalize_release(
    engine: ClickHouseEngine,
    *,
    release_key: str,
    import_id: str,
    partitions: list[tuple[str, str]],
) -> None:
    """Publish staged rows for ``import_id`` into the base table + summaries.

    The import's staging rows are treated as the authoritative set for the
    release's touched (chromosome) partitions. Correctness hinges on ORDER:

    1. Purge every release-scoped summary ONCE for this release. Doing this
       per-partition would delete summaries an earlier partition just rebuilt.
    2. Drop only the base partitions this import touches.
    3. Rewrite those partitions from the de-duplicated staged rows; the MVs
       fire exactly once, repopulating the summaries consistently with the base.

    Re-running is idempotent: the drop discards the previous publish for these
    partitions and the rewrite reproduces the same base + summary state.
    """
    for summary in RELEASE_SCOPED_SUMMARY_TABLES:
        engine.execute(f"ALTER TABLE {summary} DELETE WHERE release_key = '{release_key}'")
    for _release, chromosome in partitions:
        engine.execute(
            f"ALTER TABLE {BASE_TABLE} DROP PARTITION ('{release_key}','{chromosome}')"
        )
    columns = ", ".join(BASE_COLUMNS)
    engine.execute(
        f"INSERT INTO {BASE_TABLE} ({columns}) "
        f"SELECT {columns} FROM ("
        f"  SELECT {columns} FROM {STAGING_TABLE} "
        f"  WHERE import_id = '{import_id}'"
        f"  GROUP BY {columns}"
        f")"
    )

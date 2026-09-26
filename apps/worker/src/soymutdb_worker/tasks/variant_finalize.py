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


class ConflictingVariantRowsError(RuntimeError):
    """One variant_id carries different factual payloads (review R1 / plan §13).

    Identical duplicate rows are deterministic dedup; a variant_id with two
    different payloads is ambiguous, so publication fails closed with the
    offending ids instead of silently keeping one of them.
    """

    def __init__(self, conflicts: list[tuple[int, int]]) -> None:
        self.conflicts = conflicts
        detail = ", ".join(
            f"{variant_id}({payloads} payloads)" for variant_id, payloads in conflicts
        )
        super().__init__(f"conflicting variant_id payloads: {detail}")


def clear_staging(engine: ClickHouseEngine, import_id: str) -> None:
    """Remove any staged rows for this import before (re)writing it.

    Retries after a mid-write crash must not accumulate duplicate staged rows.
    """
    engine.execute(
        f"ALTER TABLE {STAGING_TABLE} DELETE WHERE import_id = {{import_id:String}} "
        f"SETTINGS mutations_sync = 1",
        params={"import_id": import_id},
    )


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
        f"SELECT count(DISTINCT variant_id) FROM {STAGING_TABLE} "
        f"WHERE import_id = {{import_id:String}}",
        params={"import_id": import_id},
    )
    return int(value or 0)


def verify_against_expected(engine: ClickHouseEngine, import_id: str, expected_rows: int) -> bool:
    """Final verification gate (ADR-0005): the distinct staged facts must equal
    the expected row count before the import may publish. A mismatch (truncated
    write, dropped batch, checksum mismatch surfaced by the caller) blocks
    finalize, so the portal never sees a wrong or partial result."""
    return staged_distinct_count(engine, import_id) == expected_rows


def list_partitions(engine: ClickHouseEngine, import_id: str) -> list[tuple[str, str]]:
    """Distinct (release_key, chromosome) partitions present in the staged rows."""
    rows = engine.query_rows(
        f"SELECT DISTINCT release_key, chromosome FROM {STAGING_TABLE} "
        f"WHERE import_id = {{import_id:String}}",
        params={"import_id": import_id},
    )
    return sorted({(str(r[0]), str(r[1])) for r in rows})


def _imported_assemblies(engine: ClickHouseEngine, import_id: str) -> set[str]:
    """Distinct assembly_key values present in this import's staged rows."""
    rows = engine.query_rows(
        f"SELECT DISTINCT assembly_key FROM {STAGING_TABLE} "
        f"WHERE import_id = {{import_id:String}}",
        params={"import_id": import_id},
    )
    return {str(r[0]) for r in rows}


def conflicting_variant_ids(
    engine: ClickHouseEngine, import_id: str, limit: int = 10
) -> list[tuple[int, int]]:
    """Variant ids whose staged rows carry more than one factual payload.

    ``uniqExact(tuple(all payload columns))`` counts distinct payloads per
    variant_id: identical duplicates collapse to one, a changed annotation does
    not. The finalize gate turns a non-empty result into a hard failure.
    """
    payload_columns = tuple(column for column in BASE_COLUMNS if column != "variant_id")
    tuple_expression = "(" + ", ".join(payload_columns) + ")"
    rows = engine.query_rows(
        f"SELECT variant_id, uniqExact({tuple_expression}) AS payloads "
        f"FROM {STAGING_TABLE} WHERE import_id = {{import_id:String}} "
        f"GROUP BY variant_id HAVING payloads > 1 "
        f"ORDER BY variant_id LIMIT {int(limit)}",
        params={"import_id": import_id},
    )
    return [(int(row[0]), int(row[1])) for row in rows]


def _release_chromosomes(engine: ClickHouseEngine, release_key: str) -> set[str]:
    """Chromosomes currently present in the base for one release."""
    rows = engine.query_rows(
        f"SELECT DISTINCT chromosome FROM {BASE_TABLE} "
        f"WHERE release_key = {{release_key:String}}",
        params={"release_key": release_key},
    )
    return {str(row[0]) for row in rows}


def _carry_untouched_partitions(
    engine: ClickHouseEngine,
    *,
    release_key: str,
    import_id: str,
    touched: set[str],
    imported_assemblies: set[str],
) -> None:
    """Copy the release's not-replaced base rows into staging before rebuild.

    The physical partition is ``(release_key, chromosome)``, so v4 and v5 rows
    for the same chromosome share a partition and a partition drop removes
    both. Carrying must therefore exclude only the ``(assembly, chromosome)``
    facts actually being replaced: for a touched chromosome, rows of an
    assembly *not* in this import are carried too. Without this, importing v4
    would delete v5's rows for the same chromosome.

    Several summaries (gene_impact_summary, release_dashboard,
    substitution_spectrum) carry no chromosome column, so their rows cannot be
    purged per partition. Purging the whole release and rebuilding only the
    touched partitions would therefore delete the summaries of untouched
    chromosomes while their base rows stay. Carrying those rows into staging
    first makes the rebuild release-complete: summaries are rebuilt from a base
    that still contains every chromosome of the release.
    """
    columns = ", ".join(BASE_COLUMNS)
    carry_batch = deterministic_batch_id(import_id, -1)
    ordered_assemblies = sorted(imported_assemblies)
    for chromosome in sorted(_release_chromosomes(engine, release_key)):
        where = (
            "release_key = {release_key:String} "
            "AND chromosome = {chromosome:String}"
        )
        params: dict[str, str] = {
            "import_id": import_id,
            "batch_id": carry_batch,
            "release_key": release_key,
            "chromosome": chromosome,
        }
        if chromosome in touched and ordered_assemblies:
            placeholders = ", ".join(
                f"{{assembly_{i}:String}}" for i in range(len(ordered_assemblies))
            )
            where += f" AND assembly_key NOT IN ({placeholders})"
            for i, assembly in enumerate(ordered_assemblies):
                params[f"assembly_{i}"] = assembly
        engine.execute(
            f"INSERT INTO {STAGING_TABLE} ({columns}, import_id, batch_id) "
            f"SELECT {columns}, {{import_id:String}}, {{batch_id:String}} "
            f"FROM {BASE_TABLE} WHERE {where}",
            params=params,
        )


def _purge_release_summaries(engine: ClickHouseEngine, release_key: str) -> None:
    """Delete every release-scoped summary row, waiting for each mutation.

    ClickHouse mutations are asynchronous by default: without
    ``mutations_sync = 1`` the following rebuild races the DELETE and the MV
    can re-insert over rows that are being removed (review R1 / plan §11).
    """
    for summary in RELEASE_SCOPED_SUMMARY_TABLES:
        engine.execute(
            f"ALTER TABLE {summary} DELETE WHERE release_key = {{release_key:String}} "
            f"SETTINGS mutations_sync = 1",
            params={"release_key": release_key},
        )


def _drop_release_partitions(
    engine: ClickHouseEngine, *, release_key: str, chromosomes: set[str]
) -> None:
    for chromosome in sorted(chromosomes):
        engine.execute(
            f"ALTER TABLE {BASE_TABLE} DROP PARTITION "
            f"({{release_key:String}}, {{chromosome:String}})",
            params={"release_key": release_key, "chromosome": chromosome},
        )


def _rebuild_base_from_staging(engine: ClickHouseEngine, import_id: str) -> None:
    """Rewrite the release base rows from the complete (carried) staged set."""
    columns = ", ".join(BASE_COLUMNS)
    engine.execute(
        f"INSERT INTO {BASE_TABLE} ({columns}) "
        f"SELECT {columns} FROM ("
        f"  SELECT {columns} FROM {STAGING_TABLE} "
        f"  WHERE import_id = {{import_id:String}} "
        f"  GROUP BY {columns}"
        f")",
        params={"import_id": import_id},
    )


def finalize_release(
    engine: ClickHouseEngine,
    *,
    release_key: str,
    import_id: str,
    partitions: list[tuple[str, str]],
) -> None:
    """Publish staged rows for ``import_id`` as a release-consistent rebuild.

    Publication is a FULL-RELEASE rebuild, not a touched-partition patch:

    1. Fail closed when one variant_id carries conflicting payloads.
    2. Carry the release's untouched base rows into staging.
    3. Purge every release-scoped summary (``mutations_sync = 1``).
    4. Drop all of the release's base partitions (touched + existing).
    5. Rewrite from the complete staged set; the MVs fire exactly once and
       rebuild the summaries consistently with the base.

    Re-running is idempotent: the carry and the staged set deduplicate to the
    same facts, and step 4 discards the previous publish before step 5
    reproduces it. All upload-derived values are bound parameters (plan §12).
    """
    conflicts = conflicting_variant_ids(engine, import_id)
    if conflicts:
        raise ConflictingVariantRowsError(conflicts)

    touched = {chromosome for _release, chromosome in partitions}
    imported_assemblies = _imported_assemblies(engine, import_id)
    existing = _release_chromosomes(engine, release_key)
    _carry_untouched_partitions(
        engine,
        release_key=release_key,
        import_id=import_id,
        touched=touched,
        imported_assemblies=imported_assemblies,
    )
    _purge_release_summaries(engine, release_key)
    _drop_release_partitions(
        engine, release_key=release_key, chromosomes=touched | existing
    )
    _rebuild_base_from_staging(engine, import_id)

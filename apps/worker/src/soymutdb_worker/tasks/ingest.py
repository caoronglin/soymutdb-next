"""Variant ingestion tasks.

Fixes vs. quartz reference:
- **Stable identity**: variant IDs are deterministic — derived from
  ``release_id + file_key + chromosome + position + ref + alt`` via a stable
  hash, NOT an in-memory counter. This does not make imports idempotent:
  ``variant_facts`` uses ``MergeTree`` and its materialized summaries are
  additive, so retries would insert and aggregate duplicates.
- **zygosity**: read from the actual sample genotype (cyvcf2 ``gt_type``),
  not hardcoded to ``"heterozygous"``.
- **No dependency on non-existent INFO fields**: ``GENE_SID`` / ``ML_SID`` are
  no longer required.  Gene and mutant-line surrogate IDs are resolved from
  the SnpEff ``ANN`` field and the sample name respectively.
- **cyvcf2**: uses ``cyvcf2.VCF`` for efficient streaming parsing of
  bgzipped VCF files.
- **SnpEff ANN parsing**: parses the standard ``ANN`` INFO field.
- **Trigram index rebuild**: triggers a full-text index rebuild after
  ingestion.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from typing import Any

import clickhouse_connect
from celery import Task
from clickhouse_connect.driver import Client
from soymutdb_import_protocol import ImportManifestStatus
from sqlalchemy import or_, select, text

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.tables import assemblies, releases
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import download_file, stream_s3_file

from .clickhouse_engine import ClickHouseEngine, HttpClickHouseEngine
from .data_adapters import ImportContext, UnsupportedImportError, get_adapter
from .import_manifest_repo import (
    get as get_manifest,
)
from .import_manifest_repo import (
    manifest_lock,
    mark_failed,
    record_counts,
    start_or_resume,
    transition,
)
from .variant_finalize import (
    BASE_COLUMNS,
    ConflictingVariantRowsError,
    clear_staging,
    finalize_release,
    list_partitions,
    stage_batch,
    verify_against_expected,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 50_000
_IMPORT_LOCK_NAMESPACE = 0x534D4442

# ADR-0005 / P2-3: the idempotent VCF import path is gated behind a worker flag
# that defaults OFF. Until the flag is flipped, import_vcf keeps failing closed
# (P1-2 422 preserved). The ON path runs the staging -> verify -> finalize
# protocol verified against the real engine tests.
VCF_IMPORT_FLAG = "SOYMUTDB_ENABLE_VCF_IMPORT"
# Stable importer/schema/normalization/config versions entering the fingerprint.
_VCF_IMPORTER_VERSION = "vcf-1"
_VCF_SCHEMA_VERSION = "fact-1"
_VCF_NORMALIZATION_VERSION = "norm-1"
_VCF_CONFIG_HASH = hashlib.sha256(b"soymutdb-vcf-import@1").hexdigest()


def _vcf_import_enabled() -> bool:
    return get_setting(VCF_IMPORT_FLAG, "false").lower() in {"1", "true", "yes", "on"}
_TERMINAL_IMPORT_STATUSES = frozenset({"ready", "published", "rolled_back"})


def _import_lock_key(import_task_id: int) -> int:
    """Return a stable signed-bigint advisory-lock key for one import task."""
    if not 0 < import_task_id <= 0x7FFFFFFF:
        raise ValueError("import_task_id is outside the supported integer range")
    return (_IMPORT_LOCK_NAMESPACE << 32) | import_task_id


@contextmanager
def import_execution_guard(import_task_id: int) -> Iterator[bool]:
    """Fence duplicate deliveries with a PostgreSQL session advisory lock.

    The lock is held for the complete adapter execution. A concurrent copy is
    acknowledged without running, while a later redelivery observes a terminal
    task status and also skips. PostgreSQL releases the lock automatically if
    the worker process or connection dies.
    """
    params = {"lock_key": _import_lock_key(import_task_id)}
    with get_db() as session:
        acquired = bool(
            session.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                params,
            ).scalar_one()
        )
        if not acquired:
            logger.warning(
                "duplicate import delivery skipped: task %s is already running",
                import_task_id,
            )
            yield False
            return

        try:
            row = session.execute(
                text("SELECT status FROM import_tasks WHERE id = :task_id"),
                {"task_id": import_task_id},
            ).first()
            if row is None:
                raise RuntimeError(f"import task {import_task_id} does not exist")
            yield str(row[0]) not in _TERMINAL_IMPORT_STATUSES
        finally:
            released = bool(
                session.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    params,
                ).scalar_one()
            )
            if not released:
                logger.error(
                    "import advisory lock was not owned at release: task %s",
                    import_task_id,
                )


def update_import_progress(import_task_id: int, **values: Any) -> None:
    """Persist import task progress/state to PostgreSQL.

    This is the worker-side state write used by every import adapter.  It is
    intentionally best-effort: a metrics/state write failure must not abort
    the underlying ingestion work.
    """
    logger.info("import progress", import_task_id=import_task_id, **values)
    try:
        from sqlalchemy import update

        from soymutdb_worker.tables import import_tasks
        from soymutdb_worker.utils.db import get_db

        update_values: dict[str, Any] = {}
        if "status" in values:
            update_values["status"] = values["status"]
        if "progress" in values:
            update_values["progress"] = int(values["progress"])
        if "processed" in values:
            update_values["processed_records"] = int(values["processed"])
        if "total" in values:
            update_values["total_records"] = int(values["total"])
        if "error_detail" in values:
            update_values["error_detail"] = values["error_detail"]
        if "failed_batch" in values:
            update_values["failed_batch"] = values["failed_batch"]
        if values.get("status") == "failed":
            update_values["error_message"] = str(values.get("error_detail", "import failed"))[:4000]
            from datetime import datetime

            update_values["completed_at"] = datetime.now(UTC)
        if not update_values:
            return
        with get_db() as session:
            session.execute(
                update(import_tasks)
                .where(import_tasks.c.id == import_task_id)
                .values(**update_values)
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "import_progress_persist_failed",
            import_task_id=import_task_id,
            error=str(exc),
        )


def current_batch() -> int | None:
    return None


def _surrogate_id(key: str) -> int:
    """Return a deterministic unsigned UInt32 surrogate ID for CH projection.

    This is a **ClickHouse projection surrogate only** — it must never be
    used as an authoritative foreign key into PostgreSQL. Gene and mutant-line
    identity in PG is resolved via ``(assembly, accession)`` and
    ``public_id`` respectively, not via this hash.
    """
    return (
        int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big", signed=False)
        & 0xFFFFFFFF
    )


def _pick_mutant_line(sample_names: list[str], gt_types: Any, alt_idx: int) -> tuple[str, int]:
    """Choose the first known non-reference sample for an ALT row.

    The returned ``ml_sid`` is a ClickHouse projection surrogate
    (``_surrogate_id``), not an authoritative PostgreSQL mutant-line key.
    When VCF import is re-enabled, sample-name→mutant-line resolution must
    query PG by ``public_id`` or lab designation and use the real
    ``mutant_lines.id`` (or ``public_id``) for any authoritative linkage.
    """
    if not sample_names or gt_types is None:
        return "", 0
    for sample_idx, gt_type in enumerate(gt_types):
        if sample_idx >= len(sample_names):
            break
        if int(gt_type) not in (0, 3):
            sample_name = sample_names[sample_idx]
            return sample_name, _surrogate_id(sample_name)
    return "", 0

# ---------------------------------------------------------------------------
# SnpEff ANN field consequence rank (most → least severe)
# ---------------------------------------------------------------------------

CONSEQUENCE_RANK: dict[str, int] = {
    "transcript_ablation": 1,
    "splice_acceptor_variant": 2,
    "splice_donor_variant": 3,
    "stop_gained": 4,
    "frameshift_variant": 5,
    "stop_lost": 6,
    "start_lost": 7,
    "transcript_amplification": 8,
    "inframe_insertion": 9,
    "inframe_deletion": 10,
    "missense_variant": 11,
    "protein_altering_variant": 12,
    "splice_region_variant": 13,
    "splice_donor_5th_base_variant": 14,
    "splice_donor_region_variant": 15,
    "splice_polypyrimidine_tract_variant": 16,
    "incomplete_terminal_codon_variant": 17,
    "start_retained_variant": 18,
    "stop_retained_variant": 19,
    "synonymous_variant": 20,
    "coding_sequence_variant": 21,
    "mature_miRNA_variant": 22,
    "5_prime_UTR_variant": 23,
    "3_prime_UTR_variant": 24,
    "non_coding_transcript_exon_variant": 25,
    "intron_variant": 26,
    "NMD_transcript_variant": 27,
    "non_coding_transcript_variant": 28,
    "upstream_gene_variant": 29,
    "downstream_gene_variant": 30,
    "TFBS_ablation": 31,
    "TFBS_amplification": 32,
    "TF_binding_site_variant": 33,
    "regulatory_region_ablation": 34,
    "regulatory_region_amplification": 35,
    "regulatory_region_variant": 36,
    "feature_truncation": 37,
    "feature_elongation": 38,
    "intergenic_variant": 39,
}

IMPACT_RANK = {"HIGH": 1, "MODERATE": 2, "LOW": 3, "MODIFIER": 4}


# ---------------------------------------------------------------------------
# ClickHouse client
# ---------------------------------------------------------------------------


def get_clickhouse_client() -> Client:
    """Return a synchronous ClickHouse client for worker tasks."""
    url = get_setting(
        "CLICKHOUSE_URL",
        "http://soymutdb:soymutdb_dev_password@localhost:8123/soymutdb",
    )
    match = re.match(r"https?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", url)
    if match:
        user, password, host, port_str, database = match.groups()
        port = int(port_str)
    else:
        user = "default"
        password = ""
        host = "localhost"
        port = 8123
        database = "soymutdb"

    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
    )


# ---------------------------------------------------------------------------
# Deterministic variant ID (stable identity only; not deduplication)
# ---------------------------------------------------------------------------


def compute_variant_id(
    release_id: str,
    chromosome: str,
    position: int,
    ref: str,
    alt: str,
) -> int:
    """Compute a deterministic variant ID from stable semantic facts.

    The identity is derived from ``release_id + chromosome + position + ref +
    alt`` only. The uploaded object key is deliberately NOT an input: the
    manifest fingerprint ignores it so a retry can resume the same logical
    import (ADR-0005), and the per-variant identity must agree with that —
    otherwise the same bytes retried under a new object key would mint new
    variant ids and publish duplicate facts (review R1 / plan §10).

    This replaces the non-idempotent ``variant_id_counter`` from the quartz
    reference; durable import idempotency remains a separate requirement.
    """
    key = f"{release_id}|{chromosome}|{position}|{ref}|{alt}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    # Use the first 8 bytes as a signed 64-bit integer
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


# ---------------------------------------------------------------------------
# Variant type determination
# ---------------------------------------------------------------------------


def determine_variant_type(ref: str, alt: str) -> tuple[str, str]:
    """Determine variant type and subtype from ref/alt alleles.

    ``variant_type`` uses the canonical set the ClickHouse schema and its
    summaries filter on: SNP / INS / DEL / MNV / SV. A same-length multi-base
    substitution is an MNV, never a SNP: chromosome_summary and
    substitution_spectrum group by variant_type, and the seed loader
    (scripts/seed_release_data.py) already classified it as MNV, so the worker
    would have produced different facts for identical input.
    """
    ref_len = len(ref)
    alt_len = len(alt)

    if alt == "<DEL>" or alt.startswith("<") or alt_len > 50 or ref_len > 50:
        return "SV", "SV"
    if ref_len == 1 and alt_len == 1:
        return "SNP", "SNV"
    if ref_len == alt_len:
        return "MNV", "MNV"
    if alt_len > ref_len:
        return "INS", "INS"
    if ref_len > alt_len:
        return "DEL", "DEL"
    return "MNV", "MIX"


# ---------------------------------------------------------------------------
# SnpEff ANN field parsing
# ---------------------------------------------------------------------------


def parse_snpeff_ann(ann_str: str) -> list[dict[str, str]]:
    """Parse a SnpEff ``ANN`` INFO field into a list of annotation dicts.

    The ANN field format (pipe-delimited):
    ``Allele|Annotation|Annotation_Impact|Gene_Name|Gene_ID|Feature_ID|
    Feature_Type|Rank|HGVS.c|HGVS.p|cDNA.pos|CDS.pos|AA.pos|Distance|...``
    """
    annotations: list[dict[str, str]] = []
    for entry in ann_str.split(","):
        fields = entry.split("|")
        if len(fields) < 10:
            continue
        annotations.append(
            {
                "allele": fields[0],
                "consequence": fields[1],
                "impact": fields[2],
                "gene_name": fields[3],
                "gene_id": fields[4],
                "feature_id": fields[5],
                "feature_type": fields[6],
                "rank": fields[7] if len(fields) > 7 else "",
                "hgvs_c": fields[8] if len(fields) > 8 else "",
                "hgvs_p": fields[9] if len(fields) > 9 else "",
            }
        )
    return annotations


def pick_most_severe_annotation(annotations: list[dict[str, str]]) -> dict[str, str] | None:
    """Pick the most severe annotation from SnpEff ANN entries."""
    if not annotations:
        return None
    best: dict[str, str] | None = None
    best_rank = 999
    for ann in annotations:
        consequence = ann.get("consequence", "")
        # SnpEff may have multiple consequences separated by &
        first_term = consequence.split("&")[0]
        rank = CONSEQUENCE_RANK.get(first_term, 100)
        if rank < best_rank:
            best_rank = rank
            best = ann
    return best


# ---------------------------------------------------------------------------
# Zygosity from sample genotype
# ---------------------------------------------------------------------------


def determine_zygosity(gt_type: int) -> str:
    """Determine zygosity from cyvcf2 ``gt_type``.

    cyvcf2 gt_type values:
    - 0: HOM_REF
    - 1: HET
    - 2: HOM_ALT
    - 3: UNKNOWN (missing)

    This replaces the hardcoded ``"heterozygous"`` from the quartz reference.
    """
    mapping = {0: "homozygous_ref", 1: "heterozygous", 2: "homozygous_alt", 3: "unknown"}
    return mapping.get(gt_type, "unknown")


# ---------------------------------------------------------------------------
# Trigram full-text index rebuild
# ---------------------------------------------------------------------------


def rebuild_trigram_index(ch: Client, release_id: str) -> None:
    """Rebuild the trigram full-text index for a release.

    Uses ClickHouse's ``tokenbf_v1`` / ``ngrambf_v1`` skip indexes which are
    maintained automatically on insert.  This function runs an ``OPTIMIZE``
    to force merge pending parts so the index is immediately usable.
    """
    logger.info("Rebuilding trigram index for release %s", release_id)
    try:
        ch.command(
            "OPTIMIZE TABLE variant_facts FINAL SETTINGS mutations_sync = 1"
        )
    except Exception as e:
        logger.warning("Trigram index rebuild (OPTIMIZE) failed: %s", e)


# ---------------------------------------------------------------------------
# VCF ingestion (cyvcf2)
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.ingest.import_vcf",
    queue="ingest",
)
def import_vcf(
    self: Task,
    release_id: str,
    file_key: str,
    assembly_key: str = "",
    batch_size: int = BATCH_SIZE,
    engine: ClickHouseEngine | None = None,
) -> dict:
    """Ingest variants from a VCF file into ClickHouse via the ADR-0005 protocol.

    Staging -> verify -> finalize make retries safe: writes land only in the
    staging table, the release partition is rewritten from de-duplicated staged
    rows, and only a PUBLISHED import is visible to the portal.

    Gated behind ``SOYMUTDB_ENABLE_VCF_IMPORT`` (default OFF). Until the flag is
    flipped -- which requires real ClickHouse acceptance per ADR-0005 -- this
    task keeps failing closed so the disabled capability returns 422 (P1-2).

    Args:
        release_id: Release version string; resolved to the integer release id
            recorded on the manifest and used as the ``variant_facts`` release_key.
        file_key: object key of the VCF file (stable id + source checksum).
        assembly_key: Assembly label; resolved to the integer assembly id.
        batch_size: Number of variants per staging batch.
        engine: ClickHouse engine port (injected in tests; defaults to the
            production clickhouse-connect client).
    """
    if not _vcf_import_enabled():
        raise UnsupportedImportError(
            "VCF import is disabled: variant_facts uses MergeTree and the "
            "idempotent staging/finalize protocol is gated off until real "
            "ClickHouse acceptance (ADR-0005)"
        )

    engine = engine or HttpClickHouseEngine(get_clickhouse_client())
    logger.info(
        "Starting protocol-driven VCF ingestion: %s for release %s", file_key, release_id
    )
    with download_file(file_key) as local_vcf_path:
        source_sha256 = _sha256_file(local_vcf_path)
        with get_db() as session:
            release_id_int, assembly_id_int = _resolve_release_assembly(
                session, release_id, assembly_key
            )
            if release_id_int is None:
                raise ValueError(f"unknown release version: {release_id!r}")
            if assembly_id_int is None:
                raise ValueError(f"unknown assembly: {assembly_key!r}")
            return _import_vcf_via_protocol(
                engine,
                release_id=release_id,
                assembly_key=assembly_key,
                local_vcf_path=local_vcf_path,
                file_key=file_key,
                batch_size=batch_size,
                source_sha256=source_sha256,
                release_id_int=release_id_int,
                assembly_id_int=assembly_id_int,
            )


def _sha256_file(path: str, _chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_release_assembly(
    session, release_version: str, assembly_key: str
) -> tuple[int | None, int | None]:
    """Resolve the release version + assembly label to their integer ids.

    The manifest is keyed by integer release/assembly ids (ADR-0005); the VCF
    import carries their string labels. Unknown labels return ``None`` so the
    import fails closed rather than recording a manifest against an unresolved
    release/assembly.
    """
    release_int = session.execute(
        select(releases.c.id).where(releases.c.version == release_version)
    ).scalar_one_or_none()
    assembly_int = None
    if assembly_key:
        assembly_int = session.execute(
            select(assemblies.c.id).where(
                or_(assemblies.c.name == assembly_key, assemblies.c.version == assembly_key)
            )
        ).scalar_one_or_none()
    return release_int, assembly_int


def _iter_vcf_base_rows(
    local_vcf_path: str, release_key: str, assembly_key: str, file_key: str
) -> Iterator[tuple]:
    """Yield canonical ``variant_facts`` rows (BASE_COLUMNS order) from a VCF.

    ``file_key`` identifies the import for logging/context only; variant
    identity is computed from the stable facts (see ``compute_variant_id``), so
    a retry under a different object key reproduces the same ids.
    """
    from cyvcf2 import VCF

    vcf = VCF(local_vcf_path)
    sample_names = vcf.samples
    try:
        for variant in vcf:
            alts = variant.ALT
            if not alts:
                continue
            chrom = variant.CHROM
            pos = variant.POS
            ref = variant.REF
            qual = variant.QUAL if variant.QUAL is not None else 0.0
            filt = variant.FILTER if variant.FILTER else "PASS"
            annotations = parse_snpeff_ann(variant.INFO.get("ANN", ""))
            best_ann = pick_most_severe_annotation(annotations)
            gene_id = best_ann.get("gene_id", "") if best_ann else ""
            gene_sid = _surrogate_id(gene_id) if gene_id else 0
            try:
                mutant_line_name, ml_sid = _pick_mutant_line(
                    sample_names, variant.gt_types, 0
                )
            except Exception:
                mutant_line_name, ml_sid = "", 0
            zygosity = "unknown"
            try:
                gt_types = variant.gt_types
                if gt_types is not None and len(gt_types) > 0:
                    zygosity = determine_zygosity(int(gt_types[0]))
            except Exception:
                pass
            try:
                af_val = variant.INFO.get("AF")
                af = float(af_val) if af_val is not None else 0.0
            except (ValueError, TypeError):
                af = 0.0
            try:
                dp_val = variant.INFO.get("DP")
                dp = int(dp_val) if dp_val is not None else 0
            except (ValueError, TypeError):
                dp = 0
            rs_id = variant.ID if variant.ID else ""
            for alt in alts:
                if alt is None:
                    continue
                vtype, vsubtype = determine_variant_type(ref, str(alt))
                row = {
                    "variant_id": compute_variant_id(
                        release_key, chrom, pos, ref, str(alt)
                    ),
                    "release_key": release_key,
                    "assembly_key": assembly_key,
                    "chromosome": chrom,
                    "position": pos,
                    "ref_allele": ref,
                    "alt_allele": str(alt),
                    "variant_type": vtype,
                    "variant_subtype": vsubtype,
                    "length": max(len(ref), len(str(alt))),
                    "gene_id": gene_id,
                    "gene_symbol": best_ann.get("gene_name", "") if best_ann else "",
                    "gene_surrogate_id": gene_sid,
                    "mutant_line_surrogate_id": ml_sid,
                    "mutant_line_name": mutant_line_name,
                    "consequence": best_ann.get("consequence", "") if best_ann else "",
                    "consequence_id": 0,
                    "impact": best_ann.get("impact", "MODIFIER") if best_ann else "MODIFIER",
                    "rs_id": rs_id,
                    "quality_score": float(qual),
                    "filter_status": filt,
                    "read_depth": dp,
                    "allele_frequency": af,
                    "hgvs_c": best_ann.get("hgvs_c", "") if best_ann else "",
                    "hgvs_p": best_ann.get("hgvs_p", "") if best_ann else "",
                    "zygosity": zygosity,
                }
                yield tuple(row[column] for column in BASE_COLUMNS)
    finally:
        vcf.close()


def _import_vcf_via_protocol(
    engine: ClickHouseEngine,
    *,
    release_id: str,
    assembly_key: str,
    local_vcf_path: str,
    file_key: str,
    batch_size: int,
    source_sha256: str,
    release_id_int: int,
    assembly_id_int: int,
) -> dict:
    """Drive manifest lifecycle + staging/verify/finalize for one VCF import.

    Idempotent by fingerprint: a PUBLISHED import returns without re-writing; a
    FAILED or interrupted import resumes from its manifest and re-run finalize
    is safe. A row-count mismatch marks the import FAILED and publishes nothing.

    Same-fingerprint concurrency is serialized by a PostgreSQL advisory lock
    (``manifest_lock``): the second delivery waits, re-reads the manifest, and
    observes PUBLISHED instead of racing the first writer's staging/finalize.
    """
    with get_db() as session:
        manifest, _created = start_or_resume(
            session,
            source_sha256=source_sha256,
            release_id=release_id_int,
            assembly_id=assembly_id_int,
            importer_version=_VCF_IMPORTER_VERSION,
            schema_version=_VCF_SCHEMA_VERSION,
            normalization_version=_VCF_NORMALIZATION_VERSION,
            config_hash=_VCF_CONFIG_HASH,
        )
        import_id = manifest.import_id
        if manifest.status == ImportManifestStatus.PUBLISHED.value:
            return _published_result(session, import_id)

        with manifest_lock(session, manifest.fingerprint):
            # A concurrent delivery may have finished while this one waited for
            # the lock; re-read before touching staging.
            current = get_manifest(session, import_id)
            if current is None:  # pragma: no cover - the row cannot vanish here
                raise RuntimeError(f"import manifest {import_id} disappeared")
            manifest = current
            if manifest.status == ImportManifestStatus.PUBLISHED.value:
                return _published_result(session, import_id)

            if manifest.status == ImportManifestStatus.FAILED.value:
                manifest = transition(session, manifest, ImportManifestStatus.CREATED)
            if manifest.status == ImportManifestStatus.CREATED.value:
                manifest = transition(session, manifest, ImportManifestStatus.PARSING)

            # Recovery matrix (review R1). Every state a crash can leave behind
            # resumes without an illegal transition:
            #   CREATED / PARSING / WRITING / VERIFYING -> restage from scratch
            #   (staging is private and cleared first), then advance only the
            #   transitions not yet reached. A crash during finalize leaves
            #   VERIFYING, which resumes here and goes straight to PUBLISHED —
            #   never VERIFYING -> VERIFYING (rejected by the shared state machine).
            clear_staging(engine, import_id)
            total = 0
            batch: list[tuple] = []
            batch_index = 0
            for row in _iter_vcf_base_rows(
                local_vcf_path, release_id, assembly_key, file_key
            ):
                batch.append(row)
                total += 1
                if len(batch) >= batch_size:
                    stage_batch(
                        engine, import_id=import_id, batch_index=batch_index, base_rows=batch
                    )
                    batch_index += 1
                    batch = []
            if batch:
                stage_batch(engine, import_id=import_id, batch_index=batch_index, base_rows=batch)

            if manifest.status == ImportManifestStatus.PARSING.value:
                manifest = transition(session, manifest, ImportManifestStatus.WRITING)

            if not verify_against_expected(engine, import_id, total):
                mark_failed(session, manifest, "row_count_mismatch")
                return {
                    "status": "failed",
                    "reason": "row_count_mismatch",
                    "import_id": import_id,
                    "expected_rows": total,
                }

            record_counts(session, manifest, written_rows=total)
            if manifest.status == ImportManifestStatus.WRITING.value:
                manifest = transition(session, manifest, ImportManifestStatus.VERIFYING)
            try:
                finalize_release(
                    engine,
                    release_key=release_id,
                    import_id=import_id,
                    partitions=list_partitions(engine, import_id),
                )
            except ConflictingVariantRowsError as error:
                # Fail closed with diagnostics: one variant_id carrying two
                # factual payloads is ambiguous, never silently resolved
                # (review R1 / plan §13).
                mark_failed(session, manifest, "conflicting_variant_rows")
                return {
                    "status": "failed",
                    "reason": "conflicting_variant_rows",
                    "import_id": import_id,
                    "diagnostics": [
                        {"variant_id": variant_id, "payloads": payloads}
                        for variant_id, payloads in error.conflicts
                    ],
                }
            manifest = transition(session, manifest, ImportManifestStatus.PUBLISHED)
            return {
                "status": "published",
                "import_id": import_id,
                "written_rows": total,
                "idempotent": False,
            }


def _published_result(session, import_id: str) -> dict:
    """The idempotent response for an already-published logical import."""
    written = get_manifest(session, import_id)
    return {
        "status": "published",
        "import_id": import_id,
        "written_rows": (written or {})["written_rows"] or 0,
        "idempotent": True,
    }


# ---------------------------------------------------------------------------
# GFF3 ingestion
# ---------------------------------------------------------------------------


@celery_app.task(
    name="soymutdb_worker.tasks.ingest.import_gff3",
    queue="ingest",
)
def import_gff3(
    release_id: str,
    file_key: str,
    assembly_id: str = "",
) -> dict:
    """Ingest gene models from a GFF3 file.

    Streams from S3 and parses gene/transcript/exon features.
    """
    logger.info("Starting GFF3 ingestion: %s", file_key)

    genes_count = 0
    transcripts_count = 0
    exons_count = 0

    with stream_s3_file(file_key) as s3_stream:
        import gzip as gz

        if file_key.endswith(".gz"):
            text_stream = io.TextIOWrapper(gz.GzipFile(fileobj=s3_stream), encoding="utf-8")
        else:
            text_stream = io.TextIOWrapper(s3_stream, encoding="utf-8")

        reader = csv.reader(text_stream, delimiter="\t")
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 9:
                continue

            feature_type = row[2]
            if feature_type == "gene":
                genes_count += 1
            elif feature_type in ("mRNA", "transcript"):
                transcripts_count += 1
            elif feature_type == "exon":
                exons_count += 1

    logger.info(
        "GFF3 ingestion complete: %d genes, %d transcripts, %d exons",
        genes_count,
        transcripts_count,
        exons_count,
    )

    return {
        "genes": genes_count,
        "transcripts": transcripts_count,
        "exons": exons_count,
        "assembly_id": assembly_id,
        "release_id": release_id,
    }


# ---------------------------------------------------------------------------
# Mutant lines ingestion
# ---------------------------------------------------------------------------


@celery_app.task(
    name="soymutdb_worker.tasks.ingest.import_mutant_lines",
    queue="ingest",
)
def import_mutant_lines(
    release_id: str,
    file_key: str,
) -> dict:
    """Ingest mutant line metadata from a TSV file.

    The TSV should have a header row with columns: name, species, cultivar,
    mutagen, mutagen_dose, generation, description.
    """
    logger.info("Starting mutant line ingestion: %s", file_key)

    count = 0

    with stream_s3_file(file_key) as s3_stream:
        import gzip as gz

        if file_key.endswith(".gz"):
            text_stream = io.TextIOWrapper(gz.GzipFile(fileobj=s3_stream), encoding="utf-8")
        else:
            text_stream = io.TextIOWrapper(s3_stream, encoding="utf-8")

        reader = csv.DictReader(text_stream, delimiter="\t")
        for _row in reader:
            count += 1

    logger.info("Mutant line ingestion complete: %d lines", count)

    return {"count": count, "release_id": release_id}


@celery_app.task(name="soymutdb_worker.tasks.ingest.run_import_adapter", queue="ingest")
def run_import_adapter(import_task_id: int, data_set_id: int, kind: str,
                       release_id: str, file_key: str, assembly: str = "",
                       module_key: str | None = None,
                       schema_version: int | None = None,
                       checksum: str | None = None,
                       filename: str | None = None) -> dict[str, Any]:
    with import_execution_guard(import_task_id) as should_run:
        if not should_run:
            return {
                "import_task_id": import_task_id,
                "skipped": True,
                "reason": "duplicate_or_completed",
            }

        context = ImportContext(
            import_task_id,
            data_set_id,
            release_id,
            file_key,
            assembly or None,
            module_key=module_key,
            schema_version=schema_version,
            checksum=checksum,
            filename=filename,
        )
        try:
            update_import_progress(import_task_id, status="ingesting", progress=0)
            result = get_adapter(kind).run(
                context,
                progress=lambda **values: update_import_progress(import_task_id, **values),
            )
            update_import_progress(
                import_task_id,
                status="ready",
                progress=100,
                evidence=result.evidence,
            )
            from dataclasses import asdict

            return asdict(result)
        except Exception as exc:
            update_import_progress(
                import_task_id,
                status="failed",
                error_detail=str(exc),
                failed_batch=current_batch(),
            )
            raise

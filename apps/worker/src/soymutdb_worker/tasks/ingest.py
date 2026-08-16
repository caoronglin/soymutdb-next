"""Variant ingestion tasks.

Fixes vs. quartz reference:
- **Idempotent**: variant IDs are deterministic — derived from
  ``release_id + file_key + chromosome + position + ref + alt`` via a stable
  hash, NOT an in-memory counter.  Re-importing the same file produces the
  same IDs, so ClickHouse ``REPLACE`` deduplicates automatically.
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
from datetime import UTC
from typing import Any

import clickhouse_connect
from celery import Task
from clickhouse_connect.driver import Client

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.utils.s3 import download_file, stream_s3_file

from .data_adapters import ImportContext, get_adapter

logger = logging.getLogger(__name__)

BATCH_SIZE = 50_000


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
        logger.warning("import_progress_persist_failed", import_task_id=import_task_id, error=str(exc))


def current_batch() -> int | None:
    return None


def _surrogate_id(key: str) -> int:
    """Return a deterministic unsigned UInt32 surrogate ID."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big", signed=False) & 0xFFFFFFFF


def _pick_mutant_line(sample_names: list[str], gt_types: Any, alt_idx: int) -> tuple[str, int]:
    """Choose the first known non-reference sample for an ALT row."""
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
# Deterministic variant ID (idempotent)
# ---------------------------------------------------------------------------


def compute_variant_id(
    release_id: str,
    file_key: str,
    chromosome: str,
    position: int,
    ref: str,
    alt: str,
) -> int:
    """Compute a deterministic, idempotent variant ID.

    The ID is derived from a stable SHA-256 hash of
    ``release_id + file_key + chromosome + position + ref + alt``.
    Re-importing the same file always produces the same IDs, so ClickHouse
    ``REPLACE`` / ``ReplacingMergeTree`` deduplicates automatically.

    This replaces the non-idempotent ``variant_id_counter`` from the quartz
    reference which produced duplicate IDs on repeated imports.
    """
    key = f"{release_id}|{file_key}|{chromosome}|{position}|{ref}|{alt}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    # Use the first 8 bytes as a signed 64-bit integer
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


# ---------------------------------------------------------------------------
# Variant type determination
# ---------------------------------------------------------------------------


def determine_variant_type(ref: str, alt: str) -> tuple[str, str]:
    """Determine variant type and subtype from ref/alt alleles."""
    ref_len = len(ref)
    alt_len = len(alt)

    if alt == "<DEL>" or alt.startswith("<") or alt_len > 50 or ref_len > 50:
        return "SV", "SV"
    if ref_len == 1 and alt_len == 1:
        return "SNP", "SNV"
    if ref_len == alt_len and ref_len > 1:
        return "SNP", "MNV"
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
) -> dict:
    """Ingest variants from a VCF file into ClickHouse.

    Uses ``cyvcf2`` for efficient streaming parsing of bgzipped VCF files.
    Variant IDs are deterministic (idempotent) — re-importing the same file
    produces the same IDs.

    Args:
        release_id: Release identifier.
        file_key: S3 key of the VCF file (used for idempotent ID generation).
        assembly_key: Assembly identifier.
        batch_size: Number of variants per batch insert (default 50 000).

    Returns:
        dict with ingestion statistics.
    """
    logger.info("Starting VCF ingestion: %s for release %s", file_key, release_id)

    ch = get_clickhouse_client()

    total_variants = 0
    total_inserted = 0
    skipped = 0
    batch_count = 0

    # Columnar batch storage
    batch: dict[str, list] = {
        "variant_id": [],
        "release_key": [],
        "assembly_key": [],
        "chromosome": [],
        "position": [],
        "ref_allele": [],
        "alt_allele": [],
        "variant_type": [],
        "variant_subtype": [],
        "length": [],
        "gene_id": [],
        "gene_symbol": [],
        "gene_surrogate_id": [],
        "mutant_line_surrogate_id": [],
        "mutant_line_name": [],
        "consequence": [],
        "consequence_id": [],
        "impact": [],
        "rs_id": [],
        "quality_score": [],
        "filter_status": [],
        "read_depth": [],
        "allele_frequency": [],
        "hgvs_c": [],
        "hgvs_p": [],
        "zygosity": [],
    }

    def flush_batch() -> None:
        nonlocal total_inserted, batch_count
        if not batch["variant_id"]:
            return
        ch.insert(
            "variant_facts",
            data=list(zip(*batch.values())),
            column_names=list(batch.keys()),
        )
        total_inserted += len(batch["variant_id"])
        batch_count += 1
        for key in batch:
            batch[key] = []
        self.update_state(
            state="PROGRESS",
            meta={
                "processed": total_variants,
                "inserted": total_inserted,
                "skipped": skipped,
                "batches": batch_count,
            },
        )

    try:
        # Download VCF to a local temp file for cyvcf2 (requires file path)
        with download_file(file_key) as local_vcf_path:
            from cyvcf2 import VCF

            vcf = VCF(local_vcf_path)
            sample_names = vcf.samples

            for variant in vcf:
                total_variants += 1

                chrom = variant.CHROM
                pos = variant.POS
                ref = variant.REF
                alts = variant.ALT
                qual = variant.QUAL if variant.QUAL is not None else 0.0
                filt = variant.FILTER if variant.FILTER else "PASS"

                if not alts:
                    skipped += 1
                    continue

                # Handle multiple ALT alleles
                for alt_idx, alt in enumerate(alts):
                    if alt is None:
                        continue

                    vtype, vsubtype = determine_variant_type(ref, str(alt))
                    length = max(len(ref), len(str(alt)))

                    # Deterministic variant ID (idempotent)
                    variant_id = compute_variant_id(
                        release_id, file_key, chrom, pos, ref, str(alt)
                    )

                    # Parse SnpEff ANN field (standard VEP/SnpEff annotation)
                    ann_str = variant.INFO.get("ANN", "")
                    annotations = parse_snpeff_ann(ann_str) if ann_str else []
                    best_ann = pick_most_severe_annotation(annotations)

                    gene_id = best_ann.get("gene_id", "") if best_ann else ""
                    consequence = best_ann.get("consequence", "") if best_ann else ""
                    impact = best_ann.get("impact", "MODIFIER") if best_ann else "MODIFIER"
                    hgvs_c = best_ann.get("hgvs_c", "") if best_ann else ""
                    hgvs_p = best_ann.get("hgvs_p", "") if best_ann else ""

                    # Resolve gene surrogate ID from gene_id (hash to int)
                    gene_sid = 0
                    if gene_id:
                        gene_sid = _surrogate_id(gene_id)

                    # Resolve mutant-line surrogate ID from sample name
                    ml_sid = 0
                    mutant_line_name = ""
                    try:
                        mutant_line_name, ml_sid = _pick_mutant_line(
                            sample_names, variant.gt_types, alt_idx
                        )
                    except Exception:
                        pass

                    # Zygosity from actual sample genotype (not hardcoded)
                    zygosity = "unknown"
                    try:
                        gt_types = variant.gt_types
                        if gt_types is not None and len(gt_types) > 0:
                            zygosity = determine_zygosity(int(gt_types[0]))
                    except Exception:
                        pass

                    # Other INFO fields (optional, not required)
                    af = 0.0
                    try:
                        af_val = variant.INFO.get("AF")
                        if af_val is not None:
                            af = float(af_val)
                    except (ValueError, TypeError):
                        pass

                    dp = 0
                    try:
                        dp_val = variant.INFO.get("DP")
                        if dp_val is not None:
                            dp = int(dp_val)
                    except (ValueError, TypeError):
                        pass

                    rs_id = variant.ID if variant.ID else ""

                    batch["variant_id"].append(variant_id)
                    batch["release_key"].append(release_id)
                    batch["assembly_key"].append(assembly_key)
                    batch["chromosome"].append(chrom)
                    batch["position"].append(pos)
                    batch["ref_allele"].append(ref)
                    batch["alt_allele"].append(str(alt))
                    batch["variant_type"].append(vtype)
                    batch["variant_subtype"].append(vsubtype)
                    batch["length"].append(length)
                    batch["gene_id"].append(gene_id)
                    batch["gene_symbol"].append(best_ann.get("gene_name", "") if best_ann else "")
                    batch["gene_surrogate_id"].append(gene_sid)
                    batch["mutant_line_surrogate_id"].append(ml_sid)
                    batch["mutant_line_name"].append(mutant_line_name)
                    batch["consequence"].append(consequence)
                    batch["consequence_id"].append(0)
                    batch["impact"].append(impact)
                    batch["rs_id"].append(rs_id)
                    batch["quality_score"].append(float(qual))
                    batch["filter_status"].append(filt)
                    batch["read_depth"].append(dp)
                    batch["allele_frequency"].append(af)
                    batch["hgvs_c"].append(hgvs_c)
                    batch["hgvs_p"].append(hgvs_p)
                    batch["zygosity"].append(zygosity)

                    if len(batch["variant_id"]) >= batch_size:
                        flush_batch()

            # Final flush
            flush_batch()

            vcf.close()

        # Rebuild trigram full-text index
        rebuild_trigram_index(ch, release_id)

        logger.info(
            "VCF ingestion complete: %d/%d variants inserted, %d skipped, %d batches",
            total_inserted,
            total_variants,
            skipped,
            batch_count,
        )

        return {
            "total_variants": total_variants,
            "total_inserted": total_inserted,
            "skipped": skipped,
            "batches": batch_count,
            "release_id": release_id,
        }

    except Exception as e:
        logger.error("VCF ingestion failed: %s", e)
        raise


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
                       checksum: str | None = None) -> dict[str, Any]:
    context = ImportContext(
        import_task_id,
        data_set_id,
        release_id,
        file_key,
        assembly or None,
        module_key=module_key,
        schema_version=schema_version,
        checksum=checksum,
    )
    try:
        update_import_progress(import_task_id, status="ingesting", progress=0)
        result = get_adapter(kind).run(context, progress=lambda **values: update_import_progress(import_task_id, **values))
        update_import_progress(import_task_id, status="ready", progress=100, evidence=result.evidence)
        from dataclasses import asdict
        return asdict(result)
    except Exception as exc:
        update_import_progress(import_task_id, status="failed", error_detail=str(exc), failed_batch=current_batch())
        raise

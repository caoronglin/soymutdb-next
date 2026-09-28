"""Data export tasks.

Supports vcf/tsv/csv/json/bed formats with optional gzip compression.
Files are uploaded to S3 and pre-signed download URLs are returned.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from celery import Task

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.tasks.ingest import get_clickhouse_client
from soymutdb_worker.utils.s3 import (
    delete_object,
    generate_presigned_url,
    list_objects,
    upload_large_file,
)

logger = logging.getLogger(__name__)

EXPORT_FORMATS = frozenset({"vcf", "tsv", "csv", "json", "bed"})
MAX_RECORDS_EXPORT = 100_000_000
EXPORT_RETENTION_DAYS = 7

# Column layout returned by build_export_query.
#
# Public-artifact contract (DB-CORE identity/assembly/release scope):
#   * an export is a *published public artifact*, so it must not carry the
#     ClickHouse surrogate keys ``gene_surrogate_id`` /
#     ``mutant_line_surrogate_id``. Those columns are internal join keys; the
#     public locators are the gene accession + symbol and the mutant line name.
#   * every artifact states the release and assembly it was built from
#     (``release_key``/``assembly_key``), so a downloaded file can never be
#     mistaken for another release's coordinate namespace.
EXPORT_COLUMNS = [
    # Provenance.
    "release_key",
    "assembly_key",
    # Variant locus and call.
    "chromosome",
    "position",
    "variant_id",
    "ref_allele",
    "alt_allele",
    "variant_type",
    "variant_subtype",
    "impact",
    "quality_score",
    "allele_frequency",
    "zygosity",
    # Public gene/mutant locators (never the surrogate keys).
    "gene_id",
    "gene_symbol",
    "mutant_line_name",
    "hgvs_c",
    "hgvs_p",
    "read_depth",
    "filter_status",
]

#: Columns that must never appear in a published export artifact.
FORBIDDEN_EXPORT_COLUMNS = frozenset(
    {"gene_surrogate_id", "mutant_line_surrogate_id"}
)

if FORBIDDEN_EXPORT_COLUMNS.intersection(EXPORT_COLUMNS):  # pragma: no cover
    raise RuntimeError(
        "EXPORT_COLUMNS must not carry internal surrogate ids: "
        f"{sorted(FORBIDDEN_EXPORT_COLUMNS.intersection(EXPORT_COLUMNS))}"
    )


def build_export_query(filters: dict) -> tuple[str, dict]:
    """Build a parameterised ClickHouse query from export filters.

    All user values are bound via ``%(name)s`` placeholders — never
    interpolated into the SQL string.
    """
    conditions: list[str] = []
    params: dict = {}

    if filters.get("release_key"):
        conditions.append("release_key = %(release_key)s")
        params["release_key"] = filters["release_key"]

    if filters.get("assembly"):
        conditions.append("assembly_key = %(assembly)s")
        params["assembly"] = filters["assembly"]

    if filters.get("chromosome"):
        conditions.append("chromosome = %(chromosome)s")
        params["chromosome"] = filters["chromosome"]

    if filters.get("start") is not None:
        conditions.append("position >= %(start)s")
        params["start"] = filters["start"]

    if filters.get("end") is not None:
        conditions.append("position <= %(end)s")
        params["end"] = filters["end"]

    if filters.get("ref"):
        conditions.append("ref_allele = %(ref)s")
        params["ref"] = filters["ref"]

    if filters.get("alt"):
        conditions.append("alt_allele = %(alt)s")
        params["alt"] = filters["alt"]

    if filters.get("gene_id"):
        conditions.append("gene_id = %(gene_id)s")
        params["gene_id"] = filters["gene_id"]

    if filters.get("mutant_line_id"):
        conditions.append("mutant_line_surrogate_id = %(ml_id)s")
        params["ml_id"] = filters["mutant_line_id"]

    if filters.get("variant_type"):
        conditions.append("variant_type = %(vtype)s")
        params["vtype"] = filters["variant_type"]

    if filters.get("consequence"):
        conditions.append("consequence = %(consequence)s")
        params["consequence"] = filters["consequence"]

    if filters.get("impact"):
        conditions.append("impact = %(impact)s")
        params["impact"] = filters["impact"]

    if filters.get("min_af") is not None:
        conditions.append("allele_frequency >= %(min_af)s")
        params["min_af"] = filters["min_af"]

    if filters.get("max_af") is not None:
        conditions.append("allele_frequency <= %(max_af)s")
        params["max_af"] = filters["max_af"]

    where = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
    SELECT
        {", ".join(EXPORT_COLUMNS)}
    FROM variant_facts
    WHERE {where}
    ORDER BY chromosome, position, variant_id
    """
    return query, params


def _open_output(path: Path, compress: bool):
    """Open an output file for writing, optionally gzip-compressed."""
    if compress:
        return gzip.open(str(path), "wt", newline="", encoding="utf-8")
    return open(str(path), "w", newline="", encoding="utf-8")


def _record(row) -> dict:
    """Map a ClickHouse row tuple onto EXPORT_COLUMNS by name.

    Writers address columns by name rather than by position so a reorder of
    EXPORT_COLUMNS cannot silently mislabel a published artifact.
    """
    return dict(zip(EXPORT_COLUMNS, row, strict=False))


def _write_tsv_csv(output_file, rows, delimiter: str) -> int:
    """Write rows in TSV or CSV format."""
    writer = csv.writer(
        output_file,
        delimiter=delimiter,
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerow(EXPORT_COLUMNS)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    return count


def _write_vcf(output_file, rows, provenance: dict | None = None) -> int:
    """Write rows in VCF 4.2 format.

    The release/assembly provenance is emitted as VCF header metadata so the
    file states its coordinate namespace.
    """
    output_file.write("##fileformat=VCFv4.2\n")
    output_file.write(f"##fileDate={datetime.now(UTC).strftime('%Y%m%d')}\n")
    output_file.write("##source=SoyMutDB export\n")
    for key in ("release_key", "assembly_key"):
        value = (provenance or {}).get(key)
        if value:
            output_file.write(f"##soymutdb_{key}={value}\n")
    output_file.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
    count = 0
    for row in rows:
        rec = _record(row)
        info_parts: list[str] = []
        if rec.get("impact"):
            info_parts.append(f"IMPACT={rec['impact']}")
        if rec.get("variant_type"):
            info_parts.append(f"VT={rec['variant_type']}")
        if rec.get("hgvs_c"):
            info_parts.append(f"HGVS_C={rec['hgvs_c']}")
        if rec.get("gene_id"):
            info_parts.append(f"GENE={rec['gene_id']}")
        info = ";".join(info_parts) if info_parts else "."
        output_file.write(
            f"{rec['chromosome']}\t{rec['position']}\t{rec['variant_id']}\t"
            f"{rec['ref_allele']}\t{rec['alt_allele']}\t{rec['quality_score']}\t"
            f"{rec['filter_status']}\t{info}\n"
        )
        count += 1
    return count


def _write_bed(output_file, rows) -> int:
    """Write rows in BED format.

    BED has no free metadata field, so the release/assembly provenance is
    carried in the track line and in the name column.
    """
    count = 0
    for row in rows:
        rec = _record(row)
        ref = rec.get("ref_allele")
        position = rec["position"]
        end_pos = position + max(len(str(ref)), 1) - 1
        name = f"{rec.get('gene_id') or '.'}|{rec.get('impact')}_{rec.get('variant_type')}"
        output_file.write(
            f"{rec['chromosome']}\t{position - 1}\t{end_pos}\t{name}\t0\t+\n"
        )
        count += 1
    return count


def _write_json(output_file, rows) -> int:
    """Write rows as JSON Lines (one JSON object per line)."""
    count = 0
    for row in rows:
        output_file.write(json.dumps(_record(row), default=str) + "\n")
        count += 1
    return count


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.export.export_variants",
    queue="export",
)
def export_variants(
    self: Task,
    export_id: str,
    filters: dict,
    format: str = "tsv",
    compress: bool = True,
) -> dict:
    """Export variants to a file on S3.

    Args:
        export_id: Unique export job ID.
        filters: Query filters (release_key, chromosome, start, end, etc.).
        format: Export format — one of vcf/tsv/csv/json/bed.
        compress: Whether to gzip-compress the output.

    Returns:
        dict with export metadata, S3 path, and pre-signed download URL.
    """
    if format not in EXPORT_FORMATS:
        raise ValueError(
            f"Unsupported export format: {format!r}. Allowed: {sorted(EXPORT_FORMATS)}"
        )

    logger.info("Starting export %s: %s format", export_id, format)

    ch = get_clickhouse_client()
    query, params = build_export_query(filters)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        ext = format
        filename = f"soymutdb_export_{export_id}.{ext}"
        if compress:
            filename += ".gz"
        output_path = tmpdir_path / filename

        result = ch.query(query, parameters=params)
        rows = result.result_rows

        # Fail closed on an over-budget export. MAX_RECORDS_EXPORT was declared
        # but never enforced, so a broad filter could materialise an unbounded
        # result set in the worker. The cap is checked before any bytes are
        # written so the job fails loudly instead of producing a partial file
        # that looks complete.
        if len(rows) > MAX_RECORDS_EXPORT:
            raise ValueError(
                f"Export {export_id} matched {len(rows)} records, which exceeds "
                f"the {MAX_RECORDS_EXPORT} record budget; narrow the filters "
                "(chromosome/region/impact) and resubmit."
            )

        # Provenance stamped on the artifact itself (VCF/BED headers and every
        # row of the tabular formats).
        provenance = {
            "release_key": filters.get("release_key"),
            "assembly_key": filters.get("assembly"),
        }

        record_count = 0
        output_file = _open_output(output_path, compress)
        try:
            if format == "tsv":
                record_count = _write_tsv_csv(output_file, rows, "\t")
            elif format == "csv":
                record_count = _write_tsv_csv(output_file, rows, ",")
            elif format == "vcf":
                record_count = _write_vcf(output_file, rows, provenance)
            elif format == "bed":
                record_count = _write_bed(output_file, rows)
            elif format == "json":
                record_count = _write_json(output_file, rows)

            self.update_state(
                state="PROGRESS",
                meta={"records": record_count},
            )
        finally:
            output_file.close()

        file_size = output_path.stat().st_size

        # Upload to S3 (use multipart for large files)
        s3_bucket = get_setting("S3_EXPORT_BUCKET", "exports")
        s3_path = f"exports/{export_id}/{filename}"
        upload_large_file(str(output_path), f"{s3_bucket}/{s3_path}")

        # Generate pre-signed URL (24 h)
        presigned_url = generate_presigned_url(
            f"{s3_bucket}/{s3_path}", expires_in=86400
        )

        logger.info(
            "Export %s complete: %d records, %d bytes",
            export_id,
            record_count,
            file_size,
        )

        return {
            "export_id": export_id,
            "format": format,
            "record_count": record_count,
            "file_size": file_size,
            "s3_path": s3_path,
            "download_url": presigned_url,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        }


@celery_app.task(
    name="soymutdb_worker.tasks.export.cleanup_old_exports",
    queue="cleanup",
)
def cleanup_old_exports() -> dict:
    """Remove expired export files from S3 (older than ``EXPORT_RETENTION_DAYS``).

    In production, S3 lifecycle policies are preferred; this task is a
    safety net.
    """
    logger.info("Cleaning up old exports")

    bucket = get_setting("S3_EXPORT_BUCKET", "exports")
    cutoff = datetime.now(UTC) - timedelta(days=EXPORT_RETENTION_DAYS)
    deleted = 0

    objects = list_objects(f"{bucket}/exports/")
    for obj in objects:
        last_modified = obj.get("LastModified")
        if last_modified is not None:
            # botocore returns timezone-aware datetime
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=UTC)
            if last_modified < cutoff:
                key = obj["Key"]
                delete_object(f"{bucket}/{key}")
                deleted += 1

    logger.info("Cleaned up %d old export files", deleted)
    return {"deleted": deleted}

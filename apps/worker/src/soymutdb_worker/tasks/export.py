"""Data export tasks.

Supports vcf/tsv/csv/json/bed formats with optional gzip compression.
Files are uploaded to S3; the API signs download URLs on demand.

The export *record* (owner, status, artifact key, expiry) is owned by the
API in PostgreSQL; this task advances that record: it claims the export
before the work starts and finalises it when the artifact is written or the
run fails. Finished exports are never rebuilt, and duplicate deliveries inside
the lease do not start another run. Redelivery after lease expiry fails the
record closed without starting more work. The original process may still
upload an orphan object, but its late success cannot publish a failed record.
No automatic execution retry or exactly-once delivery is promised.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from celery import Task
from soymutdb_jobs.export_artifact import (
    EXPORT_FORMATS,
    build_export_artifact_key,
    build_export_filename,
)
from soymutdb_jobs.export_errors import EXPORT_FAILED_MESSAGE
from sqlalchemy import text

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import VariantExportStore
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import (
    delete_object,
    list_objects,
    upload_large_file,
)

logger = logging.getLogger(__name__)

MAX_RECORDS_EXPORT = 100_000_000
EXPORT_RETENTION_DAYS = 7

class ExportRecordMissingError(RuntimeError):
    """The command reached the worker without its export record.

    This is a deployment inconsistency (an older API, or a migration that
    has not run yet), not a transient fault: the request cannot be
    executed, and it must fail loudly rather than disappear.
    """

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
    "mutant_public_id",
    "hgvs_c",
    "hgvs_p",
    "read_depth",
    "filter_status",
]

#: Columns that must never appear in a published export artifact.
FORBIDDEN_EXPORT_COLUMNS = frozenset(
    {"gene_surrogate_id", "mutant_line_surrogate_id", "mutant_line_name"}
)

if FORBIDDEN_EXPORT_COLUMNS.intersection(EXPORT_COLUMNS):  # pragma: no cover
    raise RuntimeError(
        "EXPORT_COLUMNS must not carry internal surrogate ids: "
        f"{sorted(FORBIDDEN_EXPORT_COLUMNS.intersection(EXPORT_COLUMNS))}"
    )


def build_export_query(filters: dict) -> tuple[str, dict]:
    """Build a native PostgreSQL query restricted to released public records.

    All user values are bound via ``:name`` placeholders — never
    interpolated into the SQL string.
    """
    if "mutant_line_id" in filters or "mutant_line_public_id" in filters:
        raise ValueError("Mutant export filters must be resolved by the API")
    release = filters.get("release_key")
    try:
        release_id = int(release)
    except (ValueError, TypeError) as error:
        raise ValueError("A resolved release identity is required for public export") from error
    if release_id < 1:
        raise ValueError("A positive release identity is required for public export")
    assembly = filters.get("assembly")
    if not isinstance(assembly, str) or not assembly.strip():
        # The task is a public entry point: anything can enqueue it. Without
        # an assembly the query would span every namespace of the release
        # while the export record advertises a single one, so the artifact
        # would mix coordinate systems under one name.
        raise ValueError(
            "An assembly namespace is required for public export: an artifact "
            "must not span assembly namespaces"
        )
    conditions = ["v.release_id = :release_id", "r.status = 'published'",
                  "v.assembly_key = :assembly",
                  "(v.mutant_line_name = '' OR ml.public_id IS NOT NULL)"]
    params = {"release_id": release_id, "assembly": assembly.strip()}
    for field, column in (
        ("chromosome", "chromosome"),
        ("ref", "ref_allele"), ("alt", "alt_allele"), ("gene_id", "gene_id"),
        ("mutant_line_name", "mutant_line_name"),
        ("variant_type", "variant_type"), ("consequence", "consequence"), ("impact", "impact"),
    ):
        value = filters.get(field)
        if value is not None:
            conditions.append(f"v.{column} = :{field}")
            params[field] = getattr(value, "value", value)
    for field, column, operator in (
        ("start", "position", ">="), ("end", "position", "<="),
        ("min_af", "allele_frequency", ">="), ("max_af", "allele_frequency", "<="),
    ):
        if filters.get(field) is not None:
            conditions.append(f"v.{column} {operator} :{field}")
            params[field] = filters[field]
    columns = [
        "CAST(v.release_id AS text) AS release_key" if name == "release_key" else
        "ml.public_id AS mutant_public_id" if name == "mutant_public_id" else f"v.{name}"
        for name in EXPORT_COLUMNS
    ]
    query = (
        "SELECT " + ", ".join(columns) + " FROM variant_facts v "
        "JOIN releases r ON r.id = v.release_id "
        "LEFT JOIN mutant_lines ml ON ml.name = v.mutant_line_name "
        "AND ml.release_id = v.release_id AND ml.is_public = true "
        "AND ml.is_deleted = false AND ml.public_id IS NOT NULL "
        "WHERE " + " AND ".join(conditions)
        + " ORDER BY v.assembly_key, v.chromosome, v.position, v.variant_id "
        "LIMIT :record_limit"
    )
    params["record_limit"] = MAX_RECORDS_EXPORT + 1
    return query, params


def _bounded_rows(rows, export_id):
    """A private temporary file may be partial; no over-budget artifact is uploaded."""
    for number, row in enumerate(rows, start=1):
        if number > MAX_RECORDS_EXPORT:
            raise ValueError(f"Export {export_id} exceeds the {MAX_RECORDS_EXPORT} record budget")
        yield row


def _open_output(path: Path, compress: bool):
    """Open an output file for writing, optionally gzip-compressed."""
    if compress:
        return gzip.open(str(path), "wt", newline="", encoding="utf-8")
    return open(str(path), "w", newline="", encoding="utf-8")


def _record(row) -> dict:
    """Map a PostgreSQL row tuple onto EXPORT_COLUMNS by name.

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


def _write_bed(output_file, rows, provenance: dict | None = None) -> int:
    """Write rows in BED format.

    BED has no free metadata field, so the release/assembly provenance is
    carried in the leading ``track`` line instead. Without it a downloaded
    file gives no hint which coordinate namespace it belongs to.
    """
    description = "; ".join(
        f"{key}={_bed_safe((provenance or {}).get(key))}"
        for key in ("release_key", "assembly_key")
        if (provenance or {}).get(key)
    )
    if description:
        output_file.write(
            f'track name="soymutdb_export" description="{description}"\n'
        )
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


def _bed_safe(value) -> str:
    """Flatten a provenance value into a single track-line token."""
    return str(value).replace('"', "'").replace("\n", " ").replace("\r", " ")


def _file_digest(path: Path) -> tuple[int, str]:
    """Return ``(size, sha256)`` without loading the artifact into memory."""
    size = 0
    digest = hashlib.sha256()
    with open(path, "rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


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
        dict with export metadata and object key (download URLs are API-owned).
    """
    if format not in EXPORT_FORMATS:
        raise ValueError(
            f"Unsupported export format: {format!r}. Allowed: {sorted(EXPORT_FORMATS)}"
        )

    logger.info("Starting export %s: %s format", export_id, format)

    # The claim is part of the work, so it runs inside the guarded phase: a
    # claim that itself fails (a database that is briefly unreachable, for
    # example) must still drive the record to a final state. Leaving it
    # outside the guard would strand the record in ``pending`` — exactly the
    # state the submitter waits on forever.
    try:
        # Claim the export record before any work.  The claim is what makes a
        # re-delivered event harmless: a finished export is never rebuilt, and
        # a live attempt keeps its claim until the lease expires.
        decision = _claim_export(export_id)
        if decision == "missing":
            # The command reached the worker without its record: the API and
            # the worker are out of step (an older API, or a migration that
            # has not run).  Failing loudly keeps the request visible instead
            # of producing no artifact, no failure and no state at all.
            logger.error(
                "Export %s has no record; the request cannot be executed", export_id
            )
            raise ExportRecordMissingError(
                f"No export record for {export_id}; the request cannot be executed"
            )
        if decision in ("skip", "expired"):
            if decision == "expired":
                logger.warning(
                    "Export %s lease expired; failed without reexecution", export_id
                )
            logger.info("Export %s is not claimable; skipping", export_id)
            return {"export_id": export_id, "status": "skipped"}

        return _run_export(self, export_id, filters, format, compress)
    except Exception:  # noqa: BLE001 — the record must reach a final state
        logger.exception("Export %s failed", export_id)
        _fail_export(export_id)
        raise


def _claim_export(export_id: str) -> str:
    """Claim the export record for this delivery.

    Returns the store's decision: ``run`` (this delivery owns the run),
    ``expired`` (a stale running record was failed without reexecution),
    ``skip`` (finished, failed, or a live attempt still owns the claim) or
    ``missing`` (there is no record for this command at all).
    """
    with get_db() as session:
        store = VariantExportStore(session)
        decision = store.begin_run(export_id)
        session.commit()
    return decision


def _fail_export(export_id: str) -> None:
    """Record public failure state; the caller logs the original exception."""
    try:
        with get_db() as session:
            store = VariantExportStore(session)
            store.mark_failed(export_id, error=EXPORT_FAILED_MESSAGE)
            session.commit()
    except Exception:  # pragma: no cover — never mask the original failure
        logger.exception("Could not record the failure of export %s", export_id)


def _run_export(
    task: Task, export_id: str, filters: dict, format: str, compress: bool
) -> dict:
    """Produce the artifact and finalise the export record."""
    query, params = build_export_query(filters)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        filename = build_export_filename(export_id, format, compress)
        output_path = tmpdir_path / filename

        # Provenance stamped on the artifact itself (VCF/BED headers and every
        # row of the tabular formats).
        provenance = {
            "release_key": filters.get("release_key"),
            "assembly_key": filters.get("assembly"),
        }

        record_count = 0
        with get_db() as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            # Psycopg's server cursor bounds memory independently of result size.
            result = session.execute(text(query), params, execution_options={
                "stream_results": True, "yield_per": 1000,
            })
            rows = _bounded_rows(result, export_id)
            output_file = _open_output(output_path, compress)
            try:
                if format == "tsv":
                    record_count = _write_tsv_csv(output_file, rows, "\t")
                elif format == "csv":
                    record_count = _write_tsv_csv(output_file, rows, ",")
                elif format == "vcf":
                    record_count = _write_vcf(output_file, rows, provenance)
                elif format == "bed":
                    record_count = _write_bed(output_file, rows, provenance)
                elif format == "json":
                    record_count = _write_json(output_file, rows)
                task.update_state(state="PROGRESS", meta={"records": record_count})
            finally:
                output_file.close()
                result.close()

        file_size, artifact_sha256 = _file_digest(output_path)
        generated_at = datetime.now(UTC)

        # Upload to S3 (use multipart for large files)
        s3_bucket = get_setting("S3_EXPORT_BUCKET", "exports")
        s3_path = build_export_artifact_key(export_id, filename)
        upload_large_file(str(output_path), f"{s3_bucket}/{s3_path}")

        # The artifact stays downloadable for the export retention window;
        # the download URL itself is signed on demand by the API, so no
        # long-lived link is produced or stored here.
        expires_at = datetime.now(UTC) + timedelta(days=EXPORT_RETENTION_DAYS)
        with get_db() as session:
            store = VariantExportStore(session)
            recorded = store.mark_succeeded(
                export_id,
                artifact_path=s3_path,
                record_count=record_count,
                file_size=file_size,
                sha256=artifact_sha256,
                generated_at=generated_at,
                expires_at=expires_at,
            )
            session.commit()
        if not recorded:
            # The guarded update refused: the record is no longer running
            # (a failure or a takeover won the race).  Say so instead of
            # reporting a success the record does not carry.
            logger.warning(
                "Export %s produced %s but the record was no longer running; "
                "the artifact was not recorded",
                export_id,
                s3_path,
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
            "expires_at": expires_at.isoformat(),
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

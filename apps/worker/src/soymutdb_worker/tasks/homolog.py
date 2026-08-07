"""Homolog data ingestion: import homolog CSV files into PostgreSQL.

CSV format (header required)::

    gene_id,homolog_species,homolog_gene_id,homolog_type,source

Lines starting with ``#`` are ignored.
"""

from __future__ import annotations

import csv
import gzip as gz
import io
import logging
from typing import Any

from celery import Task

from app.models.genomic import Gene
from app.models.homolog import GeneHomolog, HomologType
from app.models.import_task import ImportTask, ImportTaskStatus
from soymutdb_worker.main import celery_app
from soymutdb_worker.tasks.ingest import BATCH_SIZE
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import stream_s3_file

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.homolog.import_homolog_csv",
    queue="ingest",
)
def import_homolog_csv(
    self: Task,
    import_task_id: int,
    file_path: str,
) -> dict[str, Any]:
    """Import homolog relationships from a CSV file stored on S3.

    Two-pass strategy:
      1. Stream through once to count total rows (for progress).
      2. Stream again, batch-inserting into ``gene_homologs``.

    Args:
        import_task_id: PK of the ``ImportTask`` row to track status.
        file_path: S3 URI of the CSV file (``s3://bucket/key``).

    Returns:
        dict with ingestion statistics.
    """
    logger.info("Starting homolog CSV import: task_id=%s file=%s", import_task_id, file_path)

    # ── Helper: open text stream from S3 ────────────────────────────────
    def _open_csv():
        s3_stream = stream_s3_file(file_path).__enter__()
        if file_path.endswith(".gz"):
            return io.TextIOWrapper(gz.GzipFile(fileobj=s3_stream), encoding="utf-8")
        return io.TextIOWrapper(s3_stream, encoding="utf-8")

    # ── Pass 1: count total rows ────────────────────────────────────────
    total_rows = 0
    text_stream = _open_csv()
    try:
        reader = csv.DictReader(text_stream)
        for row in reader:
            if any(v and v.startswith("#") for v in row.values() if v):
                continue
            total_rows += 1
    finally:
        text_stream.close()

    logger.info("Pass 1 complete: %d homolog rows to import", total_rows)

    if total_rows == 0:
        with get_db() as session:
            task = session.get(ImportTask, import_task_id)
            if task:
                task.status = ImportTaskStatus.COMPLETED.value
                task.processed_records = 0
                task.total_records = 0
                task.progress = 100
        return {"imported": 0, "skipped": 0, "total": 0}

    # ── Mark task as running ────────────────────────────────────────────
    with get_db() as session:
        task = session.get(ImportTask, import_task_id)
        if task:
            task.status = ImportTaskStatus.RUNNING.value
            task.total_records = total_rows
            task.processed_records = 0
            task.progress = 0

    # ── Pre-load valid reference sets ───────────────────────────────────
    with get_db() as session:
        existing_gene_ids: set[str] = {gid for gid, in session.query(Gene.id).all()}
    logger.info("Reference sets loaded: %d genes", len(existing_gene_ids))

    # ── Pass 2: stream, validate, batch insert ──────────────────────────
    imported = 0
    skipped = 0
    batch: list[dict[str, Any]] = []

    def flush_batch() -> None:
        nonlocal imported
        if not batch:
            return
        with get_db() as session:
            for row_data in batch:
                gid = row_data["gene_id"]
                if gid not in existing_gene_ids:
                    logger.warning("Skipping: gene_id %r not found", gid)
                    continue
                session.add(
                    GeneHomolog(
                        gene_id=gid,
                        homolog_species=row_data["homolog_species"],
                        homolog_gene_id=row_data["homolog_gene_id"],
                        homolog_type=row_data["homolog_type"],
                        source=row_data.get("source"),
                    )
                )
                imported += 1
            session.commit()
        batch.clear()

        # Update task progress
        pct = int(imported * 100 / total_rows) if total_rows else 0
        with get_db() as session:
            task = session.get(ImportTask, import_task_id)
            if task:
                task.processed_records = imported
                task.progress = pct

        self.update_state(
            state="PROGRESS",
            meta={"progress": pct, "processed": imported, "total": total_rows},
        )

    try:
        text_stream = _open_csv()
        reader = csv.DictReader(text_stream)
        for row in reader:
            gene_id = (row.get("gene_id") or "").strip()
            species = (row.get("homolog_species") or "").strip()
            hom_gene_id = (row.get("homolog_gene_id") or "").strip()
            hom_type_raw = (row.get("homolog_type") or "").strip().lower()

            if not gene_id or not species or not hom_gene_id or not hom_type_raw:
                skipped += 1
                continue

            # Validate homolog_type
            if hom_type_raw not in (HomologType.ORTHOLOG.value, HomologType.PARALOG.value):
                logger.warning(
                    "Skipping: invalid homolog_type=%r (must be ortholog/paralog)",
                    hom_type_raw,
                )
                skipped += 1
                continue

            source = (row.get("source") or "").strip() or None

            batch.append(
                {
                    "gene_id": gene_id,
                    "homolog_species": species,
                    "homolog_gene_id": hom_gene_id,
                    "homolog_type": hom_type_raw,
                    "source": source,
                }
            )

            if len(batch) >= BATCH_SIZE:
                flush_batch()

        flush_batch()
        text_stream.close()

        # Mark task as completed
        with get_db() as session:
            task = session.get(ImportTask, import_task_id)
            if task:
                task.status = ImportTaskStatus.COMPLETED.value
                task.processed_records = imported
                task.progress = 100

        logger.info(
            "Homolog CSV import complete: %d imported, %d skipped",
            imported,
            skipped,
        )
        return {"imported": imported, "skipped": skipped, "total": total_rows}

    except Exception as e:
        logger.error("Homolog CSV import failed: %s", e)
        try:
            with get_db() as session:
                task = session.get(ImportTask, import_task_id)
                if task:
                    task.status = ImportTaskStatus.FAILED.value
                    task.error_message = str(e)
        except Exception as db_err:
            logger.error("Failed to update import task status: %s", db_err)
        raise

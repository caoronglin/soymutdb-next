"""Expression data ingestion: import expression CSV files into PostgreSQL.

CSV format (header required)::

    gene_id,library_id,fpkm,tpm,raw_count

Lines starting with ``#`` are ignored.

The worker never imports API models: data writes go through narrow SQLAlchemy
Core tables (:mod:`soymutdb_worker.tables`) and the import-task status through
:class:`ImportTaskStore`, which validates every transition with the shared
``soymutdb_jobs`` state machine.
"""

from __future__ import annotations

import csv
import gzip as gz
import io
import logging
from typing import Any

from celery import Task
from sqlalchemy import insert, select

from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import ImportTaskStore
from soymutdb_worker.shared import JobStatus
from soymutdb_worker.tables import expression_data, expression_libraries, genes, utcnow
from soymutdb_worker.tasks.ingest import BATCH_SIZE
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import stream_s3_file

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.expression.import_expression_csv",
    queue="ingest",
)
def import_expression_csv(
    self: Task,
    import_task_id: int,
    file_path: str,
) -> dict[str, Any]:
    """Import expression data from a CSV file stored on S3.

    Two-pass strategy:
      1. Stream through once to count total rows (for progress).
      2. Stream again, batch-inserting into ``expression_data``.

    Args:
        import_task_id: PK of the ``ImportTask`` row to track status.
        file_path: S3 URI of the CSV file (``s3://bucket/key``).

    Returns:
        dict with ingestion statistics.
    """
    logger.info("Starting expression CSV import: task_id=%s file=%s", import_task_id, file_path)

    # ── Helper: open text stream from S3 ────────────────────────────────
    def _open_csv():
        s3_stream = stream_s3_file(file_path).__enter__()
        if file_path.endswith(".gz"):
            return io.TextIOWrapper(gz.GzipFile(fileobj=s3_stream), encoding="utf-8")
        return io.TextIOWrapper(s3_stream, encoding="utf-8")

    # ── Pass 1: count total rows ────────────────────────────────────────
    total_rows = 0
    text_stream = None
    try:
        text_stream = _open_csv()
        reader = csv.DictReader(text_stream)
        for row in reader:
            if any(v and v.startswith("#") for v in row.values() if v):
                continue
            total_rows += 1
    finally:
        if text_stream is not None:
            text_stream.close()

    logger.info("Pass 1 complete: %d expression rows to import", total_rows)

    if total_rows == 0:
        with get_db() as session:
            ImportTaskStore(session).update(
                import_task_id,
                JobStatus.SUCCEEDED,
                fields={"processed_records": 0, "total_records": 0, "progress": 100},
            )
        return {"imported": 0, "skipped": 0, "total": 0}

    # ── Mark task as running ────────────────────────────────────────────
    with get_db() as session:
        ImportTaskStore(session).update(
            import_task_id,
            JobStatus.RUNNING,
            fields={"total_records": total_rows, "processed_records": 0, "progress": 0},
        )

    # ── Pre-load valid reference sets ───────────────────────────────────
    with get_db() as session:
        existing_gene_ids: set[str] = set(
            session.execute(select(genes.c.id)).scalars().all()
        )
        existing_lib_ids: set[int] = set(
            session.execute(select(expression_libraries.c.id)).scalars().all()
        )
    logger.info(
        "Reference sets loaded: %d genes, %d expression libraries",
        len(existing_gene_ids),
        len(existing_lib_ids),
    )

    # ── Pass 2: stream, validate, batch insert ──────────────────────────
    imported = 0
    skipped = 0
    batch: list[dict[str, Any]] = []

    def flush_batch() -> None:
        nonlocal imported
        if not batch:
            return
        with get_db() as session:
            rows = [
                row
                for row in batch
                if row["gene_id"] in existing_gene_ids
                and row["library_id"] in existing_lib_ids
            ]
            for row in batch:
                if row["gene_id"] not in existing_gene_ids:
                    logger.warning("Skipping: gene_id %r not found", row["gene_id"])
                elif row["library_id"] not in existing_lib_ids:
                    logger.warning("Skipping: library_id %s not found", row["library_id"])
            if rows:
                session.execute(insert(expression_data), rows)
                imported += len(rows)
            session.commit()
        batch.clear()

        # Update task progress
        pct = int(imported * 100 / total_rows) if total_rows else 0
        with get_db() as session:
            ImportTaskStore(session).set_progress(import_task_id, imported, pct)

        self.update_state(
            state="PROGRESS",
            meta={"progress": pct, "processed": imported, "total": total_rows},
        )

    text_stream = None
    try:
        text_stream = _open_csv()
        reader = csv.DictReader(text_stream)
        for row in reader:
            gene_id = (row.get("gene_id") or "").strip()
            lib_raw = (row.get("library_id") or "").strip()

            if not gene_id or not lib_raw:
                skipped += 1
                continue

            try:
                library_id = int(lib_raw)
            except (ValueError, TypeError):
                logger.warning("Skipping: invalid library_id=%r", lib_raw)
                skipped += 1
                continue

            fpkm_raw = (row.get("fpkm") or "").strip()
            tpm_raw = (row.get("tpm") or "").strip()
            count_raw = (row.get("raw_count") or "").strip()

            batch.append(
                {
                    "gene_id": gene_id,
                    "library_id": library_id,
                    "fpkm": float(fpkm_raw) if fpkm_raw else None,
                    "tpm": float(tpm_raw) if tpm_raw else None,
                    "raw_count": int(count_raw) if count_raw else None,
                }
            )

            if len(batch) >= BATCH_SIZE:
                flush_batch()

        flush_batch()
        text_stream.close()

        # Mark task as completed
        with get_db() as session:
            ImportTaskStore(session).update(
                import_task_id,
                JobStatus.SUCCEEDED,
                fields={
                    "processed_records": imported,
                    "progress": 100,
                    "completed_at": utcnow(),
                },
            )

        logger.info(
            "Expression CSV import complete: %d imported, %d skipped",
            imported,
            skipped,
        )
        return {"imported": imported, "skipped": skipped, "total": total_rows}

    except Exception as e:
        logger.error("Expression CSV import failed: %s", e)
        try:
            with get_db() as session:
                ImportTaskStore(session).update(
                    import_task_id,
                    JobStatus.FAILED,
                    fields={"error_message": str(e)},
                )
        except Exception as db_err:
            logger.error("Failed to update import task status: %s", db_err)
        raise

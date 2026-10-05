"""Cleanup tasks.

Removes expired BLAST jobs, old export files, and temporary files from
worker local storage.  Runs on a periodic schedule via Celery Beat.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from celery import Task

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.utils.s3 import delete_object, list_objects

logger = logging.getLogger(__name__)

# Default retention periods
BLAST_RESULT_RETENTION_HOURS = int(get_setting("BLAST_RESULT_RETENTION_HOURS", "72"))
TEMP_FILE_MAX_AGE_HOURS = int(get_setting("TEMP_FILE_MAX_AGE_HOURS", "24"))
BLAST_CACHE_MAX_AGE_HOURS = int(get_setting("BLAST_CACHE_MAX_AGE_HOURS", "168"))  # 7 days


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.cleanup.cleanup_expired_blast_jobs",
    queue="cleanup",
)
def cleanup_expired_blast_jobs(self: Task) -> dict:
    """Remove expired BLAST result files from S3.

    Files older than ``BLAST_RESULT_RETENTION_HOURS`` (default 72 h) are
    deleted from the ``blast-results/`` prefix.
    """
    logger.info("Cleaning up expired BLAST jobs")

    bucket = get_setting("S3_BLAST_BUCKET", "blast-dbs")
    cutoff = datetime.now(UTC) - timedelta(hours=BLAST_RESULT_RETENTION_HOURS)
    deleted = 0

    objects = list_objects(f"{bucket}/blast-results/")
    for obj in objects:
        last_modified = obj.get("LastModified")
        if last_modified is not None:
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=UTC)
            if last_modified < cutoff:
                key = obj["Key"]
                delete_object(f"{bucket}/{key}")
                deleted += 1

    logger.info("Cleaned up %d expired BLAST result files", deleted)
    return {"deleted": deleted, "category": "blast_results"}


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.cleanup.cleanup_temp_files",
    queue="cleanup",
)
def cleanup_temp_files(self: Task) -> dict:
    """Remove old temporary files from the worker's local filesystem.

    Cleans:
    - ``/tmp`` files older than ``TEMP_FILE_MAX_AGE_HOURS``
    - BLAST cache files older than ``BLAST_CACHE_MAX_AGE_HOURS``
    """
    logger.info("Cleaning up temporary files")

    now = time.time()
    max_age_seconds = TEMP_FILE_MAX_AGE_HOURS * 3600
    deleted = 0

    # Clean /tmp
    tmp_dir = Path("/tmp")
    if tmp_dir.exists():
        for item in tmp_dir.iterdir():
            try:
                if item.is_file():
                    stat = item.stat()
                    if (now - stat.st_mtime) > max_age_seconds:
                        item.unlink(missing_ok=True)
                        deleted += 1
                elif item.is_dir() and item.name.startswith("tmp"):
                    stat = item.stat()
                    if (now - stat.st_mtime) > max_age_seconds:
                        shutil.rmtree(item, ignore_errors=True)
                        deleted += 1
            except (OSError, PermissionError):
                continue

    # Clean BLAST cache
    blast_cache = Path(get_setting("BLAST_CACHE_DIR", "/tmp/blast_cache"))
    cache_max_age = BLAST_CACHE_MAX_AGE_HOURS * 3600
    cache_deleted = 0
    if blast_cache.exists():
        for item in blast_cache.iterdir():
            try:
                stat = item.stat()
                if (now - stat.st_mtime) > cache_max_age:
                    if item.is_file():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    cache_deleted += 1
            except (OSError, PermissionError):
                continue

    logger.info(
        "Cleaned up %d temp files, %d BLAST cache files", deleted, cache_deleted
    )
    return {"temp_deleted": deleted, "cache_deleted": cache_deleted}

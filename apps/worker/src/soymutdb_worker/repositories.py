"""Narrow repositories for job status bookkeeping.

These replace the worker's old dependency on the API's ORM models
(``from app.models import …``): each store owns a single table and only the
columns the worker needs, always validating transitions with the shared
:func:`soymutdb_jobs.status.transition_allowed` state machine.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, text, update

from soymutdb_worker.shared import JobStatus, JobStatusUpdate, transition_allowed
from soymutdb_worker.tables import blast_hits, blast_jobs, import_tasks, utcnow

# ---------------------------------------------------------------------------
# DB status value ↔ shared JobStatus mapping
# ---------------------------------------------------------------------------

# ``expired`` is a BLAST-only terminal state with no shared equivalent; it
# maps to None so callers treat it like an unknown job (never re-run).
_BLAST_DB_TO_SHARED: dict[str, JobStatus] = {
    "pending": JobStatus.PENDING,
    "running": JobStatus.RUNNING,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
}
_BLAST_SHARED_TO_DB: dict[JobStatus, str] = {
    value: key for key, value in _BLAST_DB_TO_SHARED.items()
}

_IMPORT_DB_TO_SHARED: dict[str, JobStatus] = {
    "queued": JobStatus.QUEUED,
    "running": JobStatus.RUNNING,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
}
_IMPORT_SHARED_TO_DB: dict[JobStatus, str] = {
    value: key for key, value in _IMPORT_DB_TO_SHARED.items()
}

#: Decision returned by ``BlastJobStore.begin_run``.
_RUN = "run"      # transition applied, start work
_RESUME = "resume"  # already running (redelivery of a lost attempt), start work
_SKIP = "skip"    # terminal/unknown job, do not run


class BlastJobStore:
    """Narrow repository over ``blast_jobs`` (implements ``JobRecordStore``).

    All status writes are guarded by ``WHERE status = <expected>`` so two
    concurrent deliveries of the same event can never both win.
    """

    def __init__(self, session) -> None:
        self._session = session

    # -- JobRecordStore protocol -------------------------------------------

    def get_status(self, job_id: str | uuid.UUID) -> JobStatus | None:
        row = self._session.execute(
            text("SELECT status FROM blast_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        if row is None:
            return None
        return _BLAST_DB_TO_SHARED.get(row[0])

    def update_status(
        self,
        job_id: str | uuid.UUID,
        update_: JobStatusUpdate,
        *,
        expected: JobStatus | None,
    ) -> bool:
        """Validate with the shared transition matrix, then apply a guarded UPDATE."""
        current = self.get_status(job_id)
        if current is None or current != expected:
            return False
        if not transition_allowed(current, update_.status):
            return False
        db_target = _BLAST_SHARED_TO_DB.get(update_.status)
        db_expected = _BLAST_SHARED_TO_DB.get(expected)
        if db_target is None or db_expected is None:
            return False
        values: dict[str, Any] = {"status": db_target}
        if update_.last_error is not None:
            values["error_message"] = update_.last_error
        if update_.started_at is not None:
            values["started_at"] = update_.started_at
        if update_.completed_at is not None:
            values["completed_at"] = update_.completed_at
        result = self._session.execute(
            update(blast_jobs)
            .where(
                blast_jobs.c.id == str(job_id),
                blast_jobs.c.status == db_expected,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    # -- BLAST-specific helpers --------------------------------------------

    def begin_run(self, job_id: str | uuid.UUID) -> str:
        """Idempotently claim the job for execution.

        Returns ``run`` (transition applied), ``resume`` (a previous delivery
        already set ``running`` — the worker was lost, re-run safely) or
        ``skip`` (terminal/unknown job — never execute).
        """
        current = self.get_status(job_id)
        if current is None or current in (JobStatus.SUCCEEDED, JobStatus.CANCELLED):
            return _SKIP
        if current == JobStatus.RUNNING:
            return _RESUME
        if not transition_allowed(current, JobStatus.RUNNING):
            return _SKIP
        applied = self.update_status(
            job_id,
            JobStatusUpdate(status=JobStatus.RUNNING, started_at=utcnow()),
            expected=current,
        )
        return _RUN if applied else _SKIP

    def mark_succeeded(
        self,
        job_id: str | uuid.UUID,
        *,
        result_path: str,
        query_len: int | None = None,
        hit_count: int | None = None,
    ) -> bool:
        """Mark the job completed and record the S3 result path.

        ``query_len`` / ``hit_count`` come from the parsed BLAST report and
        back the results endpoint's statistics.
        """
        current = self.get_status(job_id)
        if current != JobStatus.RUNNING:
            return False
        if not transition_allowed(current, JobStatus.SUCCEEDED):
            return False
        values: dict[str, Any] = {
            "status": "completed",
            "completed_at": utcnow(),
            "result_path": result_path,
        }
        if query_len is not None:
            values["query_len"] = int(query_len)
        if hit_count is not None:
            values["hit_count"] = int(hit_count)
        result = self._session.execute(
            update(blast_jobs)
            .where(
                blast_jobs.c.id == str(job_id),
                blast_jobs.c.status == "running",
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_failed(self, job_id: str | uuid.UUID, *, error: str) -> bool:
        """Record a failure on the job record."""
        current = self.get_status(job_id)
        if current is None or not transition_allowed(current, JobStatus.FAILED):
            return False
        result = self._session.execute(
            update(blast_jobs)
            .where(
                blast_jobs.c.id == str(job_id),
                blast_jobs.c.status == _BLAST_SHARED_TO_DB[current],
            )
            .values(
                status="failed",
                error_message=error[:4000],
                completed_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))


class BlastHitStore:
    """Narrow repository over ``blast_hits`` (idempotent replace).

    Parsed HSP rows are stored with a delete-then-insert per job, all inside
    the caller's transaction: a redelivered event (same ``job_id``) can never
    leave two result sets behind.
    """

    def __init__(self, session) -> None:
        self._session = session

    def replace_hits(self, job_id: str | uuid.UUID, hits: list[dict]) -> int:
        """Delete existing rows for the job, then insert *hits*.

        ``hits`` must be plain dicts with the column names of ``blast_hits``
        (``job_id`` is added by this method).
        """
        jid = str(job_id)
        self._session.execute(
            delete(blast_hits).where(blast_hits.c.job_id == jid)
        )
        if hits:
            rows = [{**hit, "job_id": jid} for hit in hits]
            self._session.execute(insert(blast_hits), rows)
        return len(hits)


class ImportTaskStore:
    """Narrow repository over ``import_tasks`` with shared transition checks."""

    def __init__(self, session) -> None:
        self._session = session

    def get_status(self, task_id: int) -> JobStatus | None:
        row = self._session.execute(
            text("SELECT status FROM import_tasks WHERE id = :tid"),
            {"tid": task_id},
        ).first()
        if row is None:
            return None
        return _IMPORT_DB_TO_SHARED.get(row[0])

    def update(
        self,
        task_id: int,
        to_status: JobStatus,
        *,
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """Validate ``current -> to_status``, then apply a guarded UPDATE.

        ``fields`` may carry extra columns (progress, error_message, ...).
        """
        current = self.get_status(task_id)
        if current is None or not transition_allowed(current, to_status):
            return False
        values: dict[str, Any] = {"status": _IMPORT_SHARED_TO_DB[to_status]}
        if fields:
            values.update(fields)
        result = self._session.execute(
            update(import_tasks)
            .where(
                import_tasks.c.id == task_id,
                import_tasks.c.status == _IMPORT_SHARED_TO_DB[current],
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    def set_progress(self, task_id: int, processed: int, pct: int) -> None:
        """Update progress counters without changing status."""
        self._session.execute(
            update(import_tasks)
            .where(import_tasks.c.id == task_id)
            .values(processed_records=processed, progress=pct)
        )


__all__ = ["BlastHitStore", "BlastJobStore", "ImportTaskStore"]

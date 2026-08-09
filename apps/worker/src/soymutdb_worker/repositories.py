"""Narrow repositories for job status bookkeeping.

These replace the worker's old dependency on the API's ORM models
(``from app.models import …``): each store owns a single table and only the
columns the worker needs, always validating transitions with the shared
:func:`soymutdb_jobs.status.transition_allowed` state machine.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, select, text, update

from soymutdb_worker.shared import JobStatus, JobStatusUpdate, transition_allowed
from soymutdb_worker.tables import (
    analysis_jobs,
    blast_hits,
    blast_jobs,
    gwas_jobs,
    import_tasks,
    notifications,
    utcnow,
)

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

#: DB status vocabulary of ``gwas_jobs`` (BLAST-style spelling).
_GWAS_DB_TO_SHARED: dict[str, JobStatus] = {
    "pending": JobStatus.PENDING,
    "running": JobStatus.RUNNING,
    "completed": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
}
_GWAS_SHARED_TO_DB: dict[JobStatus, str] = {
    value: key for key, value in _GWAS_DB_TO_SHARED.items()
}

#: DB status vocabulary of ``analysis_jobs``: statuses are persisted with the
#: canonical shared spelling (``succeeded`` / ``failed`` / ...), matching the
#: PostgreSQL enum ``analysis_job_status_enum`` created by the API migration.
_ANALYSES_DB_TO_SHARED: dict[str, JobStatus] = {
    "pending": JobStatus.PENDING,
    "queued": JobStatus.QUEUED,
    "running": JobStatus.RUNNING,
    "succeeded": JobStatus.SUCCEEDED,
    "failed": JobStatus.FAILED,
    "cancel_requested": JobStatus.CANCEL_REQUESTED,
    "cancelled": JobStatus.CANCELLED,
}
_ANALYSES_SHARED_TO_DB: dict[JobStatus, str] = {
    value: key for key, value in _ANALYSES_DB_TO_SHARED.items()
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


class AnalysisJobStore:
    """Narrow repository over ``analysis_jobs`` (fastp and friends).

    Same guarded-status pattern as :class:`BlastJobStore`: every write is a
    conditional UPDATE keyed on the current status and validated with the
    shared transition matrix, so concurrent or re-delivered events never
    double-apply.  ``result_summary`` is a JSON document (parsed fastp
    statistics + output object keys) written by the worker on success.
    """

    def __init__(self, session) -> None:
        self._session = session

    # -- JobRecordStore protocol -------------------------------------------

    def get_status(self, job_id: str | uuid.UUID) -> JobStatus | None:
        row = self._session.execute(
            text("SELECT status FROM analysis_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        if row is None:
            return None
        return _ANALYSES_DB_TO_SHARED.get(row[0])

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
        db_target = _ANALYSES_SHARED_TO_DB.get(update_.status)
        db_expected = _ANALYSES_SHARED_TO_DB.get(expected)
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
            update(analysis_jobs)
            .where(
                analysis_jobs.c.id == str(job_id),
                analysis_jobs.c.status == db_expected,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    # -- Analyses-specific helpers -----------------------------------------

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
        result_summary: dict[str, Any],
    ) -> bool:
        """Mark the job completed and store the parsed result summary.

        ``result_summary`` is a plain-JSON dict (fastp statistics + output
        object keys); it lands in the ``result_summary`` column and backs the
        API's results endpoint.
        """
        current = self.get_status(job_id)
        if current != JobStatus.RUNNING:
            return False
        if not transition_allowed(current, JobStatus.SUCCEEDED):
            return False
        result = self._session.execute(
            update(analysis_jobs)
            .where(
                analysis_jobs.c.id == str(job_id),
                analysis_jobs.c.status == "running",
            )
            .values(
                status="succeeded",
                completed_at=utcnow(),
                result_summary=result_summary,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_failed(self, job_id: str | uuid.UUID, *, error: str) -> bool:
        """Record a scrubbed failure message on the job record."""
        current = self.get_status(job_id)
        if current is None or not transition_allowed(current, JobStatus.FAILED):
            return False
        result = self._session.execute(
            update(analysis_jobs)
            .where(
                analysis_jobs.c.id == str(job_id),
                analysis_jobs.c.status == _ANALYSES_SHARED_TO_DB[current],
            )
            .values(
                status="failed",
                error_message=error[:4000],
                completed_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))


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


class GwasJobStore:
    """Narrow repository over ``gwas_jobs`` (implements ``JobRecordStore``).

    Same guarded-status pattern as :class:`BlastJobStore`: every write is a
    conditional UPDATE keyed on the current status and validated with the
    shared transition matrix, so concurrent or re-delivered events never
    double-apply.  ``result_summary`` is a JSON document (MinIO object keys
    of the Manhattan / QQ / HTML / assoc outputs + statistics) written by
    the worker on success.
    """

    def __init__(self, session) -> None:
        self._session = session

    # -- JobRecordStore protocol -------------------------------------------

    def get_status(self, job_id: str | uuid.UUID) -> JobStatus | None:
        row = self._session.execute(
            text("SELECT status FROM gwas_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        if row is None:
            return None
        return _GWAS_DB_TO_SHARED.get(row[0])

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
        db_target = _GWAS_SHARED_TO_DB.get(update_.status)
        db_expected = _GWAS_SHARED_TO_DB.get(expected)
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
            update(gwas_jobs)
            .where(
                gwas_jobs.c.id == str(job_id),
                gwas_jobs.c.status == db_expected,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    # -- GWAS-specific helpers --------------------------------------------

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
        result_summary: dict[str, Any],
    ) -> bool:
        """Mark the job completed and store the result summary."""
        current = self.get_status(job_id)
        if current != JobStatus.RUNNING:
            return False
        if not transition_allowed(current, JobStatus.SUCCEEDED):
            return False
        result = self._session.execute(
            update(gwas_jobs)
            .where(
                gwas_jobs.c.id == str(job_id),
                gwas_jobs.c.status == "running",
            )
            .values(
                status="completed",
                completed_at=utcnow(),
                result_summary=result_summary,
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_failed(self, job_id: str | uuid.UUID, *, error: str) -> bool:
        """Record a scrubbed failure message on the job record."""
        current = self.get_status(job_id)
        if current is None or not transition_allowed(current, JobStatus.FAILED):
            return False
        result = self._session.execute(
            update(gwas_jobs)
            .where(
                gwas_jobs.c.id == str(job_id),
                gwas_jobs.c.status == _GWAS_SHARED_TO_DB[current],
            )
            .values(
                status="failed",
                error_message=error[:4000],
                completed_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))


class NotifyStore:
    """Narrow repository over ``notifications`` (worker-side writes, D2).

    The worker writes notification rows directly (same pattern as the job
    stores — never imports API models).  ``create`` is idempotent: when a
    ``link`` is given (it uniquely identifies the originating job, e.g.
    ``/blast/jobs/{id}``) an existing row for the same user + link wins and
    nothing is inserted, so redeliveries of the same job event never
    produce duplicate notifications.

    ``get_job_user_id`` resolves the owner of a job row so the trigger
    points can skip notifications for anonymous jobs (no ``user_id``).
    """

    #: Job table per trigger kind (fastp / scanpy share ``analysis_jobs``).
    _JOB_TABLES: dict[str, Any] = {
        "blast": blast_jobs,
        "fastp": analysis_jobs,
        "scanpy": analysis_jobs,
        "gwas": gwas_jobs,
    }

    def __init__(self, session) -> None:
        self._session = session

    def get_job_user_id(self, job_id: str | uuid.UUID, kind: str) -> str | None:
        """Return the owning ``user_id`` of the job, or ``None``.

        ``kind`` selects the job table (``blast`` / ``fastp`` / ``scanpy`` /
        ``gwas``); unknown kinds raise :class:`ValueError` (programming
        error, never swallowed silently).
        """
        table = self._JOB_TABLES.get(kind)
        if table is None:
            raise ValueError(f"Unknown notification job kind: {kind!r}")
        row = self._session.execute(
            select(table.c.user_id).where(table.c.id == str(job_id))
        ).first()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def create(
        self,
        *,
        user_id: str | uuid.UUID,
        type: str,
        title: str,
        body: str,
        link: str | None = None,
    ) -> bool:
        """Idempotently insert one notification row.

        Returns ``True`` when inserted, ``False`` when skipped (duplicate
        user + link already present — same job, keep the first entry).
        """
        uid = str(user_id)
        if link:
            existing = self._session.execute(
                select(notifications.c.id)
                .where(
                    notifications.c.user_id == uid,
                    notifications.c.link == link,
                )
                .limit(1)
            ).first()
            if existing is not None:
                return False
        self._session.execute(
            insert(notifications).values(
                user_id=uid,
                type=type,
                title=title,
                body=body,
                link=link,
                created_at=utcnow(),
            )
        )
        return True


__all__ = [
    "AnalysisJobStore",
    "BlastHitStore",
    "BlastJobStore",
    "GwasJobStore",
    "ImportTaskStore",
    "NotifyStore",
]

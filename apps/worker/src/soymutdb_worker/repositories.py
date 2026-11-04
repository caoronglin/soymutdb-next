"""Narrow repositories for job status bookkeeping.

These replace the worker's old dependency on the API's ORM models
(``from app.models import …``): each store owns a single table and only the
columns the worker needs, always validating transitions with the shared
:func:`soymutdb_jobs.status.transition_allowed` state machine.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from soymutdb_jobs.export_errors import EXPORT_FAILED_MESSAGE
from sqlalchemy import delete, func, insert, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB

from soymutdb_worker.shared import JobStatus, JobStatusUpdate, transition_allowed
from soymutdb_worker.tables import (
    analysis_jobs,
    blast_databases,
    blast_hits,
    blast_index_builds,
    blast_jobs,
    gwas_jobs,
    import_tasks,
    notifications,
    utcnow,
    variant_exports,
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

#: Decision returned by ``VariantExportStore.begin_run`` when the export
#: record does not exist at all.  This is not a "nothing to do" case: it
#: means the command reached the worker without its record, so the request
#: must fail loudly instead of vanishing.
_MISSING = "missing"

#: How long a running export keeps its claim.  A delivery that arrives
#: while the previous attempt is still inside this window belongs to a
#: *duplicate* dispatch, not to a lost attempt, and must not start a second
#: export of the same request. Past the window a redelivery fails the record
#: closed: process death cannot be inferred from elapsed time, so no takeover.
EXPORT_CLAIM_LEASE_SECONDS = 3600


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

    def _deadline(self, job_id: str | uuid.UUID) -> tuple[datetime | None, bool]:
        """Return ``(deadline, known)`` for the job's expiry.

        ``known`` is False when the row is missing or the deadline is absent or
        not a datetime: an unreadable deadline must never be read as "expired",
        and must never be read as "just expired now" either.
        """
        row = self._session.execute(
            text("SELECT expires_at FROM blast_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        if row is None or row[0] is None:
            return None, False
        deadline = row[0]
        if not isinstance(deadline, datetime):
            return None, False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return deadline, True

    def is_expired(self, job_id: str | uuid.UUID) -> bool:
        """True when the job's download/capability deadline has passed.

        An expired job must not be executed: its public capability and result
        download are no longer valid. NULL expiry (legacy rows) is not expired.
        """
        deadline, known = self._deadline(job_id)
        return known and deadline is not None and deadline <= datetime.now(UTC)

    def is_terminal_skip(self, job_id: str | uuid.UUID) -> bool:
        """True when the job must not be started at all.

        A cancelled/expired *row* is terminal, and so is a row whose deadline
        has passed — the worker is the last line of defence, so a late Celery
        delivery cannot start a search whose capability already lapsed.
        """
        row = self._session.execute(
            text("SELECT status FROM blast_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        if row is not None and row[0] in {"cancelled", "expired"}:
            return True
        return self.is_expired(job_id)

    def is_cancelled(self, job_id: str | uuid.UUID) -> bool:
        """True when the job row is already in a cancelled/expired terminal state."""
        row = self._session.execute(
            text("SELECT status FROM blast_jobs WHERE id = :jid"),
            {"jid": str(job_id)},
        ).first()
        return row is not None and row[0] in {"cancelled", "expired"}

    def download_ttl_seconds(
        self, job_id: str | uuid.UUID, *, cap: int = 86400
    ) -> int:
        """Remaining seconds until the job's download/capability deadline.

        ``cap`` is the hard maximum even for rows without an expiry (legacy).
        Zero or negative means no download link may be issued.
        """
        deadline, known = self._deadline(job_id)
        if deadline is None or not known:
            return max(0, cap)  # unknown deadline shape: use the hard cap
        remaining = int((deadline - datetime.now(UTC)).total_seconds())
        return max(0, min(remaining, cap))

    def mark_expired(self, job_id: str | uuid.UUID) -> bool:
        """Guardedly close a pending/running job whose deadline has passed."""
        result = self._session.execute(
            update(blast_jobs)
            .where(
                blast_jobs.c.id == str(job_id),
                blast_jobs.c.status.in_(["pending", "running"]),
            )
            .values(status="expired", completed_at=utcnow(),
                    error_message="BLAST job expired before completion")
        )
        return bool(getattr(result, "rowcount", 0))

    def request_retry(self, job_id: str | uuid.UUID) -> bool:
        """Reset a FAILED job to PENDING for one explicit retry.

        Only ``failed`` is retryable: completed/cancelled/expired jobs are
        terminal (a new job must be submitted instead). The caller owns the
        outbox re-dispatch; this method never fabricates a new execution.
        """
        result = self._session.execute(
            update(blast_jobs)
            .where(blast_jobs.c.id == str(job_id), blast_jobs.c.status == "failed")
            .values(status="pending", error_message=None, started_at=None,
                    completed_at=None, result_path=None, hit_count=0, query_len=None)
        )
        return bool(getattr(result, "rowcount", 0))

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
        execution_metadata: dict | None = None,
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
        if execution_metadata is not None:
            values["parameters"] = func.coalesce(
                blast_jobs.c.parameters, literal({}, type_=JSONB)
            ).op("||")(literal({"_execution": execution_metadata}, type_=JSONB))
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
            rows = [
                {**hit, "hsp_num": number, "job_id": jid}
                for number, hit in enumerate(hits, 1)
            ]
            self._session.execute(insert(blast_hits), rows)
        return len(hits)


class VariantExportStore:
    """Narrow repository over ``variant_exports``.

    The API owns the record (owner, provenance, requested filters); the worker
    only advances the lifecycle and records the produced artifact.  Every
    write is a guarded UPDATE keyed on the current status. Redeliveries do
    not start another execution or overwrite terminal records through this
    store; external object writes are not a database transaction.

    ``status`` uses the shared job vocabulary directly
    (``pending``/``running``/``succeeded``/``failed``) — the same spelling the
    API stores, so the two sides cannot drift.
    """

    def __init__(self, session) -> None:
        self._session = session

    def get_status(self, export_id: str | uuid.UUID) -> JobStatus | None:
        row = self._session.execute(
            text("SELECT status FROM variant_exports WHERE id = :eid"),
            {"eid": str(export_id)},
        ).first()
        if row is None:
            return None
        try:
            return JobStatus(row[0])
        except ValueError:
            return None

    def get_claim_state(
        self, export_id: str | uuid.UUID
    ) -> tuple[JobStatus | None, datetime | None]:
        """Return the record's status and when the current attempt started."""
        row = self._session.execute(
            text("SELECT status, started_at FROM variant_exports WHERE id = :eid"),
            {"eid": str(export_id)},
        ).first()
        if row is None:
            return None, None
        try:
            status = JobStatus(row[0])
        except ValueError:
            return None, None
        return status, row[1]

    def begin_run(self, export_id: str | uuid.UUID) -> str:
        """Idempotently claim the export for execution.

        Returns ``run`` (claimed now), ``expired`` (stale running record
        failed closed), ``skip`` (terminal or a live attempt owns the claim),
        or ``missing`` (the record does not exist at all).

        A *failed* export is never re-run: this batch ships no automatic
        execution retry and no manual retry endpoint, so a failure is the
        submitter's final answer.

        A delivery that arrives while the previous attempt is still inside
        its lease is a **duplicate dispatch**, not a lost attempt: the
        outbox is at-least-once, so the same command can be handed to the
        broker twice.  Such a delivery must not start a second export of
        the same request — that would duplicate the work and race the
        ``mark_succeeded`` update. A redelivery after the lease instead
        fails the record without starting work. The original process may
        still be alive; its late success cannot overwrite the failed state.
        Users recover by submitting a new export, never automatic replay.
        """
        current, started_at = self.get_claim_state(export_id)
        if current is None:
            return _MISSING
        if current in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            return _SKIP
        if current == JobStatus.RUNNING:
            lease_until = utcnow() - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS)
            if started_at is not None and started_at > lease_until:
                return _SKIP  # a live attempt still owns the claim
            return "expired" if self._expire_run(export_id, started_at) else _SKIP
        if not transition_allowed(current, JobStatus.RUNNING):
            return _SKIP
        applied = self.update_status(
            export_id,
            JobStatusUpdate(status=JobStatus.RUNNING, started_at=utcnow()),
            expected=current,
        )
        return _RUN if applied else _SKIP

    def _expire_run(
        self, export_id: str | uuid.UUID, observed_started_at: datetime | None
    ) -> bool:
        """Fail the observed stale claim without starting a second execution.

        Guard both status and timestamp, so an intervening success or lease
        change is never overwritten. NULL timestamps are fail-closed too.
        """
        result = self._session.execute(
            update(variant_exports)
            .where(
                variant_exports.c.id == str(export_id),
                variant_exports.c.status == JobStatus.RUNNING.value,
                variant_exports.c.started_at.is_not_distinct_from(observed_started_at),
            )
            .values(
                status=JobStatus.FAILED.value,
                error_message=EXPORT_FAILED_MESSAGE,
                completed_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def update_status(
        self,
        export_id: str | uuid.UUID,
        update_: JobStatusUpdate,
        *,
        expected: JobStatus | None,
    ) -> bool:
        """Validate with the shared transition matrix, then apply a guarded UPDATE."""
        current = self.get_status(export_id)
        if current is None or current != expected:
            return False
        if not transition_allowed(current, update_.status):
            return False
        values: dict[str, Any] = {
            "status": update_.status.value,
            "updated_at": utcnow(),
        }
        if update_.last_error is not None:
            values["error_message"] = update_.last_error[:4000]
        if update_.started_at is not None:
            values["started_at"] = update_.started_at
        if update_.completed_at is not None:
            values["completed_at"] = update_.completed_at
        result = self._session.execute(
            update(variant_exports)
            .where(
                variant_exports.c.id == str(export_id),
                variant_exports.c.status == expected.value,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_succeeded(
        self,
        export_id: str | uuid.UUID,
        *,
        artifact_path: str,
        sha256: str | None = None,
        generated_at=None,
        record_count: int,
        file_size: int,
        expires_at: datetime,
    ) -> bool:
        """Record the finished artifact (object key, size, expiry)."""
        current = self.get_status(export_id)
        if current != JobStatus.RUNNING:
            return False
        if not transition_allowed(current, JobStatus.SUCCEEDED):
            return False
        result = self._session.execute(
            update(variant_exports)
            .where(
                variant_exports.c.id == str(export_id),
                variant_exports.c.status == JobStatus.RUNNING.value,
            )
            .values(
                status=JobStatus.SUCCEEDED.value,
                artifact_path=artifact_path,
                record_count=int(record_count),
                file_size=int(file_size),
                sha256=sha256,
                generated_at=generated_at,
                completed_at=utcnow(),
                expires_at=expires_at,
                updated_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def mark_failed(self, export_id: str | uuid.UUID, *, error: str) -> bool:
        """Record a failure so the submitter sees a final state, not a spinner."""
        current = self.get_status(export_id)
        if current is None or not transition_allowed(current, JobStatus.FAILED):
            return False
        result = self._session.execute(
            update(variant_exports)
            .where(
                variant_exports.c.id == str(export_id),
                variant_exports.c.status == current.value,
            )
            .values(
                status=JobStatus.FAILED.value,
                error_message=error[:4000],
                completed_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))


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
    "BlastIndexBuildStore",
    "BlastJobStore",
    "GwasJobStore",
    "ImportTaskStore",
    "NotifyStore",
]


class BlastIndexBuildStore:
    """Narrow repository over ``blast_index_builds``.

    Every state write is a guarded conditional UPDATE validated by the shared
    BLAST catalog state machine, so duplicate outbox deliveries cannot advance
    a build twice or publish a stale identity. Failure reasons are sanitized
    (no paths, no child stderr, no sequences).
    """

    def __init__(self, session) -> None:
        self._session = session

    def get_state(self, build_id: str | uuid.UUID) -> tuple[str, dict] | None:
        row = self._session.execute(
            select(
                blast_index_builds.c.state,
                blast_index_builds.c.build_metadata,
                blast_index_builds.c.source_object_key,
                blast_index_builds.c.db_type,
                blast_index_builds.c.index_identity,
                blast_index_builds.c.database_id,
            ).where(blast_index_builds.c.id == str(build_id))
        ).first()
        if row is None:
            return None
        state, metadata, key, db_type, identity, database_id = row
        return state, {
            "build_metadata": metadata or {}, "source_object_key": key, "db_type": db_type,
            "index_identity": identity, "database_id": database_id,
        }

    def expire_stale_claim(self, build_id: str | uuid.UUID, lease_seconds: int) -> bool:
        """Close a claim whose worker died, without starting another build."""
        row = self._session.execute(
            select(blast_index_builds.c.state, blast_index_builds.c.started_at).where(
                blast_index_builds.c.id == str(build_id)
            )
        ).first()
        if row is None or row[0] not in {"building", "validating"}:
            return False
        started_at = row[1]
        if started_at is None:
            return False
        if started_at.tzinfo is None:
            from datetime import UTC

            started_at = started_at.replace(tzinfo=UTC)
        if (utcnow() - started_at).total_seconds() < lease_seconds:
            return False
        result = self._session.execute(
            update(blast_index_builds)
            .where(
                blast_index_builds.c.id == str(build_id),
                blast_index_builds.c.state == row[0],
                blast_index_builds.c.started_at == started_at,
            )
            .values(
                state="failed",
                error_message="build attempt lost (claim lease expired)",
                completed_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    def transition(
        self,
        build_id: str | uuid.UUID,
        target: str,
        *,
        expected: str,
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """Apply one legal state step only if the row is still at *expected*."""
        from soymutdb_jobs.blast_catalog import build_transition_allowed, validate_build_state

        validate_build_state(target)
        if not build_transition_allowed(expected, target):
            return False
        now = utcnow()
        values: dict[str, Any] = {"state": target, "updated_at": now}
        if target == "building":
            values["started_at"] = now
        if target in {"published", "failed"}:
            values["completed_at"] = now
        if fields:
            values.update(fields)
        result = self._session.execute(
            update(blast_index_builds)
            .where(
                blast_index_builds.c.id == str(build_id),
                blast_index_builds.c.state == expected,
            )
            .values(**values)
        )
        return bool(getattr(result, "rowcount", 0))

    def fail(self, build_id: str | uuid.UUID, *, reason: str) -> bool:
        """Terminal failure from any non-terminal state, with a scrubbed reason."""
        current, _ = self.get_state(build_id) or (None, {})
        if current is None or current in {"published", "failed", "ready"}:
            return False
        return self.transition(
            build_id, "failed", expected=current,
            fields={"error_message": _scrub_build_error(reason)},
        )

    def publish(
        self,
        build_id: str | uuid.UUID,
        *,
        identity: str,
        source_sha256: str,
        sequence_count: int,
        total_length: int,
        database_id: int | None,
    ) -> bool:
        """Atomically publish the verified identity and bind the catalog row.

        The catalog row is updated in the same transaction: an index becomes
        searchable only when both the build record and the catalog agree.
        A published directory is never overwritten.
        """
        # ``blast_catalog.index_identity`` validates and returns the normalized
        # identity; the previous local alias named it ``validate_identity`` and
        # raised ImportError, which every caller read as "publication rejected".
        from soymutdb_jobs.blast_catalog import index_identity as validate_identity

        validate_identity(identity)
        current, _ = self.get_state(build_id) or (None, {})
        # Both builders take the ``validating -> publishing`` claim before they
        # publish, so ``publishing`` is the expected state here -- a build that
        # is still ``validating`` has not finished re-verifying its artifacts
        # and must not win the swap.
        if current != "publishing":
            return False

        # Bind the catalog row first. If the guarded UPDATE is rejected the
        # whole transaction rolls back and the build row stays ``publishing``,
        # so the caller's failure handler can close it as ``failed`` rather
        # than leaving a build marked published with no searchable index.
        if database_id is not None:
            updated = self._session.execute(
                update(blast_databases)
                .where(
                    blast_databases.c.id == database_id,
                    blast_databases.c.build_status.in_(
                        ["pending", "building", "validating"]
                    ),
                    blast_databases.c.index_version.is_(None),
                )
                .values(
                    build_status="published",
                    index_version=identity,
                    fasta_sha256=source_sha256,
                    sequence_count=sequence_count,
                    total_length=total_length,
                    engine="ncbi_blast",
                    is_active=True,
                )
            )
            if not getattr(updated, "rowcount", 0):
                raise ValueError("catalog row missing or already published")

        return self.transition(
            build_id, "published", expected="publishing",
            fields={
                "index_identity": identity,
                "source_sha256": source_sha256,
                "sequence_count": sequence_count,
                "total_length": total_length,
            },
        )


def _scrub_build_error(reason: str, *, max_len: int = 2000) -> str:
    """Operator diagnostics never echo paths, sequences or raw child stderr."""
    clean = "".join(ch for ch in reason if ch.isprintable() or ch in "\n\t")
    clean = " ".join(clean.split())
    return (clean[:max_len] or "index build failed")

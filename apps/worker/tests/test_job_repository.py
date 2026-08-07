"""Tests for the worker's narrow job repositories (no docker, no DB).

A fake sync session records executed statements and returns canned status
rows, so the transition-validation and idempotency logic can be asserted
directly against the shared state machine.
"""

from __future__ import annotations

import uuid

from soymutdb_worker.repositories import BlastJobStore, ImportTaskStore
from soymutdb_worker.shared import JobStatus, JobStatusUpdate


class _FakeResult:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Sync-session stand-in: returns configured status rows per query.

    When an UPDATE on ``blast_jobs``/``import_tasks`` sets a new status, the
    fake mutates the status rows so subsequent reads see the new state.
    """

    def __init__(self, status: str | None = "pending", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount
        self.executed: list = []

    def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        table = getattr(stmt, "table", None)
        if table is not None:
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                new_status = values["status"]
                self.status = new_status
                return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [],
            rowcount=self.rowcount,
        )


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


def _jid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# BlastJobStore: status mapping
# ---------------------------------------------------------------------------


def test_get_status_maps_db_values_to_shared_status() -> None:
    mapping = {
        "pending": JobStatus.PENDING,
        "running": JobStatus.RUNNING,
        "completed": JobStatus.SUCCEEDED,
        "failed": JobStatus.FAILED,
        "cancelled": JobStatus.CANCELLED,
    }
    for db_value, expected in mapping.items():
        store = BlastJobStore(FakeSession(status=db_value))
        assert store.get_status(_jid()) == expected


def test_get_status_returns_none_for_unknown_or_expired() -> None:
    assert BlastJobStore(FakeSession(status="expired")).get_status(_jid()) is None
    assert BlastJobStore(FakeSession(status=None)).get_status(_jid()) is None


# ---------------------------------------------------------------------------
# BlastJobStore: transitions are validated by the shared state machine
# ---------------------------------------------------------------------------


def test_update_status_applies_legal_transition() -> None:
    session = FakeSession(status="pending")
    store = BlastJobStore(session)
    applied = store.update_status(
        _jid(),
        JobStatusUpdate(status=JobStatus.RUNNING, started_at=None),
        expected=JobStatus.PENDING,
    )
    assert applied is True
    assert session.status == "running"


def test_update_status_rejects_illegal_transition() -> None:
    session = FakeSession(status="completed")
    store = BlastJobStore(session)
    # completed -> running is illegal in the shared matrix.
    applied = store.update_status(
        _jid(),
        JobStatusUpdate(status=JobStatus.RUNNING),
        expected=JobStatus.SUCCEEDED,
    )
    assert applied is False
    assert session.status == "completed"


def test_update_status_rejects_when_expected_mismatch() -> None:
    session = FakeSession(status="running")
    store = BlastJobStore(session)
    applied = store.update_status(
        _jid(),
        JobStatusUpdate(status=JobStatus.SUCCEEDED),
        expected=JobStatus.PENDING,  # row is actually running
    )
    assert applied is False


# ---------------------------------------------------------------------------
# BlastJobStore: idempotent begin_run
# ---------------------------------------------------------------------------


def test_begin_run_transitions_pending_to_running() -> None:
    session = FakeSession(status="pending")
    decision = BlastJobStore(session).begin_run(_jid())
    assert decision == "run"
    assert session.status == "running"


def test_begin_run_skips_terminal_jobs() -> None:
    assert BlastJobStore(FakeSession(status="completed")).begin_run(_jid()) == "skip"
    assert BlastJobStore(FakeSession(status="cancelled")).begin_run(_jid()) == "skip"
    assert BlastJobStore(FakeSession(status=None)).begin_run(_jid()) == "skip"


def test_begin_run_resumes_after_lost_worker() -> None:
    """Redelivery of the same event while status=running must proceed."""
    assert BlastJobStore(FakeSession(status="running")).begin_run(_jid()) == "resume"


def test_begin_run_allows_retry_from_failed() -> None:
    session = FakeSession(status="failed")
    decision = BlastJobStore(session).begin_run(_jid())
    assert decision == "run"
    assert session.status == "running"


def test_begin_run_loses_race_without_side_effects() -> None:
    session = FakeSession(status="pending", rowcount=0)
    decision = BlastJobStore(session).begin_run(_jid())
    assert decision == "skip"


# ---------------------------------------------------------------------------
# BlastJobStore: completion / failure guards
# ---------------------------------------------------------------------------


def test_mark_succeeded_only_from_running() -> None:
    session = FakeSession(status="running")
    assert (
        BlastJobStore(session).mark_succeeded(
            _jid(), result_path="s3://blast-results/x.json"
        )
        is True
    )
    assert session.status == "completed"

    assert (
        BlastJobStore(FakeSession(status="pending")).mark_succeeded(_jid(), result_path="x")
        is False
    )
    assert (
        BlastJobStore(FakeSession(status=None)).mark_succeeded(_jid(), result_path="x")
        is False
    )


def test_mark_failed_allowed_from_pending_and_running() -> None:
    for current in ("pending", "running"):
        session = FakeSession(status=current)
        assert BlastJobStore(session).mark_failed(_jid(), error="boom") is True
        assert session.status == "failed"

    assert BlastJobStore(FakeSession(status="completed")).mark_failed(_jid(), error="x") is False


# ---------------------------------------------------------------------------
# ImportTaskStore
# ---------------------------------------------------------------------------


def test_import_store_queued_to_running() -> None:
    session = FakeSession(status="queued")
    assert ImportTaskStore(session).update(1, JobStatus.RUNNING) is True
    assert session.status == "running"


def test_import_store_noop_success_from_queued() -> None:
    session = FakeSession(status="queued")
    assert ImportTaskStore(session).update(1, JobStatus.SUCCEEDED) is True
    assert session.status == "completed"


def test_import_store_running_to_completed_or_failed() -> None:
    assert ImportTaskStore(FakeSession(status="running")).update(1, JobStatus.SUCCEEDED) is True
    assert ImportTaskStore(FakeSession(status="running")).update(1, JobStatus.FAILED) is True


def test_import_store_rejects_illegal_or_unknown() -> None:
    # completed -> running is illegal.
    session = FakeSession(status="completed")
    assert ImportTaskStore(session).update(1, JobStatus.RUNNING) is False
    assert session.status == "completed"
    # Unknown task (no row) -> no-op.
    assert ImportTaskStore(FakeSession(status=None)).update(99, JobStatus.FAILED) is False


def test_import_store_update_carries_extra_fields() -> None:
    session = FakeSession(status="running")
    assert (
        ImportTaskStore(session).update(
            1, JobStatus.SUCCEEDED, fields={"progress": 100, "error_message": None}
        )
        is True
    )
    assert session.status == "completed"

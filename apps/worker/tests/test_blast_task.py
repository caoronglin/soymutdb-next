"""BLAST task idempotency and job-status tests (no docker, no DB).

Runs the real ``run_blast`` task against a fake sync session and mocked
BLAST/S3 internals: re-deliveries of the same event (same idempotency key)
must be skipped, the job must advance pending -> running -> completed /
failed, and the payload contract must be validated.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload
from soymutdb_worker.tasks import blast as blast_module


class _FakeResult:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


class FakeSession:
    def __init__(self, status: str | None = "pending", rowcount: int = 1):
        self.status = status
        self.rowcount = rowcount

    def execute(self, stmt, params=None):
        table = getattr(stmt, "table", None)
        if table is not None:
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:
                self.status = values["status"]
                return _FakeResult([], rowcount=self.rowcount)
        return _FakeResult(
            [(self.status,)] if self.status is not None else [], rowcount=self.rowcount
        )


class FakeTask:
    def __init__(self):
        self.states = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


def _call_task(task: Any, *args, **kwargs):
    """Invoke the raw task function (bypassing Celery's bound-task wrapper)."""
    return task.run.__func__(*args, **kwargs)


def _payload(job_id: str | None = None, task_name: str = BLAST_RUN_TASK) -> dict:
    job_id = job_id or str(uuid.uuid4())
    now = datetime.now(UTC)
    p = JobPayload(
        job_id=job_id,
        task_name=task_name,
        payload={
            "job_id": job_id,
            "program": "blastn",
            "database": "williams82_cds",
            "sequence": "ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
            "evalue": 0.001,
            "max_target_seqs": 10,
        },
        idempotency_key=f"blast:{job_id}",
        created_at=now,
        updated_at=now,
    )
    return p.model_dump(mode="json")


@contextmanager
def _fake_db(session: FakeSession):
    yield session


def _monkeypatch_execution(monkeypatch, *, fail: bool = False) -> None:
    monkeypatch.setattr(blast_module, "get_blast_db_path", lambda db: "/tmp/db")
    if fail:

        def boom(*args, **kwargs):
            raise RuntimeError("blast binary exploded")

        monkeypatch.setattr(blast_module, "run_blast_command", boom)
    else:
        monkeypatch.setattr(blast_module, "run_blast_command", lambda **kw: None)
    monkeypatch.setattr(
        blast_module,
        "parse_blast_json",
        lambda path: {"hits": [], "total_hits": 0, "query_len": 0},
    )
    monkeypatch.setattr(blast_module, "upload_file", lambda *a, **k: None)
    monkeypatch.setattr(
        blast_module, "generate_presigned_url", lambda *a, **k: "https://s3.example/x"
    )


def test_redelivery_of_completed_job_is_skipped(monkeypatch) -> None:
    """Idempotency: same event re-sent after completion must not re-run."""
    payload = _payload()
    session = FakeSession(status="completed")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    # If the task actually re-runs BLAST, this raises.
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True
    assert session.status == "completed"


def test_cancelled_job_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="cancelled")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_missing_job_row_is_skipped(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status=None)
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["skipped"] is True


def test_successful_run_advances_status_to_completed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert result["total_hits"] == 0
    assert result["result_s3_path"] == "blast-results/" + payload["payload"]["job_id"] + ".json"
    # pending -> running -> completed
    assert session.status == "completed"


def test_failed_run_marks_job_failed(monkeypatch) -> None:
    payload = _payload()
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch, fail=True)

    with pytest.raises(RuntimeError, match="blast binary exploded"):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)

    assert session.status == "failed"


def test_wrong_task_name_in_payload_is_rejected() -> None:
    payload = _payload(task_name="soymutdb_worker.tasks.blast.run_blast.other")
    with pytest.raises(ValueError, match="does not match"):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)


def test_unknown_payload_version_is_rejected() -> None:
    payload = _payload()
    payload["payload_version"] = 999
    with pytest.raises(Exception):
        _call_task(blast_module.run_blast, FakeTask(), payload=payload)


def test_legacy_kwargs_dispatch_still_works(monkeypatch) -> None:
    """Direct dispatch with plain kwargs (pre-outbox callers) keeps working."""
    job_id = str(uuid.uuid4())
    session = FakeSession(status="pending")
    monkeypatch.setattr(blast_module, "get_db", lambda: _fake_db(session))
    _monkeypatch_execution(monkeypatch)

    result = _call_task(
        blast_module.run_blast,
        FakeTask(),
        job_id=job_id,
        program="blastn",
        database="williams82_cds",
        sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
    )

    assert result["total_hits"] == 0
    assert session.status == "completed"


def test_legacy_kwargs_require_job_id() -> None:
    with pytest.raises(TypeError):
        _call_task(blast_module.run_blast, FakeTask(), program="blastn")

"""Tests for the shared JobPayload schema and JobRecordStore interface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from soymutdb_jobs.schemas import JobPayload, JobStatusUpdate
from soymutdb_jobs.status import JobStatus


def _make_payload(**overrides) -> JobPayload:
    now = datetime.now(UTC)
    values = {
        "job_id": uuid.uuid4(),
        "task_name": "soymutdb_worker.tasks.blast.run_blast",
        "payload": {"sequence": "ATGC"},
        "idempotency_key": "blast:job-1",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return JobPayload(**values)


def test_payload_defaults() -> None:
    p = _make_payload()
    assert p.payload_version == 1
    assert p.attempt_count == 0
    assert p.max_attempts == 1
    assert p.status == JobStatus.PENDING
    assert p.last_error is None


def test_payload_rejects_future_payload_version() -> None:
    with pytest.raises(ValidationError, match="newer than the supported version"):
        _make_payload(payload_version=999)


def test_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _make_payload(surprise="field")


def test_payload_serializes_to_plain_json() -> None:
    p = _make_payload()
    data = p.model_dump(mode="json")
    assert isinstance(data["job_id"], str)
    assert isinstance(data["created_at"], str)
    assert data["status"] == "pending"
    # Round-trip through JSON keeps every field.
    assert JobPayload.model_validate(data) == p


def test_payload_to_task_kwargs_uses_payload_key() -> None:
    p = _make_payload()
    kwargs = p.to_task_kwargs()
    assert set(kwargs) == {"payload"}
    assert JobPayload.model_validate(kwargs["payload"]) == p


def test_status_update_defaults() -> None:
    u = JobStatusUpdate(status=JobStatus.RUNNING)
    assert u.last_error is None
    assert u.started_at is None
    assert u.completed_at is None


def test_status_update_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JobStatusUpdate.model_validate(
            {"status": JobStatus.RUNNING.value, "nope": 1}
        )


def test_payload_roundtrip_preserves_idempotency_key() -> None:
    key = "blast:job-7"
    p = _make_payload(idempotency_key=key)
    assert JobPayload.model_validate(p.model_dump(mode="json")).idempotency_key == key


def test_import_draft_source_row_key_is_stable_and_scoped_to_the_physical_row() -> None:
    """Editable source identity must not depend on mutable business values."""
    from soymutdb_jobs.import_studio import source_row_key

    draft_id = uuid.UUID("de2593ee-ff7f-4074-b2e1-b0f727c66177")

    first = source_row_key(draft_id, 2)

    assert first == source_row_key(str(draft_id), 2)
    assert first != source_row_key(draft_id, 3)
    assert first != source_row_key(uuid.uuid4(), 2)
    assert len(first) == 64


@pytest.mark.parametrize("row_number", [0, -1])
def test_import_draft_source_row_key_rejects_non_physical_rows(row_number: int) -> None:
    from soymutdb_jobs.import_studio import source_row_key

    with pytest.raises(ValueError, match="row_number"):
        source_row_key(uuid.uuid4(), row_number)

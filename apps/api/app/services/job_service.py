"""Job payload construction and transition validation (shared contract)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from soymutdb_jobs.schemas import JobPayload  # noqa: E402
from soymutdb_jobs.status import JobStatus, transition_allowed  # noqa: E402

from ..core.exceptions import ValidationError  # noqa: E402
from ..core.jobs_package import ensure_jobs_package  # noqa: F401  (sys.path bootstrap)

__all__ = ["build_job_payload", "validate_transition", "JobStatus"]


def build_job_payload(
    *,
    job_id: str | uuid.UUID,
    task_name: str,
    payload: dict[str, Any],
    idempotency_key: str,
    status: JobStatus = JobStatus.PENDING,
    attempt_count: int = 0,
    max_attempts: int = 1,
) -> JobPayload:
    """Build a versioned, idempotent job payload for an outbox event.

    ``payload`` must contain plain JSON-able values only (no ORM objects, no
    absolute filesystem paths).
    """
    now = datetime.now(UTC)
    return JobPayload(
        job_id=uuid.UUID(str(job_id)),
        task_name=task_name,
        payload=payload,
        idempotency_key=idempotency_key,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        created_at=now,
        updated_at=now,
        status=status,
    )


def validate_transition(current: JobStatus, target: JobStatus) -> JobStatus:
    """Validate a status transition through the shared state machine.

    Raises the API's ``ValidationError`` for illegal transitions so callers
    surface a proper error envelope instead of a bare assertion.
    """
    if not transition_allowed(current, target):
        raise ValidationError(
            f"Illegal job status transition: {current.value} -> {target.value}"
        )
    return target

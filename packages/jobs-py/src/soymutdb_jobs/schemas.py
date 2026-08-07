"""Shared job payload schema and job-record store interface.

``JobPayload`` is the canonical envelope for outbox events and Celery task
kwargs: it carries identity (``job_id``), routing (``task_name``), versioning
(``payload_version``), idempotency (``idempotency_key``) and retry bookkeeping
(``attempt_count`` / ``max_attempts``).  Only plain JSON-able types live in
``payload`` — never ORM objects or filesystem paths.

``JobRecordStore`` is the interface a system of record must implement so the
worker can advance job status without importing API models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contract import PAYLOAD_VERSION
from .status import JobStatus

__all__ = ["JobPayload", "JobStatusUpdate", "JobRecordStore", "PAYLOAD_VERSION"]


class JobPayload(BaseModel):
    """Versioned, idempotent description of a job to be executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: uuid.UUID = Field(description="Identifier of the job record.")
    task_name: str = Field(description="Celery task name (see soymutdb_jobs.contract).")
    payload_version: int = PAYLOAD_VERSION
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific arguments (plain JSON values only).",
    )
    idempotency_key: str = Field(
        description="Stable key identifying one logical execution; the worker "
        "must not apply a job twice for the same key."
    )
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=1, ge=1)
    last_error: str | None = None
    created_at: datetime = Field(description="UTC creation time.")
    updated_at: datetime = Field(description="UTC last-update time.")
    status: JobStatus = JobStatus.PENDING

    @field_validator("payload_version")
    @classmethod
    def _validate_payload_version(cls, value: int) -> int:
        if value > PAYLOAD_VERSION:
            raise ValueError(
                f"payload_version {value} is newer than the supported version "
                f"{PAYLOAD_VERSION}; refusing to run with an unknown contract"
            )
        return value

    def to_task_kwargs(self) -> dict[str, Any]:
        """Return the kwargs to pass to ``celery.send_task``."""
        return {"payload": self.model_dump(mode="json")}


class JobStatusUpdate(BaseModel):
    """Field-level update for a job record (used by ``JobRecordStore``)."""

    model_config = ConfigDict(extra="forbid")

    status: JobStatus
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@runtime_checkable
class JobRecordStore(Protocol):
    """Interface for advancing job status in the system of record.

    Implementations are narrow repositories: they know the schema of the job
    table they own and nothing else.  All transitions must be validated with
    :func:`soymutdb_jobs.status.transition_allowed` before being applied.
    """

    def get_status(self, job_id: str | uuid.UUID) -> JobStatus | None:
        """Return the current status, or ``None`` when the job is unknown."""
        ...

    def update_status(
        self,
        job_id: str | uuid.UUID,
        update: JobStatusUpdate,
        *,
        expected: JobStatus | None,
    ) -> bool:
        """Apply *update* only when the current status equals *expected*.

        Returns ``True`` when the row was updated (the caller won the race);
        ``False`` when the expected-status guard did not match.
        """
        ...

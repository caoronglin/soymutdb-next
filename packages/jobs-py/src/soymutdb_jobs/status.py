"""Job status enumeration and transition validation (shared contract).

The API writes job records; the worker advances them.  Both sides must
agree on the status vocabulary and the legal transitions, so the state
machine lives here and nowhere else.
"""

from __future__ import annotations

import enum
from typing import Final

__all__ = ["JobStatus", "transition_allowed", "TRANSITION_MATRIX"]


class JobStatus(enum.StrEnum):
    """Canonical job status values shared by API and worker.

    Values are strict: do not add or rename members without updating every
    consumer (API job service, worker repositories, outbox payloads).
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


#: Legal transitions.  Terminal states (``succeeded`` / ``cancelled``) have
#: no outgoing edges; ``failed`` may be re-queued or re-run (manual retry).
#: ``succeeded`` is reachable directly from ``pending``/``queued`` for
#: no-op jobs (e.g. an empty import that completes without running).
TRANSITION_MATRIX: Final[dict[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.PENDING: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.QUEUED: frozenset(
        {JobStatus.RUNNING, JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    ),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCEL_REQUESTED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED, JobStatus.RUNNING}),
    JobStatus.CANCELLED: frozenset(),
}


def transition_allowed(current: JobStatus, target: JobStatus) -> bool:
    """Return ``True`` when *target* is a legal successor of *current*."""
    return target in TRANSITION_MATRIX[current]

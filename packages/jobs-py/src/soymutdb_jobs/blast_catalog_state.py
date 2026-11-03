"""Build-state contract for immutable BLAST indexes.

PostgreSQL is authoritative for catalog visibility. The worker drives a
catalog row through a narrow, guarded state machine; only ``ready`` rows are
selectable by search. A build never mutates a published index: a changed
source, metadata or binary produces a new content-addressed identity.

The ``validating`` and ``publishing`` states are persisted so a crashed
delivery can be resumed (or failed cleanly) without leaving an index half
published. They are additive to the historical ``pending/ready/building/failed``
vocabulary, which the discovery service still reads as ``ready == runnable``.
"""
from __future__ import annotations

from typing import Final

#: Persisted ``blast_databases.build_status`` values, in lifecycle order.
PENDING: Final[str] = "pending"
BUILDING: Final[str] = "building"
VALIDATING: Final[str] = "validating"
PUBLISHING: Final[str] = "publishing"
READY: Final[str] = "ready"
FAILED: Final[str] = "failed"

#: Only ``ready`` is runnable; everything else is private to the control plane.
RUNNABLE_STATUS: Final[str] = READY

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    PENDING: frozenset({BUILDING, FAILED}),
    BUILDING: frozenset({VALIDATING, FAILED}),
    VALIDATING: frozenset({PUBLISHING, FAILED}),
    PUBLISHING: frozenset({READY, FAILED}),
    # Rebuild starts from a published row but targets a *new* identity; the
    # old row stays ready until the new one is atomically swapped in.
    READY: frozenset({BUILDING, FAILED}),
    FAILED: frozenset({BUILDING}),
}


def transition_allowed(current: str, target: str) -> bool:
    """Whether *target* is a legal successor of *current*."""
    return target in TRANSITIONS.get(current, frozenset())


def is_runnable(status: str) -> bool:
    """Only a published index may be selected for a search."""
    return status == READY


__all__ = [
    "BUILDING", "FAILED", "PENDING", "PUBLISHING", "READY", "RUNNABLE_STATUS",
    "TRANSITIONS", "VALIDATING", "is_runnable", "transition_allowed",
]

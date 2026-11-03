"""Build-state contract for immutable BLAST indexes.

PostgreSQL is authoritative for catalog visibility. The worker drives a
catalog row through a narrow, guarded state machine; only the published state
is selectable by search. A build never mutates a published index: a changed
source, metadata or binary produces a new content-addressed identity.

A crashed delivery can resume from (or fail cleanly out of) the persisted
intermediate states, so an index is never left half published.

One vocabulary, one spelling. The terminal searchable state *written* by the
current binary is ``published``; it is what the API response schema and the
OpenAPI contract already expose, and what migration 0052's check constraint
stores. ``ready`` is the legacy terminal spelling carried by catalogs built
before asynchronous indexing existed — it means the same thing to a reader, so
``SEARCHABLE_STATES`` holds both and ``is_searchable_build_state`` is the single
reader predicate. No layer may invent a third name for "published", and the
state machine never writes ``ready`` back.
"""
from __future__ import annotations

from typing import Final

#: A build was requested but no worker has claimed it yet.
PENDING: Final[str] = "pending"
#: A worker owns the build: staging, ``makeblastdb`` and the checksum inventory.
BUILDING: Final[str] = "building"
#: The produced index is being re-verified independently (``blastdbcmd``).
VALIDATING: Final[str] = "validating"
#: The guarded catalog write that makes an immutable identity searchable.
PUBLISHING: Final[str] = "publishing"
#: The published, searchable terminal state written by the current binary.
PUBLISHED: Final[str] = "published"
#: Legacy terminal spelling of pre-existing catalog rows. Readable as
#: published; never written back.
LEGACY_READY: Final[str] = "ready"
FAILED: Final[str] = "failed"

#: Persisted ``blast_databases.build_status`` values, in lifecycle order. This
#: tuple is the vocabulary the migration check constraint must accept.
STATES: Final[tuple[str, ...]] = (
    PENDING, BUILDING, VALIDATING, PUBLISHING, PUBLISHED, FAILED,
)
#: Every value the catalog column's check constraint must accept.
COLUMN_STATES: Final[tuple[str, ...]] = STATES + (LEGACY_READY,)
#: Statuses a search may select: the current spelling plus the legacy one.
SEARCHABLE_STATES: Final[frozenset[str]] = frozenset({PUBLISHED, LEGACY_READY})
#: Every state in which a build owns the row (no other worker may claim it).
IN_FLIGHT_STATES: Final[frozenset[str]] = frozenset({BUILDING, VALIDATING, PUBLISHING})
#: Status of a runnable index.
RUNNABLE_STATUS: Final[str] = PUBLISHED

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    PENDING: frozenset({BUILDING, FAILED}),
    BUILDING: frozenset({VALIDATING, FAILED}),
    VALIDATING: frozenset({PUBLISHING, FAILED}),
    PUBLISHING: frozenset({PUBLISHED, FAILED}),
    # A rebuild starts from a published row but targets a *new* identity; the
    # old row stays searchable until the new one is atomically swapped in.
    PUBLISHED: frozenset({BUILDING, FAILED}),
    FAILED: frozenset({BUILDING}),
}


def transition_allowed(current: str, target: str) -> bool:
    """Whether *target* is a legal successor of *current*."""
    return target in TRANSITIONS.get(current, frozenset())


def is_searchable_build_state(status: object) -> bool:
    """Whether a catalog row in *status* may be selected by a search.

    An unrecognised value (including ``None``) is never searchable: a state
    name that no layer defines must not read as a published index.
    """
    return isinstance(status, str) and status in SEARCHABLE_STATES


def is_runnable(status: str) -> bool:
    """Only a published index may be selected for a search."""
    return is_searchable_build_state(status)


__all__ = [
    "BUILDING", "COLUMN_STATES", "FAILED", "IN_FLIGHT_STATES", "LEGACY_READY",
    "PENDING", "PUBLISHED", "PUBLISHING", "RUNNABLE_STATUS", "SEARCHABLE_STATES",
    "STATES", "TRANSITIONS", "VALIDATING", "is_runnable",
    "is_searchable_build_state", "transition_allowed",
]

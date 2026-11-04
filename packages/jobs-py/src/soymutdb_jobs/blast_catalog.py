"""Public BLAST source attribution shared by API discovery and index manifests.

This validates metadata without fetching URLs or performing DNS lookups. It is
not an HTTP fetch policy and cannot prove a domain resolves to a public address.
"""
from __future__ import annotations

import re
from ipaddress import ip_address
from typing import Final
from urllib.parse import urlsplit

from . import blast_catalog_state as state


def public_source_url(value: object) -> str | None:
    """Omit private paths, credential URLs and known private authorities."""
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
            or "\\" in value
            or "." not in host
            or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
        ):
            return None
        _ = parsed.port
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return value
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Index build lifecycle
# ---------------------------------------------------------------------------
#
# One vocabulary for the whole catalog, re-exported from
# ``soymutdb_jobs.blast_catalog_state`` so the ORM check constraint, the worker's
# state machine and the API's wire model cannot drift into two spellings. That
# module owns ``STATES`` / ``COLUMN_STATES`` / ``TRANSITIONS``; the names below
# stay for the callers that only validate or gate on searchability.
#
# ``ready`` is the legacy spelling of a published DIAMOND index and stays a
# valid searchable value so migration 0050's existing rows keep working; the
# state machine never writes it back. New NCBI builds walk
# pending → building → validating → publishing → published, and ``failed`` is
# terminal with a recorded reason.

#: Every state the catalog column's check constraint must accept.
BUILD_STATES: Final[frozenset[str]] = frozenset(state.COLUMN_STATES)
#: Only a published index may be selected for a search.
SEARCHABLE_BUILD_STATES: Final[frozenset[str]] = frozenset(state.SEARCHABLE_STATES)
#: Immutable indexes: a rebuild produces a new ``index_version`` identity and
#: a new catalog row; an existing identity is never mutated or overwritten.
TERMINAL_BUILD_STATES: Final[frozenset[str]] = frozenset(
    {state.PUBLISHED, state.FAILED, state.LEGACY_READY}
)

#: Legal steps of the lifecycle state machine, keyed by current state. ``ready``
#: is accepted as an input (a legacy row that is still being read) but has no
#: outgoing edge: a legacy index is replaced by a new row, not re-driven.
BUILD_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    **state.TRANSITIONS,
    state.LEGACY_READY: frozenset(),
}


def validate_build_state(value: object) -> str:
    """Reject unknown build states instead of guessing their meaning."""
    if not isinstance(value, str) or value not in BUILD_STATES:
        raise ValueError(f"unknown BLAST index build state: {value!r}")
    return value


def build_transition_allowed(current: str, target: str) -> bool:
    """Return whether ``current -> target`` is a legal catalog build step."""
    validate_build_state(current)
    validate_build_state(target)
    return state.transition_allowed(current, target)


def is_searchable_build_state(value: str) -> bool:
    """A search may target only a published (or legacy-ready) index."""
    return validate_build_state(value) in SEARCHABLE_BUILD_STATES


def index_identity(value: object) -> str:
    """Validate an immutable 64-hex index identity (content-addressed)."""
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError("invalid BLAST index identity")
    return value


_IDENTITY_RE = re.compile(r"[a-f0-9]{64}\Z")

"""Public BLAST source attribution shared by API discovery and index manifests.

This validates metadata without fetching URLs or performing DNS lookups. It is
not an HTTP fetch policy and cannot prove a domain resolves to a public address.
"""
from __future__ import annotations

import re
from ipaddress import ip_address
from typing import Final
from urllib.parse import urlsplit


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
# One owner for the catalog build vocabulary: the API records and exposes it,
# the worker advances it, and both agree on which states are searchable.
# ``ready`` is the legacy spelling of a published DIAMOND index; it remains a
# valid searchable state so migration 0050's existing rows keep working.
# New NCBI builds go through the full pending → building → validating →
# published lifecycle; ``failed`` is terminal with a recorded reason.

BUILD_STATES: Final[frozenset[str]] = frozenset({
    "pending", "building", "validating", "published", "failed", "ready",
})
#: Only a published index may be selected for a search.
SEARCHABLE_BUILD_STATES: Final[frozenset[str]] = frozenset({"published", "ready"})
#: Immutable indexes: a rebuild produces a new ``index_version`` identity and
#: a new catalog row; an existing identity is never mutated or overwritten.
TERMINAL_BUILD_STATES: Final[frozenset[str]] = frozenset({"published", "failed", "ready"})

BUILD_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "pending": frozenset({"building", "failed"}),
    "building": frozenset({"validating", "failed"}),
    "validating": frozenset({"published", "failed"}),
    # A failed row is never retried in place: submit a new build that resolves
    # to a new immutable identity. Terminal states have no outgoing edges.
    "published": frozenset(),
    "failed": frozenset(),
    "ready": frozenset(),
}


def validate_build_state(state: object) -> str:
    """Reject unknown build states instead of guessing their meaning."""
    if not isinstance(state, str) or state not in BUILD_STATES:
        raise ValueError(f"unknown BLAST index build state: {state!r}")
    return state


def build_transition_allowed(current: str, target: str) -> bool:
    """Return whether ``current -> target`` is a legal catalog build step."""
    validate_build_state(current)
    validate_build_state(target)
    return target in BUILD_TRANSITIONS[current]


def is_searchable_build_state(state: str) -> bool:
    """A search may target only a published (or legacy-ready) index."""
    return validate_build_state(state) in SEARCHABLE_BUILD_STATES


def index_identity(value: object) -> str:
    """Validate an immutable 64-hex index identity (content-addressed)."""
    if not isinstance(value, str) or not _IDENTITY_RE.fullmatch(value):
        raise ValueError("invalid BLAST index identity")
    return value


_IDENTITY_RE = re.compile(r"[a-f0-9]{64}\Z")

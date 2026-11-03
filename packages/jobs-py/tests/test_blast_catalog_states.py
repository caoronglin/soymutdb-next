"""The catalog build state machine has one owner and one searchable gate."""
from __future__ import annotations

import pytest

from soymutdb_jobs.blast_catalog import (
    BUILD_STATES,
    BUILD_TRANSITIONS,
    SEARCHABLE_BUILD_STATES,
    TERMINAL_BUILD_STATES,
    build_transition_allowed,
    index_identity,
    is_searchable_build_state,
    validate_build_state,
)


def test_full_lifecycle_is_the_only_legal_path():
    assert BUILD_TRANSITIONS == {
        "pending": frozenset({"building", "failed"}),
        "building": frozenset({"validating", "failed"}),
        "validating": frozenset({"published", "failed"}),
        "published": frozenset(),
        "failed": frozenset(),
        "ready": frozenset(),
    }
    assert set(BUILD_STATES) == set(BUILD_TRANSITIONS)
    assert SEARCHABLE_BUILD_STATES == {"published", "ready"}
    assert {"published", "failed", "ready"} <= TERMINAL_BUILD_STATES


@pytest.mark.parametrize("current,target,allowed", [
    ("pending", "building", True),
    ("pending", "published", False),
    ("pending", "failed", True),
    ("building", "validating", True),
    ("building", "published", False),
    ("validating", "published", True),
    ("validating", "failed", True),
    ("published", "pending", False),
    ("failed", "building", False),
    ("ready", "building", False),
])
def test_transitions(current, target, allowed):
    assert build_transition_allowed(current, target) is allowed


@pytest.mark.parametrize("state,searchable", [
    ("pending", False), ("building", False), ("validating", False),
    ("published", True), ("failed", False), ("ready", True),
])
def test_only_published_indexes_are_searchable(state, searchable):
    assert is_searchable_build_state(state) is searchable


@pytest.mark.parametrize("bad", ["", "READY", "queued", None, 1, "published "])
def test_unknown_state_is_rejected(bad):
    with pytest.raises(ValueError):
        validate_build_state(bad)


def test_identity_is_a_frozen_64_hex_digest():
    assert index_identity("a" * 64) == "a" * 64
    for bad in ["A" * 64, "a" * 63, "a" * 65, "g" * 64, None, 42, "../etc"]:
        with pytest.raises(ValueError):
            index_identity(bad)

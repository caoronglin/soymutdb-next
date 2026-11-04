"""The BLAST catalog build lifecycle is explicit, guarded and fail-closed."""
from __future__ import annotations

import pytest

from soymutdb_jobs import blast_catalog_state as state
from soymutdb_jobs.contract import BLAST_INDEX_BUILD_TASK, TASK_QUEUE_MAP


def test_build_task_is_on_the_blast_queue():
    assert BLAST_INDEX_BUILD_TASK == (
        "soymutdb_worker.tasks.blast_index_tasks.build_blast_index"
    )
    assert TASK_QUEUE_MAP[BLAST_INDEX_BUILD_TASK] == "blast"


def test_only_published_and_its_legacy_spelling_are_searchable():
    assert state.is_searchable_build_state(state.PUBLISHED)
    assert state.is_runnable(state.PUBLISHED)
    # ``ready`` is the legacy terminal spelling of pre-existing catalogs: it
    # reads as published, but nothing in the state machine writes it back.
    assert state.is_searchable_build_state(state.LEGACY_READY)
    assert state.SEARCHABLE_STATES == {state.PUBLISHED, state.LEGACY_READY}
    for status in state.STATES:
        if status == state.PUBLISHED:
            continue
        assert not state.is_searchable_build_state(status), status
    for value in ("Publishing", "Published", "", None, 0, ["published"]):
        assert not state.is_searchable_build_state(value), value


def test_the_vocabulary_matches_the_catalog_check_constraint():
    """The migration, the ORM and this module must accept the same spellings."""
    # Guarded against a silent divergence: a status one layer writes and
    # another rejects is a runtime failure, not a test failure.
    assert set(state.STATES) == {
        "pending", "building", "validating", "publishing", "published", "failed",
    }
    assert set(state.COLUMN_STATES) == set(state.STATES) | {state.LEGACY_READY}
    assert state.STATES[-2] == state.PUBLISHED
    assert state.RUNNABLE_STATUS == state.PUBLISHED
    assert set(state.TRANSITIONS) == set(state.STATES)
    reached = {target for targets in state.TRANSITIONS.values() for target in targets}
    assert reached <= set(state.STATES), reached - set(state.STATES)


@pytest.mark.parametrize("current,target", [
    (state.PENDING, state.BUILDING), (state.BUILDING, state.VALIDATING),
    (state.VALIDATING, state.PUBLISHING), (state.PUBLISHING, state.PUBLISHED),
    (state.PUBLISHED, state.BUILDING), (state.FAILED, state.BUILDING),
    (state.PENDING, state.FAILED), (state.BUILDING, state.FAILED),
    (state.VALIDATING, state.FAILED), (state.PUBLISHING, state.FAILED),
    (state.PUBLISHED, state.FAILED),  # health check can retire a corrupt index
])
def test_legal_transitions(current, target):
    assert state.transition_allowed(current, target)


@pytest.mark.parametrize("current,target", [
    (state.PENDING, state.PUBLISHED), (state.BUILDING, state.PUBLISHED),
    (state.VALIDATING, state.PUBLISHED), (state.PUBLISHING, state.BUILDING),
    (state.PUBLISHED, state.PUBLISHED), (state.FAILED, state.PUBLISHED),
    (state.FAILED, state.FAILED),
    ("unknown", state.BUILDING), (state.PENDING, "bogus"),
    # The legacy spelling must never be written back by the current binary.
    (state.PUBLISHED, "ready"),
])
def test_illegal_transitions_are_refused(current, target):
    assert not state.transition_allowed(current, target)


def test_rebuild_leaves_the_old_index_published_until_swap():
    # A rebuild starts from published -> building, but the state machine has no
    # direct building -> published edge: publication requires validation first.
    assert state.transition_allowed(state.PUBLISHED, state.BUILDING)
    assert not state.transition_allowed(state.BUILDING, state.PUBLISHED)
    assert state.transition_allowed(state.BUILDING, state.VALIDATING)


def test_in_flight_states_are_the_ones_a_build_owns():
    assert state.IN_FLIGHT_STATES == {
        state.BUILDING, state.VALIDATING, state.PUBLISHING,
    }
    assert not state.is_searchable_build_state(state.PUBLISHING)

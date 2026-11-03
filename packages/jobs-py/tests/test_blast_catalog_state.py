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


def test_only_ready_is_runnable():
    assert state.is_runnable(state.READY)
    for status in (state.PENDING, state.BUILDING, state.VALIDATING,
                   state.PUBLISHING, state.FAILED, "unknown"):
        assert not state.is_runnable(status)


@pytest.mark.parametrize("current,target", [
    (state.PENDING, state.BUILDING), (state.BUILDING, state.VALIDATING),
    (state.VALIDATING, state.PUBLISHING), (state.PUBLISHING, state.READY),
    (state.READY, state.BUILDING), (state.FAILED, state.BUILDING),
    (state.PENDING, state.FAILED), (state.BUILDING, state.FAILED),
    (state.VALIDATING, state.FAILED), (state.PUBLISHING, state.FAILED),
    (state.READY, state.FAILED),  # health check can retire a corrupt index
])
def test_legal_transitions(current, target):
    assert state.transition_allowed(current, target)


@pytest.mark.parametrize("current,target", [
    (state.PENDING, state.READY), (state.BUILDING, state.READY),
    (state.VALIDATING, state.READY), (state.PUBLISHING, state.BUILDING),
    (state.READY, state.READY), (state.FAILED, state.READY),
    (state.FAILED, state.FAILED),
    ("unknown", state.BUILDING), (state.PENDING, "bogus"),
])
def test_illegal_transitions_are_refused(current, target):
    assert not state.transition_allowed(current, target)


def test_rebuild_leaves_the_old_index_published_until_swap():
    # A rebuild starts from ready -> building, but the state machine has no
    # direct building -> ready edge: publication requires validation first.
    assert state.transition_allowed(state.READY, state.BUILDING)
    assert not state.transition_allowed(state.BUILDING, state.READY)
    assert state.transition_allowed(state.BUILDING, state.VALIDATING)

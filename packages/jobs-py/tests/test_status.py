"""Tests for the job status state machine (transition table)."""

from __future__ import annotations

import pytest

from soymutdb_jobs.status import TRANSITION_MATRIX, JobStatus, transition_allowed


def test_status_values_are_strict() -> None:
    """The enum values are exactly the canonical seven strings."""
    assert {s.value for s in JobStatus} == {
        "pending",
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancel_requested",
        "cancelled",
    }


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.PENDING, JobStatus.QUEUED),
        (JobStatus.PENDING, JobStatus.RUNNING),
        (JobStatus.PENDING, JobStatus.SUCCEEDED),
        (JobStatus.PENDING, JobStatus.FAILED),
        (JobStatus.PENDING, JobStatus.CANCELLED),
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.QUEUED, JobStatus.SUCCEEDED),
        (JobStatus.QUEUED, JobStatus.FAILED),
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.RUNNING, JobStatus.SUCCEEDED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED),
        (JobStatus.RUNNING, JobStatus.CANCELLED),
        (JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED),
        (JobStatus.CANCEL_REQUESTED, JobStatus.FAILED),
        (JobStatus.FAILED, JobStatus.QUEUED),
        (JobStatus.FAILED, JobStatus.RUNNING),
    ],
)
def test_legal_transitions_are_allowed(current: JobStatus, target: JobStatus) -> None:
    assert transition_allowed(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.PENDING, JobStatus.PENDING),
        (JobStatus.PENDING, JobStatus.CANCEL_REQUESTED),
        (JobStatus.QUEUED, JobStatus.QUEUED),
        (JobStatus.RUNNING, JobStatus.RUNNING),
        (JobStatus.RUNNING, JobStatus.QUEUED),
        (JobStatus.SUCCEEDED, JobStatus.RUNNING),
        (JobStatus.SUCCEEDED, JobStatus.FAILED),
        (JobStatus.SUCCEEDED, JobStatus.CANCELLED),
        (JobStatus.FAILED, JobStatus.SUCCEEDED),
        (JobStatus.FAILED, JobStatus.CANCELLED),
        (JobStatus.CANCELLED, JobStatus.RUNNING),
        (JobStatus.CANCELLED, JobStatus.QUEUED),
        (JobStatus.CANCELLED, JobStatus.SUCCEEDED),
    ],
)
def test_illegal_transitions_are_rejected(current: JobStatus, target: JobStatus) -> None:
    assert transition_allowed(current, target) is False


def test_terminal_states_have_no_outgoing_edges() -> None:
    for terminal in (JobStatus.SUCCEEDED, JobStatus.CANCELLED):
        assert TRANSITION_MATRIX[terminal] == frozenset()


def test_matrix_covers_every_status() -> None:
    assert set(TRANSITION_MATRIX) == set(JobStatus)

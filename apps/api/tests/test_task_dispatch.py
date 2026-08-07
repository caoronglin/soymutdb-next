"""Tests for API-side Celery dispatch without importing the worker app."""

from __future__ import annotations

from unittest.mock import Mock

import pytest


def test_dispatch_task_raises_identifiable_error_on_broker_failure(monkeypatch) -> None:
    """A failed dispatch must include the task and job identifier."""
    from app.core import task_dispatch
    from app.core.exceptions import TaskDispatchError

    celery_client = Mock()
    celery_client.send_task.side_effect = ConnectionError("broker unavailable")
    monkeypatch.setattr(task_dispatch, "get_celery_client", lambda: celery_client)

    with pytest.raises(TaskDispatchError, match="job-123") as exc_info:
        task_dispatch.dispatch_task(
            "soymutdb_worker.tasks.blast.run_blast",
            identifier="job-123",
            queue="blast",
        )

    assert exc_info.value.details["task_name"] == "soymutdb_worker.tasks.blast.run_blast"

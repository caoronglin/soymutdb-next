"""Tests for API-side Celery dispatch without importing the worker app."""

from __future__ import annotations

from unittest.mock import Mock
from types import SimpleNamespace

import pytest


def test_celery_client_configures_bounded_broker_io(monkeypatch) -> None:
    from app.core import task_dispatch

    client = SimpleNamespace(conf=Mock())
    celery_factory = Mock(return_value=client)
    monkeypatch.setattr(task_dispatch, "Celery", celery_factory)
    monkeypatch.setattr(
        task_dispatch,
        "get_settings",
        lambda: SimpleNamespace(
            celery_broker_url="redis://broker/0",
            celery_result_backend="redis://broker/1",
            celery_broker_connect_timeout_seconds=3.0,
            celery_broker_socket_timeout_seconds=5.0,
        ),
    )

    assert task_dispatch.get_celery_client() is client
    client.conf.update.assert_called_once_with(
        broker_connection_timeout=3.0,
        broker_transport_options={
            "socket_connect_timeout": 3.0,
            "socket_timeout": 5.0,
            "retry_on_timeout": False,
        },
        task_publish_retry=False,
    )


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


def test_dispatch_disables_in_memory_publish_retry(monkeypatch) -> None:
    from app.core import task_dispatch

    celery_client = Mock()
    monkeypatch.setattr(task_dispatch, "get_celery_client", lambda: celery_client)

    task_dispatch.dispatch_task(
        "soymutdb_worker.tasks.ingest.run_import_adapter",
        identifier="event-1",
        queue="ingest",
    )

    assert celery_client.send_task.call_args.kwargs["retry"] is False

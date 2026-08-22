"""API-side Celery dispatch without importing the worker application object."""

from __future__ import annotations

from typing import Any

from celery import Celery

from .config import get_settings
from .exceptions import TaskDispatchError


def get_celery_client() -> Celery:
    """Create a lightweight Celery client used only for named task dispatch."""
    settings = get_settings()
    client = Celery(
        "soymutdb-api-dispatcher",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    client.conf.update(
        broker_connection_timeout=settings.celery_broker_connect_timeout_seconds,
        broker_transport_options={
            "socket_connect_timeout": settings.celery_broker_connect_timeout_seconds,
            "socket_timeout": settings.celery_broker_socket_timeout_seconds,
            "retry_on_timeout": False,
        },
        # The durable outbox owns retries. Keeping a second in-memory retry
        # loop here would extend a claim unpredictably during broker outages.
        task_publish_retry=False,
    )
    return client


def dispatch_task(
    task_name: str,
    *,
    identifier: object,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    queue: str,
    task_id: str | None = None,
) -> Any:
    """Dispatch a task and raise a traceable error when the broker rejects it.

    ``task_id`` pins the Celery message id (the outbox dispatcher passes the
    outbox ``event_id`` so crash-restart re-sends reuse the same task id and
    the idempotent worker can safely ignore duplicates).
    """
    try:
        return get_celery_client().send_task(
            task_name,
            args=args,
            kwargs=kwargs,
            queue=queue,
            task_id=task_id,
            retry=False,
        )
    except Exception as exc:
        raise TaskDispatchError(
            f"Failed to dispatch task {task_name} for job {identifier}: {exc}",
            details={
                "identifier": str(identifier),
                "task_name": task_name,
                "queue": queue,
                "task_id": task_id,
            },
        ) from exc


__all__ = ["dispatch_task", "get_celery_client"]

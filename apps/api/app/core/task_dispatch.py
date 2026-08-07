"""API-side Celery dispatch without importing the worker application object."""

from __future__ import annotations

from typing import Any

from celery import Celery

from .config import get_settings
from .exceptions import TaskDispatchError


def get_celery_client() -> Celery:
    """Create a lightweight Celery client used only for named task dispatch."""
    settings = get_settings()
    return Celery(
        "soymutdb-api-dispatcher",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )


def dispatch_task(
    task_name: str,
    *,
    identifier: object,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    queue: str,
) -> Any:
    """Dispatch a task and raise a traceable error when the broker rejects it."""
    try:
        return get_celery_client().send_task(
            task_name,
            args=args,
            kwargs=kwargs,
            queue=queue,
        )
    except Exception as exc:
        raise TaskDispatchError(
            f"Failed to dispatch task {task_name} for job {identifier}: {exc}",
            details={
                "identifier": str(identifier),
                "task_name": task_name,
                "queue": queue,
            },
        ) from exc


__all__ = ["dispatch_task", "get_celery_client"]

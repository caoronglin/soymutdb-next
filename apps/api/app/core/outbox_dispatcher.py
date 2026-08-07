"""Background dispatcher for the transactional outbox.

Polls the ``outbox_events`` table and forwards pending events to Celery with
``task_id == event_id`` (fixed), so a crash between broker accept and the
``sent`` marker causes a re-send that the idempotent worker safely ignores
(at-least-once delivery — exactly-once is never assumed).

Started from the FastAPI lifespan; disabled with
``SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import structlog

from ..core.config import get_settings
from ..core.database import get_session_factory
from ..core.task_contract import QUEUE_DEFAULT, TASK_QUEUE_MAP
from ..core.task_dispatch import dispatch_task
from ..services import outbox_service

logger = structlog.get_logger(__name__)
settings = get_settings()

SendFn = Callable[..., Any]


async def poll_outbox_once(*, send: SendFn = dispatch_task) -> int:
    """Forward one batch of pending outbox events; return events processed."""
    factory = get_session_factory()
    processed = 0
    async with factory() as session:
        try:
            events = await outbox_service.claim_pending(session)
        except Exception:
            await session.rollback()
            raise

        for event in events:
            event_id = str(event.event_id)
            task_name = event.payload.get("task_name", "")
            queue = TASK_QUEUE_MAP.get(task_name, QUEUE_DEFAULT)
            try:
                send(
                    task_name,
                    identifier=event_id,
                    kwargs={"payload": event.payload},
                    queue=queue,
                    task_id=event_id,
                )
            except Exception as exc:
                logger.warning(
                    "outbox.send_failed",
                    event_id=event_id,
                    task_name=task_name,
                    error=str(exc),
                )
                await outbox_service.mark_failed(session, event.event_id, error=str(exc))
            else:
                await outbox_service.mark_sent(
                    session, event.event_id, message_id=event_id
                )
            processed += 1
    return processed


async def cleanup_outbox() -> int:
    """Delete ``sent`` events older than the retention window."""
    factory = get_session_factory()
    async with factory() as session:
        return await outbox_service.delete_sent_older_than(session)


async def run_outbox_dispatcher(stop_event: asyncio.Event | None = None) -> None:
    """Run the poll loop until *stop_event* is set (or the task is cancelled)."""
    logger.info("outbox.dispatcher_started", interval=settings.outbox_poll_interval_seconds)
    last_cleanup = 0.0
    while True:
        try:
            await poll_outbox_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox.poll_error")

        now = time.monotonic()
        if now - last_cleanup >= settings.outbox_cleanup_interval_seconds:
            try:
                deleted = await cleanup_outbox()
                if deleted:
                    logger.info("outbox.cleanup_deleted", events=deleted)
            except Exception:
                logger.exception("outbox.cleanup_error")
            last_cleanup = now

        if stop_event is not None and stop_event.is_set():
            return
        try:
            await asyncio.sleep(settings.outbox_poll_interval_seconds)
        except asyncio.CancelledError:
            raise


async def start_dispatcher() -> asyncio.Task[None] | None:
    """Create the dispatcher background task (or ``None`` when disabled)."""
    if not settings.outbox_dispatcher_enabled:
        logger.info("outbox.dispatcher_disabled")
        return None
    return asyncio.create_task(run_outbox_dispatcher())


__all__ = ["cleanup_outbox", "poll_outbox_once", "run_outbox_dispatcher", "start_dispatcher"]

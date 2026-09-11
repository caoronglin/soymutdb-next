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
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

import structlog

from ..core.config import get_settings
from ..core.database import get_session_factory
from ..core.metrics import (
    OUTBOX_DISPATCH_TOTAL,
    OUTBOX_EVENTS,
    OUTBOX_OLDEST_UNSENT_AGE_SECONDS,
)
from ..core.task_contract import QUEUE_DEFAULT, TASK_QUEUE_MAP
from ..core.task_dispatch import dispatch_task
from ..services import outbox_service

logger = structlog.get_logger(__name__)
settings = get_settings()

SendFn = Callable[..., Any]
_OUTBOX_METRICS_REFRESH_SECONDS = 15.0


def _safe_send_error(exc: Exception) -> str:
    """Return broker diagnostics that cannot contain an event payload."""
    return f"{type(exc).__name__}: broker send failed"


async def _heartbeat_claims(
    *,
    factory: Any,
    event_ids: set[uuid.UUID],
    lease_owner: uuid.UUID,
    lease_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Renew every unfinished event in a claimed batch until stopped."""
    interval = max(lease_seconds / 3, 0.01)
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except TimeoutError:
            pass

        active_ids = list(event_ids)
        if not active_ids:
            return
        try:
            async with factory() as session:
                renewed = await outbox_service.renew_leases(
                    session,
                    active_ids,
                    lease_owner=lease_owner,
                    lease_seconds=lease_seconds,
                )
            if renewed < len(active_ids):
                logger.warning(
                    "outbox.lease_renew_partial",
                    lease_owner=str(lease_owner),
                    expected=len(active_ids),
                    renewed=renewed,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "outbox.lease_renew_failed",
                lease_owner=str(lease_owner),
                error_type=type(exc).__name__,
            )


async def poll_outbox_once(*, send: SendFn = dispatch_task) -> int:
    """Forward one durably claimed batch; return the number processed.

    The claim transaction commits ``processing`` leases before any broker I/O.
    A separate heartbeat session keeps all unfinished rows in the batch leased
    while synchronous Celery sends run in worker threads.
    """
    factory = get_session_factory()
    processed = 0
    lease_owner = uuid.uuid4()
    async with factory() as session:
        try:
            events = await outbox_service.claim_pending(
                session,
                batch_size=settings.outbox_batch_size,
                lease_owner=lease_owner,
                lease_seconds=settings.outbox_lease_seconds,
            )
        except Exception:
            await session.rollback()
            raise

        if not events:
            return 0

        active_event_ids = {event.event_id for event in events}
        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            _heartbeat_claims(
                factory=factory,
                event_ids=active_event_ids,
                lease_owner=lease_owner,
                lease_seconds=settings.outbox_lease_seconds,
                stop_event=heartbeat_stop,
            )
        )
        send_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="outbox-send"
        )
        cancelled = False
        try:
            for event in events:
                event_id = str(event.event_id)
                payload = event.payload or {}
                task_name = payload.get("task_name", "")
                if not task_name or not isinstance(task_name, str):
                    logger.warning(
                        "outbox.malformed_event",
                        event_id=event_id,
                        event_type=event.event_type,
                        reason="missing task_name",
                    )
                    changed = await outbox_service.mark_failed(
                        session,
                        event.event_id,
                        lease_owner=lease_owner,
                        error="missing task_name",
                    )
                    outcome = "malformed" if changed else "lease_lost"
                    OUTBOX_DISPATCH_TOTAL.labels(outcome=outcome).inc()
                    if not changed:
                        logger.warning("outbox.lease_lost", event_id=event_id)
                    processed += 1
                    active_event_ids.discard(event.event_id)
                    continue

                kwargs = payload.get("kwargs")
                if kwargs is None:
                    # Backward compatibility: versioned JobPayload events carry
                    # the task payload directly under ``payload``.
                    kwargs = {"payload": payload}
                elif not isinstance(kwargs, dict):
                    logger.warning(
                        "outbox.malformed_event",
                        event_id=event_id,
                        event_type=event.event_type,
                        reason="invalid kwargs",
                    )
                    changed = await outbox_service.mark_failed(
                        session,
                        event.event_id,
                        lease_owner=lease_owner,
                        error="invalid kwargs",
                    )
                    outcome = "malformed" if changed else "lease_lost"
                    OUTBOX_DISPATCH_TOTAL.labels(outcome=outcome).inc()
                    if not changed:
                        logger.warning("outbox.lease_lost", event_id=event_id)
                    processed += 1
                    active_event_ids.discard(event.event_id)
                    continue

                queue = TASK_QUEUE_MAP.get(task_name, QUEUE_DEFAULT)
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        send_executor,
                        partial(
                            send,
                            task_name,
                            identifier=event_id,
                            kwargs=kwargs,
                            queue=queue,
                            task_id=event_id,
                        ),
                    )
                except Exception as exc:
                    logger.warning(
                        "outbox.send_failed",
                        event_id=event_id,
                        task_name=task_name,
                        error_type=type(exc).__name__,
                    )
                    changed = await outbox_service.mark_failed(
                        session,
                        event.event_id,
                        lease_owner=lease_owner,
                        error=_safe_send_error(exc),
                    )
                    outcome = "failed"
                else:
                    changed = await outbox_service.mark_sent(
                        session,
                        event.event_id,
                        lease_owner=lease_owner,
                        message_id=event_id,
                    )
                    outcome = "sent"
                if not changed:
                    outcome = "lease_lost"
                    logger.warning("outbox.lease_lost", event_id=event_id)
                OUTBOX_DISPATCH_TOTAL.labels(outcome=outcome).inc()
                processed += 1
                active_event_ids.discard(event.event_id)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            heartbeat_stop.set()
            try:
                await heartbeat
            except asyncio.CancelledError:
                heartbeat.cancel()
                raise
            finally:
                send_executor.shutdown(
                    wait=not cancelled, cancel_futures=cancelled
                )
    return processed


async def refresh_outbox_metrics() -> None:
    """Refresh low-cardinality backlog gauges from one read-only snapshot."""
    factory = get_session_factory()
    async with factory() as session:
        counts, oldest_age = await outbox_service.get_metrics_snapshot(session)
    for status in ("pending", "processing", "sent", "failed"):
        OUTBOX_EVENTS.labels(status=status).set(counts.get(status, 0))
    OUTBOX_OLDEST_UNSENT_AGE_SECONDS.set(oldest_age)


async def cleanup_outbox() -> int:
    """Delete ``sent`` events older than the retention window."""
    factory = get_session_factory()
    async with factory() as session:
        return await outbox_service.delete_sent_older_than(session)


async def run_outbox_dispatcher(stop_event: asyncio.Event | None = None) -> None:
    """Run the poll loop until *stop_event* is set (or the task is cancelled)."""
    logger.info("outbox.dispatcher_started", interval=settings.outbox_poll_interval_seconds)
    last_cleanup = 0.0
    last_metrics_refresh = 0.0
    while True:
        try:
            await poll_outbox_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "outbox.poll_error",
                error_type=type(exc).__name__,
            )

        now = time.monotonic()
        if now - last_metrics_refresh >= _OUTBOX_METRICS_REFRESH_SECONDS:
            try:
                await refresh_outbox_metrics()
            except Exception as exc:
                logger.warning(
                    "outbox.metrics_refresh_error", error_type=type(exc).__name__
                )
            last_metrics_refresh = now

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


__all__ = [
    "cleanup_outbox",
    "poll_outbox_once",
    "refresh_outbox_metrics",
    "run_outbox_dispatcher",
    "start_dispatcher",
]

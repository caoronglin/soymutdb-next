"""Transactional outbox: event creation and dispatch bookkeeping.

Events are written in the same database transaction as the business record
(e.g. a BLAST job), so submission never depends on the Celery broker being
reachable.  A background dispatcher (``app.core.outbox_dispatcher``) polls
``claim_pending`` and marks rows ``sent`` only after the broker accepted the
message; rows left ``pending``/``failed`` after a crash are re-sent with the
same ``task_id`` (``event_id``) and the idempotent worker ignores duplicates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.task_contract import IMPORT_ADAPTER_TASK
from ..models.data_publishing import DataSet
from ..models.import_task import ImportTask, ImportTaskType
from ..models.outbox import OutboxEvent, OutboxEventStatus

settings = get_settings()


async def get_or_create_idempotent_event(db: AsyncSession, *, aggregate_type: str, aggregate_id: str, event_type: str, idempotency_key: str, payload: dict) -> tuple[OutboxEvent, bool]:
    result = await db.execute(select(OutboxEvent).where(OutboxEvent.payload["idempotency_key"].astext == idempotency_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    return await create_outbox_event(db, aggregate_type=aggregate_type, aggregate_id=aggregate_id, event_type=event_type, payload={**payload, "idempotency_key": idempotency_key}), True


async def create_import_command(
    db: AsyncSession,
    *,
    actor_id,
    idempotency_key: str,
    data_set_id: int,
    import_type: str,
    filename: str,
    object_key: str | None = None,
    release_id: int | None = None,
    assembly: str | None = None,
    module_key: str | None = None,
    schema_version: int | None = None,
    checksum: str | None = None,
) -> ImportTask:
    """Create an import task and enqueue the canonical import-adapter event.

    The outbox event carries a typed ``task_name`` and ``kwargs`` so the
    dispatcher can forward exactly the arguments the worker task expects.
    """
    existing = await db.scalar(select(ImportTask).where(ImportTask.idempotency_key == idempotency_key))
    if existing:
        return existing
    dataset = await db.get(DataSet, data_set_id)
    if dataset is None:
        dataset = DataSet(id=data_set_id, type=import_type)
        db.add(dataset)
        await db.flush()
    task = ImportTask(
        filename=filename,
        type=ImportTaskType(import_type),
        file_path=object_key or "",
        data_set_id=data_set_id,
        release_id=release_id,
        object_key=object_key,
        idempotency_key=idempotency_key,
        submitted_by=str(actor_id) if actor_id else None,
    )
    db.add(task)
    await db.flush()
    await enqueue_task_event(
        db,
        event_type="import_requested",
        aggregate_type="import_task",
        aggregate_id=str(task.id),
        task_name=IMPORT_ADAPTER_TASK,
        kwargs={
            "import_task_id": task.id,
            "data_set_id": data_set_id,
            "kind": import_type,
            "release_id": str(release_id) if release_id is not None else "",
            "file_key": object_key or filename,
            "filename": filename,
            "assembly": assembly or "",
            "module_key": module_key,
            "schema_version": schema_version,
            "checksum": checksum,
        },
    )
    return task


def new_event_id() -> uuid.UUID:
    """Generate the outbox event id (also used as the Celery ``task_id``)."""
    return uuid.uuid4()


async def create_outbox_event(
    db: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    """Persist a pending outbox row inside the caller's transaction.

    The caller owns the transaction: this function only flushes so the row
    is visible to the rest of the transaction.
    """
    event = OutboxEvent(
        event_id=new_event_id(),
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        event_type=event_type,
        payload=payload,
        status=OutboxEventStatus.PENDING,
        attempt_count=0,
    )
    db.add(event)
    await db.flush()
    return event


async def enqueue_task_event(
    db: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    task_name: str,
    kwargs: dict,
) -> OutboxEvent:
    """Enqueue a typed task event with an explicit Celery task name.

    The payload is ``{"task_name": ..., "kwargs": ...}``.  The dispatcher
    forwards ``kwargs`` directly to the worker task, while legacy job events
    (which carry a versioned ``JobPayload`` under ``payload``) remain
    supported through the dispatcher's backward-compatible fallback.
    """
    if not task_name or not task_name.strip():
        raise ValueError("task_name is required")
    if not isinstance(kwargs, dict):
        raise ValueError("kwargs must be a dict")
    return await create_outbox_event(
        db,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload={"task_name": task_name, "kwargs": kwargs},
    )


async def claim_pending(
    db: AsyncSession,
    *,
    batch_size: int | None = None,
    max_attempts: int | None = None,
) -> list[OutboxEvent]:
    """Select events to send: pending, or failed with retries remaining.

    Oldest first, locked with ``FOR UPDATE SKIP LOCKED`` so concurrent
    dispatchers never hand the same event to two senders in one round.
    """
    batch_size = batch_size or settings.outbox_batch_size
    max_attempts = max_attempts or settings.outbox_max_attempts
    stmt = (
        select(OutboxEvent)
        .where(
            (OutboxEvent.status == OutboxEventStatus.PENDING)
            | (
                (OutboxEvent.status == OutboxEventStatus.FAILED)
                & (OutboxEvent.attempt_count < max_attempts)
            )
        )
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_sent(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    message_id: str | None = None,
) -> None:
    """Mark an event as sent (only called after the broker accepted it)."""
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.event_id == event_id)
        .values(
            status=OutboxEventStatus.SENT,
            sent_at=datetime.now(UTC),
            message_id=message_id,
            last_error=None,
            attempt_count=OutboxEvent.attempt_count + 1,
        )
    )
    await db.commit()


async def mark_failed(db: AsyncSession, event_id: uuid.UUID, *, error: str) -> None:
    """Record a failed send; the event stays eligible for a later retry."""
    await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.event_id == event_id)
        .values(
            status=OutboxEventStatus.FAILED,
            last_error=error[:4000],
            attempt_count=OutboxEvent.attempt_count + 1,
        )
    )
    await db.commit()


async def delete_sent_older_than(
    db: AsyncSession, *, days: int | None = None
) -> int:
    """Archive/cleanup: delete ``sent`` events older than the retention window."""
    days = days or settings.outbox_retention_days
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        delete(OutboxEvent).where(
            OutboxEvent.status == OutboxEventStatus.SENT,
            OutboxEvent.sent_at < cutoff,
        )
    )
    await db.commit()
    return getattr(result, "rowcount", 0) or 0


__all__ = [
    "claim_pending",
    "create_outbox_event",
    "delete_sent_older_than",
    "mark_failed",
    "mark_sent",
    "new_event_id",
    "get_or_create_idempotent_event",
    "create_import_command",
    "enqueue_task_event",
]

"""Transactional outbox: event creation and durable dispatch bookkeeping.

Events are written in the same database transaction as the business record
(e.g. a BLAST job), so submission never depends on the Celery broker being
reachable.  A background dispatcher (``app.core.outbox_dispatcher``) polls
``claim_pending`` and marks rows ``sent`` only after the broker accepted the
message.  Claims are committed as fenced ``processing`` leases before broker
I/O; expired claims are re-sent with the same ``task_id`` (``event_id``), so
delivery remains at-least-once and idempotent workers can ignore duplicates.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ValidationError
from ..core.metrics import OUTBOX_DELIVERY_EXHAUSTED_TOTAL
from ..core.task_contract import IMPORT_ADAPTER_TASK
from ..models.content import Release, ReleaseStatus
from ..models.data_publishing import DataSet
from ..models.import_task import ImportTask, ImportTaskType
from ..models.outbox import OutboxEvent, OutboxEventStatus
from .presign import validate_data_key

settings = get_settings()


async def get_or_create_idempotent_event(
    db: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    idempotency_key: str,
    payload: dict,
) -> tuple[OutboxEvent, bool]:
    result = await db.execute(
        select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    try:
        async with db.begin_nested():
            event = await create_outbox_event(
                db,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload={**payload, "idempotency_key": idempotency_key},
            )
        return event, True
    except IntegrityError:
        # A concurrent transaction won the unique-key race. The savepoint
        # keeps the caller's business transaction usable; return its row.
        existing = await db.scalar(
            select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return existing, False


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
    existing = await db.scalar(
        select(ImportTask).where(ImportTask.idempotency_key == idempotency_key)
    )
    if existing:
        return existing

    file_key = object_key or filename

    # Bare ``data/<dataset>/...`` keys come from browser-direct multipart
    # uploads. Bind them to the data set before persisting an attestation;
    # explicit S3 URIs retain the advanced-source contract. ``file_key`` is
    # the exact fallback forwarded to the worker, so it—not only object_key—
    # must satisfy the browser-key ownership boundary.
    if file_key.startswith("data/"):
        try:
            validate_data_key(file_key, data_set_id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    if import_type == "module_tsv":
        if release_id is None:
            raise ValidationError("release_id is required for module_tsv imports")
        # Keep this lock until the caller commits the task and outbox event.
        # A publication transition then serializes with the command boundary
        # instead of accepting a task for an immutable release.
        release = await db.scalar(
            select(Release).where(Release.id == release_id).with_for_update()
        )
        if release is None:
            raise ValidationError(f"release_id {release_id} does not exist")
        release_status = getattr(release.status, "value", release.status)
        if release_status != ReleaseStatus.DRAFT.value:
            raise ValidationError("module_tsv imports require a draft release")

    dataset = await db.get(DataSet, data_set_id)
    if dataset is None:
        dataset = DataSet(
            id=data_set_id,
            type=import_type,
            release_id=release_id if import_type == "module_tsv" else None,
        )
        db.add(dataset)
        await db.flush()
    elif import_type == "module_tsv" and dataset.release_id != release_id:
        bound_release = dataset.release_id if dataset.release_id is not None else "none"
        raise ValidationError(
            f"Data set {data_set_id} is already bound to release {bound_release}; "
            f"cannot import it into release {release_id}"
        )
    task = ImportTask(
        filename=filename,
        type=ImportTaskType(import_type),
        file_path=file_key,
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
            "file_key": file_key,
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


def _payload_idempotency_key(payload: dict) -> str | None:
    value = payload.get("idempotency_key")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("idempotency_key must be a non-empty string")
    if len(value) > 255:
        raise ValueError("idempotency_key must not exceed 255 characters")
    return value


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
        idempotency_key=_payload_idempotency_key(payload),
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
    metadata: dict | None = None,
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
        payload={
            "task_name": task_name,
            "kwargs": kwargs,
            **({"metadata": metadata} if metadata else {}),
        },
    )


async def claim_pending(
    db: AsyncSession,
    *,
    batch_size: int | None = None,
    max_attempts: int | None = None,
    lease_owner: uuid.UUID | None = None,
    lease_seconds: float | None = None,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    """Atomically claim and commit one delivery batch before broker I/O.

    Pending, retryable failed, and expired processing rows are selected oldest
    first under ``FOR UPDATE SKIP LOCKED``.  Every selected row receives the
    caller's fresh fencing token, a lease deadline, and exactly one attempt
    increment.  The commit happens here so no database lock is held while the
    dispatcher talks to Celery.
    """
    batch_size = settings.outbox_batch_size if batch_size is None else batch_size
    max_attempts = settings.outbox_max_attempts if max_attempts is None else max_attempts
    lease_seconds = (
        settings.outbox_lease_seconds if lease_seconds is None else lease_seconds
    )
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    lease_owner = lease_owner or uuid.uuid4()
    claimed_at = now if now is not None else await db.scalar(select(func.now()))
    if claimed_at is None:  # pragma: no cover - PostgreSQL always returns now()
        raise RuntimeError("database clock is unavailable")
    lease_until = claimed_at + timedelta(seconds=lease_seconds)
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.attempt_count < max_attempts,
            or_(
                OutboxEvent.status == OutboxEventStatus.PENDING,
                OutboxEvent.status == OutboxEventStatus.FAILED,
                and_(
                    OutboxEvent.status == OutboxEventStatus.PROCESSING,
                    OutboxEvent.lease_until.is_not(None),
                    OutboxEvent.lease_until <= claimed_at,
                ),
            ),
        )
        .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    events = list(result.scalars().all())
    exhausted_result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxEventStatus.PROCESSING,
            OutboxEvent.attempt_count >= max_attempts,
            OutboxEvent.lease_until <= claimed_at,
        )
        .values(
            # The claim predicate gates retryable failed rows by attempt_count.
            # Do not mark an unacknowledged broker delivery as sent.
            status=OutboxEventStatus.FAILED,
            sent_at=None,
            lease_owner=None,
            lease_until=None,
            last_error="delivery lease expired after maximum attempts",
        )
    )
    for event in events:
        event.status = OutboxEventStatus.PROCESSING
        event.attempt_count += 1
        event.lease_owner = lease_owner
        event.lease_until = lease_until
    await db.commit()
    exhausted_count = max(getattr(exhausted_result, "rowcount", 0) or 0, 0)
    if exhausted_count:
        OUTBOX_DELIVERY_EXHAUSTED_TOTAL.inc(exhausted_count)
    return events


async def mark_sent(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    lease_owner: uuid.UUID,
    message_id: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Mark a live claim sent, returning false when its fence is stale."""
    database_now = now if now is not None else func.now()
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.event_id == event_id,
            OutboxEvent.status == OutboxEventStatus.PROCESSING,
            OutboxEvent.lease_owner == lease_owner,
            OutboxEvent.lease_until > database_now,
        )
        .values(
            status=OutboxEventStatus.SENT,
            sent_at=database_now,
            message_id=message_id,
            last_error=None,
            lease_owner=None,
            lease_until=None,
        )
    )
    await db.commit()
    return (getattr(result, "rowcount", 0) or 0) == 1


async def mark_failed(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    lease_owner: uuid.UUID,
    error: str,
    now: datetime | None = None,
) -> bool:
    """Fail a live claim, returning false when another owner reclaimed it."""
    database_now = now if now is not None else func.now()
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.event_id == event_id,
            OutboxEvent.status == OutboxEventStatus.PROCESSING,
            OutboxEvent.lease_owner == lease_owner,
            OutboxEvent.lease_until > database_now,
        )
        .values(
            status=OutboxEventStatus.FAILED,
            last_error=error[:4000],
            lease_owner=None,
            lease_until=None,
        )
    )
    await db.commit()
    return (getattr(result, "rowcount", 0) or 0) == 1


async def renew_leases(
    db: AsyncSession,
    event_ids: Sequence[uuid.UUID],
    *,
    lease_owner: uuid.UUID,
    lease_seconds: float | None = None,
    now: datetime | None = None,
) -> int:
    """Extend live leases owned by *lease_owner* in one transaction.

    An already-expired or reclaimed lease is never resurrected.  The return
    value is the number of rows still owned and renewed by this caller.
    """
    if not event_ids:
        return 0
    lease_seconds = (
        settings.outbox_lease_seconds if lease_seconds is None else lease_seconds
    )
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    renewed_at = now if now is not None else await db.scalar(select(func.now()))
    if renewed_at is None:  # pragma: no cover - PostgreSQL always returns now()
        raise RuntimeError("database clock is unavailable")
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.event_id.in_(event_ids),
            OutboxEvent.status == OutboxEventStatus.PROCESSING,
            OutboxEvent.lease_owner == lease_owner,
            OutboxEvent.lease_until > renewed_at,
        )
        .values(lease_until=renewed_at + timedelta(seconds=lease_seconds))
    )
    await db.commit()
    return getattr(result, "rowcount", 0) or 0


async def get_metrics_snapshot(
    db: AsyncSession, *, now: datetime | None = None
) -> tuple[dict[str, int], float]:
    """Return status counts and oldest unsent age without mutating rows."""
    result = await db.execute(
        select(OutboxEvent.status, func.count(OutboxEvent.id)).group_by(
            OutboxEvent.status
        )
    )
    counts = {
        str(getattr(status, "value", status)): int(count)
        for status, count in result.all()
    }
    oldest = await db.scalar(
        select(func.min(OutboxEvent.created_at)).where(
            OutboxEvent.status != OutboxEventStatus.SENT
        )
    )
    if oldest is None:
        return counts, 0.0
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return counts, max(0.0, (current - oldest).total_seconds())


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
    "get_metrics_snapshot",
    "mark_failed",
    "mark_sent",
    "new_event_id",
    "renew_leases",
    "get_or_create_idempotent_event",
    "create_import_command",
    "enqueue_task_event",
]

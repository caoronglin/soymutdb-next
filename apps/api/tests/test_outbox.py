"""Transactional outbox tests (no docker: fake async session).

Covers event creation, claiming, send bookkeeping, retry of failed events,
and re-send idempotency (a ``sent`` event is never claimed/sent again; sends
always pin ``task_id == event_id`` so worker-side dedup is possible).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core import outbox_dispatcher
from app.core.task_contract import BLAST_RUN_TASK, TASK_QUEUE_MAP
from app.models.outbox import OutboxEvent, OutboxEventStatus
from app.services import outbox_service

# ---------------------------------------------------------------------------
# Fake async session
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class _Result:
    def __init__(self, rows: list | None = None, rowcount: int | None = None):
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _extract(value):
    """Unwrap BindParameter / enum members to plain values."""
    while hasattr(value, "value") and not isinstance(value, str):
        value = value.value
    return value


class FakeSession:
    """Minimal AsyncSession stand-in that records statements/objects."""

    def __init__(
        self,
        events: list[OutboxEvent] | None = None,
        rowcount: int = 0,
        max_attempts: int = 5,
    ):
        self.events = list(events or [])
        self.added: list = []
        self.executed: list = []
        self.rowcount = rowcount
        self.max_attempts = max_attempts
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        table = getattr(stmt, "table", None)
        if table is not None and table.name == "outbox_events":
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if "status" in values:  # UPDATE (mark_sent / mark_failed)
                new_status = values["status"]
                if self.events:
                    self.events[0].status = OutboxEventStatus(new_status)
                    self.events[0].attempt_count += 1
                    if new_status == OutboxEventStatus.SENT.value:
                        self.events[0].sent_at = datetime.now(UTC)
                        self.events[0].message_id = values.get("message_id")
                    else:
                        self.events[0].last_error = values.get("last_error")
                return _Result([], rowcount=self.rowcount)
        if str(stmt).lstrip().upper().startswith("SELECT") and "outbox_events" in str(stmt):
            # SELECT (claim_pending): emulate the status/attempts filter.
            claimable = [
                ev
                for ev in self.events
                if ev.status == OutboxEventStatus.PENDING
                or (
                    ev.status == OutboxEventStatus.FAILED
                    and ev.attempt_count < self.max_attempts
                )
            ]
            return _Result(rows=claimable, rowcount=self.rowcount)
        return _Result(rows=self.events, rowcount=self.rowcount)


def _make_event(
    *,
    status: OutboxEventStatus = OutboxEventStatus.PENDING,
    attempt_count: int = 0,
    task_name: str = BLAST_RUN_TASK,
) -> OutboxEvent:
    return OutboxEvent(
        id=1,
        event_id=uuid.uuid4(),
        aggregate_type="blast_job",
        aggregate_id="job-1",
        event_type="blast_job.run",
        payload={"task_name": task_name, "job_id": "job-1"},
        status=status,
        attempt_count=attempt_count,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Service: creation and claiming
# ---------------------------------------------------------------------------


async def test_create_event_flushes_pending_row() -> None:
    session = FakeSession()
    event = await outbox_service.create_outbox_event(
        session,
        aggregate_type="blast_job",
        aggregate_id="job-1",
        event_type="blast_job.run",
        payload={"task_name": BLAST_RUN_TASK},
    )
    assert session.added == [event]
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 0
    assert event.event_id is not None
    assert session.commits == 0  # caller owns the transaction


async def test_claim_pending_only_returns_pending_and_retryable_failed() -> None:
    retryable = _make_event(status=OutboxEventStatus.FAILED, attempt_count=2)
    exhausted = _make_event(status=OutboxEventStatus.FAILED, attempt_count=5)
    sent = _make_event(status=OutboxEventStatus.SENT)
    session = FakeSession(events=[retryable, exhausted, sent])
    claimed = await outbox_service.claim_pending(session, batch_size=10, max_attempts=5)
    assert claimed == [retryable]


# ---------------------------------------------------------------------------
# Service: send bookkeeping
# ---------------------------------------------------------------------------


async def test_mark_sent_records_message_id_and_attempt() -> None:
    event = _make_event()
    session = FakeSession(events=[event])
    await outbox_service.mark_sent(session, event.event_id, message_id=str(event.event_id))
    assert session.commits == 1
    assert event.status == OutboxEventStatus.SENT
    assert event.attempt_count == 1
    assert event.message_id == str(event.event_id)
    assert event.sent_at is not None


async def test_mark_failed_records_error_and_increments_attempts() -> None:
    event = _make_event()
    session = FakeSession(events=[event])
    await outbox_service.mark_failed(session, event.event_id, error="broker down")
    assert session.commits == 1
    assert event.status == OutboxEventStatus.FAILED
    assert event.attempt_count == 1
    assert event.last_error == "broker down"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class _SendRecorder:
    def __init__(self, raise_error: Exception | None = None):
        self.calls: list[dict] = []
        self.raise_error = raise_error

    def __call__(self, task_name, *, identifier, args=None, kwargs=None, queue=None, task_id=None):
        if self.raise_error is not None:
            raise self.raise_error
        self.calls.append(
            {
                "task_name": task_name,
                "identifier": identifier,
                "kwargs": kwargs,
                "queue": queue,
                "task_id": task_id,
            }
        )


def _fake_factory(session: FakeSession):
    """Patched ``get_session_factory``.

    The dispatcher does ``factory = get_session_factory()`` then
    ``async with factory() as session`` — so the patched value must be
    callable (like a sessionmaker) and produce an async context manager.
    """

    class _Ctx:
        async def __aenter__(self) -> FakeSession:
            return session

        async def __aexit__(self, *args) -> None:
            pass

    class _Maker:
        def __call__(self) -> _Ctx:
            return _Ctx()

    return _Maker  # class: calling it yields a callable whose call yields the CM


async def test_poll_sends_with_fixed_task_id_and_marks_sent(monkeypatch) -> None:
    event = _make_event()
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder()
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 1
    assert len(sender.calls) == 1
    call = sender.calls[0]
    # Re-send idempotency anchor: task_id must equal the outbox event_id.
    assert call["task_id"] == str(event.event_id)
    assert call["task_name"] == BLAST_RUN_TASK
    assert call["queue"] == TASK_QUEUE_MAP[BLAST_RUN_TASK]
    assert call["kwargs"] == {"payload": event.payload}
    # After a successful send the event is marked sent, never re-sent.
    assert event.status == OutboxEventStatus.SENT
    assert event.message_id == str(event.event_id)
    assert session.commits == 1


async def test_poll_marks_failed_when_broker_rejects(monkeypatch) -> None:
    event = _make_event()
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder(raise_error=ConnectionError("redis down"))
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 1
    assert event.status == OutboxEventStatus.FAILED
    assert "redis down" in (event.last_error or "")


async def test_sent_event_is_not_sent_again(monkeypatch) -> None:
    """Re-send idempotency: a sent event is never claimed, hence never sent."""
    event = _make_event(status=OutboxEventStatus.SENT)
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder()
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 0
    assert sender.calls == []


async def test_failed_event_is_retried_on_next_poll(monkeypatch) -> None:
    """Retry: a failed event (attempts left) is re-sent with the same task_id."""
    event = _make_event(status=OutboxEventStatus.FAILED, attempt_count=1)
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder()
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 1
    assert sender.calls[0]["task_id"] == str(event.event_id)
    assert event.status == OutboxEventStatus.SENT
    assert event.attempt_count == 2


async def test_cleanup_deletes_sent_events_older_than_retention(monkeypatch) -> None:
    session = FakeSession(rowcount=3)
    deleted = await outbox_service.delete_sent_older_than(session, days=30)
    assert deleted == 3
    assert session.commits == 1


async def test_dispatcher_survives_poll_errors_and_stops_on_event() -> None:
    """The loop keeps polling after an error and exits on stop_event."""
    stop = __import__("asyncio").Event()
    stop.set()
    await outbox_dispatcher.run_outbox_dispatcher(stop_event=stop)

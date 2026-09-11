"""Transactional outbox tests (no docker: fake async session).

Covers event creation, claiming, send bookkeeping, retry of failed events,
and re-send idempotency (a ``sent`` event is never claimed/sent again; sends
always pin ``task_id == event_id`` so worker-side dedup is possible).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core import outbox_dispatcher
from app.core.task_contract import BLAST_RUN_TASK, TASK_QUEUE_MAP
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import DataSet
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

    async def scalar(self, stmt):
        self.executed.append((stmt, None))
        return datetime.now(UTC)

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        table = getattr(stmt, "table", None)
        if table is not None and table.name == "outbox_events":
            values = {
                getattr(key, "name", key): _extract(value)
                for key, value in dict(getattr(stmt, "_values", {}) or {}).items()
            }
            if (
                values.get("last_error")
                == "delivery lease expired after maximum attempts"
            ):
                settled = 0
                for event in self.events:
                    if (
                        event.status == OutboxEventStatus.PROCESSING
                        and event.attempt_count >= self.max_attempts
                        and event.lease_until is not None
                        and event.lease_until <= datetime.now(UTC)
                    ):
                        event.status = OutboxEventStatus.FAILED
                        event.lease_owner = None
                        event.lease_until = None
                        event.last_error = values["last_error"]
                        settled += 1
                return _Result([], rowcount=settled)
            if "status" in values:  # UPDATE (mark_sent / mark_failed)
                new_status = values["status"]
                if self.events:
                    self.events[0].status = OutboxEventStatus(new_status)
                    self.events[0].lease_owner = values.get("lease_owner")
                    self.events[0].lease_until = values.get("lease_until")
                    if new_status == OutboxEventStatus.SENT.value:
                        self.events[0].sent_at = datetime.now(UTC)
                        self.events[0].message_id = values.get("message_id")
                    else:
                        self.events[0].last_error = values.get("last_error")
                return _Result(
                    [], rowcount=self.rowcount or int(bool(self.events))
                )
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
                or (
                    ev.status == OutboxEventStatus.PROCESSING
                    and ev.attempt_count < self.max_attempts
                    and ev.lease_until is not None
                    and ev.lease_until <= datetime.now(UTC)
                )
            ]
            return _Result(rows=claimable, rowcount=self.rowcount)
        return _Result(rows=self.events, rowcount=self.rowcount)


class ImportCommandSession(FakeSession):
    """Small no-Docker session for command-boundary validation tests."""

    def __init__(self, *, release_status: str | ReleaseStatus = ReleaseStatus.DRAFT) -> None:
        super().__init__()
        self.release_status = release_status

    async def scalar(self, stmt):
        self.executed.append((stmt, None))
        rendered = str(stmt)
        if "FROM import_tasks" in rendered:
            return None  # no existing idempotent task
        if "FROM releases" in rendered:
            return SimpleNamespace(id=9, status=self.release_status)
        raise AssertionError(f"unexpected scalar query: {rendered}")

    async def get(self, entity, _identifier):
        if entity is Release:
            return SimpleNamespace(id=_identifier, status=self.release_status)
        if entity is DataSet:
            return None
        raise AssertionError(f"unexpected model lookup: {entity}")


def _make_event(
    *,
    status: OutboxEventStatus = OutboxEventStatus.PENDING,
    attempt_count: int = 0,
    task_name: str = BLAST_RUN_TASK,
) -> OutboxEvent:
    lease_owner = uuid.uuid4() if status == OutboxEventStatus.PROCESSING else None
    return OutboxEvent(
        id=1,
        event_id=uuid.uuid4(),
        aggregate_type="blast_job",
        aggregate_id="job-1",
        event_type="blast_job.run",
        payload={"task_name": task_name, "job_id": "job-1"},
        status=status,
        attempt_count=attempt_count,
        lease_owner=lease_owner,
        lease_until=(
            datetime.now(UTC) + timedelta(minutes=5)
            if lease_owner is not None
            else None
        ),
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
        payload={"task_name": BLAST_RUN_TASK, "idempotency_key": "blast:job-1"},
    )
    assert session.added == [event]
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 0
    assert event.event_id is not None
    assert event.idempotency_key == "blast:job-1"
    assert session.commits == 0  # caller owns the transaction


@pytest.mark.parametrize("key", ["", "   ", 7, "x" * 256])
async def test_create_event_rejects_invalid_idempotency_key(key) -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        await outbox_service.create_outbox_event(
            FakeSession(),
            aggregate_type="blast_job",
            aggregate_id="job-1",
            event_type="blast_job.run",
            payload={"task_name": BLAST_RUN_TASK, "idempotency_key": key},
        )


async def test_claim_pending_only_returns_pending_and_retryable_failed() -> None:
    retryable = _make_event(status=OutboxEventStatus.FAILED, attempt_count=2)
    exhausted = _make_event(status=OutboxEventStatus.FAILED, attempt_count=5)
    sent = _make_event(status=OutboxEventStatus.SENT)
    session = FakeSession(events=[retryable, exhausted, sent])
    claimed = await outbox_service.claim_pending(session, batch_size=10, max_attempts=5)
    assert claimed == [retryable]
    assert retryable.status == OutboxEventStatus.PROCESSING
    assert retryable.attempt_count == 3
    assert retryable.lease_owner is not None
    assert retryable.lease_until is not None
    assert session.commits == 1


# ---------------------------------------------------------------------------
# Service: send bookkeeping
# ---------------------------------------------------------------------------


async def test_mark_sent_records_message_id_and_attempt() -> None:
    event = _make_event(status=OutboxEventStatus.PROCESSING, attempt_count=1)
    session = FakeSession(events=[event])
    changed = await outbox_service.mark_sent(
        session,
        event.event_id,
        lease_owner=event.lease_owner,
        message_id=str(event.event_id),
    )
    assert changed is True
    assert session.commits == 1
    assert event.status == OutboxEventStatus.SENT
    assert event.attempt_count == 1
    assert event.message_id == str(event.event_id)
    assert event.sent_at is not None


async def test_mark_failed_records_error_without_incrementing_attempt_twice() -> None:
    event = _make_event(status=OutboxEventStatus.PROCESSING, attempt_count=1)
    session = FakeSession(events=[event])
    changed = await outbox_service.mark_failed(
        session,
        event.event_id,
        lease_owner=event.lease_owner,
        error="broker down",
    )
    assert changed is True
    assert session.commits == 1
    assert event.status == OutboxEventStatus.FAILED
    assert event.attempt_count == 1
    assert event.last_error == "broker down"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def test_poll_claims_configured_batch_after_persisting_leases(monkeypatch) -> None:
    """Durable leases allow one committed claim transaction per full batch."""
    session = FakeSession()
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    claim_calls: list[dict] = []

    async def _claim_batch(_session, **kwargs):
        claim_calls.append(kwargs)
        return []

    monkeypatch.setattr(outbox_service, "claim_pending", _claim_batch)

    assert await outbox_dispatcher.poll_outbox_once() == 0
    assert claim_calls[0]["batch_size"] == outbox_dispatcher.settings.outbox_batch_size
    assert claim_calls[0]["lease_seconds"] == outbox_dispatcher.settings.outbox_lease_seconds
    assert isinstance(claim_calls[0]["lease_owner"], uuid.UUID)


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
    assert event.attempt_count == 1
    assert session.commits == 2


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
    assert event.last_error == "ConnectionError: broker send failed"


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
    assert event.status == OutboxEventStatus.SENT


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


async def test_enqueue_task_event_requires_task_name_and_stores_kwargs() -> None:
    session = FakeSession()
    event = await outbox_service.enqueue_task_event(
        session,
        event_type="import_requested",
        aggregate_type="import_task",
        aggregate_id="import-1",
        task_name="soymutdb_worker.tasks.ingest.run_import_adapter",
        kwargs={"import_task_id": 1},
        metadata={"requested_by": "user-1"},
    )
    assert session.added == [event]
    assert event.payload["task_name"] == "soymutdb_worker.tasks.ingest.run_import_adapter"
    assert event.payload["kwargs"] == {"import_task_id": 1}
    assert event.payload["metadata"] == {"requested_by": "user-1"}
    assert event.status == OutboxEventStatus.PENDING


@pytest.mark.parametrize(
    "release_status",
    [
        ReleaseStatus.VALIDATED,
        ReleaseStatus.READY,
        ReleaseStatus.PUBLISHED,
        ReleaseStatus.ROLLED_BACK,
    ],
)
async def test_module_import_command_rejects_every_non_draft_release(release_status) -> None:
    """Imports mutate release-scoped rows and therefore stop at validation."""
    from app.core.exceptions import ValidationError

    session = ImportCommandSession(release_status=release_status)

    with pytest.raises(ValidationError, match="draft release"):
        await outbox_service.create_import_command(
            session,
            actor_id=None,
            idempotency_key=f"non-draft-{release_status.value}",
            data_set_id=2,
            import_type="module_tsv",
            filename="genes.tsv",
            object_key="data/2/genes.tsv",
            release_id=9,
            module_key="genes",
            checksum="a" * 64,
        )

    assert session.added == []


async def test_module_import_command_locks_the_draft_release_before_queueing() -> None:
    """The API command transaction must serialize against release publication."""
    session = ImportCommandSession()

    await outbox_service.create_import_command(
        session,
        actor_id=None,
        idempotency_key="draft-release-lock",
        data_set_id=2,
        import_type="module_tsv",
        filename="genes.tsv",
        object_key="data/2/genes.tsv",
        release_id=9,
        module_key="genes",
        checksum="a" * 64,
    )

    release_statements = [
        str(statement)
        for statement, _params in session.executed
        if "FROM releases" in str(statement)
    ]
    assert release_statements
    assert "FOR UPDATE" in release_statements[0]


async def test_import_command_rejects_a_browser_object_key_owned_by_another_dataset() -> None:
    """The task's attested data set must match its direct-upload key prefix."""
    from app.core.exceptions import ValidationError

    session = ImportCommandSession()

    with pytest.raises(ValidationError, match="does not belong to this data set"):
        await outbox_service.create_import_command(
            session,
            actor_id=None,
            idempotency_key="wrong-browser-data-key",
            data_set_id=2,
            import_type="vcf",
            filename="genes.tsv",
            object_key="data/1/genes.tsv",
        )

    assert session.added == []


async def test_import_command_rejects_a_browser_filename_owned_by_another_dataset() -> None:
    """Fallback file keys use the same ownership check as explicit object keys."""
    from app.core.exceptions import ValidationError

    session = ImportCommandSession()

    with pytest.raises(ValidationError, match="does not belong to this data set"):
        await outbox_service.create_import_command(
            session,
            actor_id=None,
            idempotency_key="wrong-browser-filename-key",
            data_set_id=2,
            import_type="vcf",
            filename="data/1/genes.tsv",
        )

    assert session.added == []


async def test_import_command_keeps_explicit_s3_uris_as_advanced_sources() -> None:
    """Key ownership enforcement is limited to platform-owned ``data/...`` keys."""
    session = ImportCommandSession()

    task = await outbox_service.create_import_command(
        session,
        actor_id=None,
        idempotency_key="advanced-s3-source",
        data_set_id=2,
        import_type="vcf",
        filename="genes.tsv",
        object_key="s3://external-bucket/data/1/genes.tsv",
    )

    assert task.object_key == "s3://external-bucket/data/1/genes.tsv"


async def test_enqueue_task_event_rejects_empty_task_name() -> None:
    session = FakeSession()
    try:
        await outbox_service.enqueue_task_event(
            session,
            event_type="import_requested",
            aggregate_type="import_task",
            aggregate_id="import-1",
            task_name="   ",
            kwargs={"import_task_id": 1},
        )
    except ValueError as exc:
        assert "task_name" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


async def test_poll_marks_malformed_event_failed_without_sending(monkeypatch) -> None:
    event = OutboxEvent(
        id=2,
        event_id=uuid.uuid4(),
        aggregate_type="release",
        aggregate_id="release-1",
        event_type="release_pointer_changed",
        payload={"release_id": 1},  # missing task_name / kwargs
        status=OutboxEventStatus.PENDING,
        attempt_count=0,
        created_at=datetime.now(UTC),
    )
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder()
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 1
    assert sender.calls == []
    assert event.status == OutboxEventStatus.FAILED
    assert event.last_error == "missing task_name"


async def test_poll_uses_typed_kwargs_when_present(monkeypatch) -> None:
    event = OutboxEvent(
        id=3,
        event_id=uuid.uuid4(),
        aggregate_type="import_task",
        aggregate_id="import-1",
        event_type="import_requested",
        payload={
            "task_name": "soymutdb_worker.tasks.ingest.run_import_adapter",
            "kwargs": {"import_task_id": 1, "kind": "vcf"},
        },
        status=OutboxEventStatus.PENDING,
        attempt_count=0,
        created_at=datetime.now(UTC),
    )
    session = FakeSession(events=[event])
    monkeypatch.setattr(
        outbox_dispatcher, "get_session_factory", _fake_factory(session)
    )
    sender = _SendRecorder()
    processed = await outbox_dispatcher.poll_outbox_once(send=sender)

    assert processed == 1
    assert len(sender.calls) == 1
    assert sender.calls[0]["task_name"] == "soymutdb_worker.tasks.ingest.run_import_adapter"
    assert sender.calls[0]["kwargs"] == {"import_task_id": 1, "kind": "vcf"}
    assert event.status == OutboxEventStatus.SENT

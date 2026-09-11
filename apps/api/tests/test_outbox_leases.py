"""Durable lease and fencing contracts for the transactional outbox.

These tests use stateful fake sessions because the local test environment has
no PostgreSQL service.  SQL predicates are compiled with the PostgreSQL
dialect so the owner/expiry fencing contract is still asserted explicitly.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.dialects import postgresql

from app.core import outbox_dispatcher
from app.core.config import Settings
from app.core.metrics import OUTBOX_DELIVERY_EXHAUSTED_TOTAL
from app.core.task_contract import BLAST_RUN_TASK
from app.models.outbox import OutboxEvent, OutboxEventStatus
from app.services import outbox_service


class _Scalars:
    def __init__(self, items: list[OutboxEvent]) -> None:
        self._items = items

    def all(self) -> list[OutboxEvent]:
        return self._items


class _Result:
    def __init__(
        self,
        rows: list[OutboxEvent] | None = None,
        *,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


def _status_value(event: OutboxEvent) -> str:
    return getattr(event.status, "value", event.status)


class _ClaimSession:
    """Shared-state session that emulates claim eligibility and commits."""

    def __init__(
        self,
        events: list[OutboxEvent],
        *,
        now: datetime,
        max_attempts: int = 5,
    ) -> None:
        self.events = events
        self.now = now
        self.max_attempts = max_attempts
        self.statements: list[Any] = []
        self.commits = 0
        self.scalar_calls = 0

    async def scalar(self, statement: Any) -> datetime:
        self.scalar_calls += 1
        self.statements.append(statement)
        return self.now

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        del params
        self.statements.append(statement)
        if getattr(statement, "is_update", False):
            settled = 0
            for event in self.events:
                if (
                    _status_value(event) == "processing"
                    and event.attempt_count >= self.max_attempts
                    and event.lease_until is not None
                    and event.lease_until <= self.now
                ):
                    event.status = OutboxEventStatus.FAILED
                    event.sent_at = None
                    event.lease_owner = None
                    event.lease_until = None
                    event.last_error = "delivery lease expired after maximum attempts"
                    settled += 1
            return _Result(rowcount=settled)

        claimable: list[OutboxEvent] = []
        for event in self.events:
            if event.attempt_count >= self.max_attempts:
                continue
            status = _status_value(event)
            if status in {"pending", "failed"}:
                claimable.append(event)
            elif (
                status == "processing"
                and event.lease_until is not None
                and event.lease_until <= self.now
            ):
                claimable.append(event)

        claimable.sort(key=lambda event: (event.created_at, event.id))
        limit_clause = getattr(statement, "_limit_clause", None)
        limit = getattr(limit_clause, "value", len(claimable))
        return _Result(claimable[:limit])

    async def commit(self) -> None:
        self.commits += 1


class _CommitFailingClaimSession(_ClaimSession):
    """Claim session that proves metrics are not recorded before commit."""

    async def commit(self) -> None:
        self.commits += 1
        raise RuntimeError("simulated commit failure")


class _UpdateSession:
    """Statement recorder used to verify conditional update fencing."""

    def __init__(self, *, rowcount: int) -> None:
        self.rowcount = rowcount
        self.statements: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        del params
        self.statements.append(statement)
        return _Result(rowcount=self.rowcount)

    async def commit(self) -> None:
        self.commits += 1


def _event(
    *,
    status: OutboxEventStatus | str = OutboxEventStatus.PENDING,
    attempt_count: int = 0,
    lease_owner: uuid.UUID | None = None,
    lease_until: datetime | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        id=1,
        event_id=uuid.uuid4(),
        aggregate_type="blast_job",
        aggregate_id="job-1",
        event_type="blast_job.run",
        payload={"task_name": BLAST_RUN_TASK, "secret": "do-not-log"},
        status=status,
        attempt_count=attempt_count,
        lease_owner=lease_owner,
        lease_until=lease_until,
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _compiled(statement: Any) -> tuple[str, dict[str, Any]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


async def test_claim_commits_processing_lease_and_attempt_before_return() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    owner = uuid.uuid4()
    event = _event()
    session = _ClaimSession([event], now=now)

    claimed = await outbox_service.claim_pending(
        session,
        batch_size=10,
        max_attempts=5,
        lease_owner=owner,
        lease_seconds=30,
        now=now,
    )

    assert claimed == [event]
    assert session.commits == 1
    assert event.status == OutboxEventStatus.PROCESSING
    assert event.attempt_count == 1
    assert event.lease_owner == owner
    assert event.lease_until == now + timedelta(seconds=30)
    sql, _ = _compiled(session.statements[0])
    assert "FOR UPDATE" in sql
    assert "SKIP LOCKED" in sql


async def test_claim_uses_database_clock_when_not_explicitly_injected() -> None:
    database_now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    owner = uuid.uuid4()
    event = _event()
    session = _ClaimSession([event], now=database_now)

    await outbox_service.claim_pending(
        session,
        lease_owner=owner,
        lease_seconds=30,
    )

    assert session.scalar_calls == 1
    assert event.lease_until == database_now + timedelta(seconds=30)


async def test_active_processing_lease_is_not_claimable() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    event = _event(
        status="processing",
        attempt_count=1,
        lease_owner=uuid.uuid4(),
        lease_until=now + timedelta(seconds=1),
    )
    session = _ClaimSession([event], now=now)

    claimed = await outbox_service.claim_pending(
        session,
        lease_owner=uuid.uuid4(),
        lease_seconds=30,
        now=now,
    )

    assert claimed == []
    assert session.commits == 1
    assert event.attempt_count == 1


async def test_expired_processing_lease_is_reclaimed_with_new_fence() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    old_owner = uuid.uuid4()
    new_owner = uuid.uuid4()
    event = _event(
        status="processing",
        attempt_count=1,
        lease_owner=old_owner,
        lease_until=now - timedelta(microseconds=1),
    )
    session = _ClaimSession([event], now=now)

    claimed = await outbox_service.claim_pending(
        session,
        lease_owner=new_owner,
        lease_seconds=30,
        now=now,
    )

    assert claimed == [event]
    assert event.status == OutboxEventStatus.PROCESSING
    assert event.attempt_count == 2
    assert event.lease_owner == new_owner
    assert event.lease_until == now + timedelta(seconds=30)


async def test_expired_final_attempt_is_not_reclaimed_or_marked_sent() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    event = _event(
        status="processing",
        attempt_count=5,
        lease_owner=uuid.uuid4(),
        lease_until=now - timedelta(seconds=1),
    )
    session = _ClaimSession([event], now=now, max_attempts=5)
    exhausted_before = OUTBOX_DELIVERY_EXHAUSTED_TOTAL._value.get()

    claimed = await outbox_service.claim_pending(
        session,
        max_attempts=5,
        lease_owner=uuid.uuid4(),
        lease_seconds=30,
        now=now,
    )

    assert claimed == []
    assert event.status == OutboxEventStatus.FAILED
    assert event.sent_at is None
    assert event.attempt_count == 5
    assert event.lease_owner is None
    assert event.lease_until is None
    assert OUTBOX_DELIVERY_EXHAUSTED_TOTAL._value.get() == exhausted_before + 1

    # A subsequent poll cannot reclaim or re-count an exhausted delivery.
    assert await outbox_service.claim_pending(
        session,
        max_attempts=5,
        lease_owner=uuid.uuid4(),
        lease_seconds=30,
        now=now,
    ) == []
    assert OUTBOX_DELIVERY_EXHAUSTED_TOTAL._value.get() == exhausted_before + 1
    cleanup_statement = next(
        statement
        for statement in session.statements
        if getattr(statement, "is_update", False)
    )
    sql, _ = _compiled(cleanup_statement)
    assert "outbox_events.status" in sql
    assert "outbox_events.attempt_count >=" in sql
    assert "outbox_events.lease_until <=" in sql


async def test_exhausted_lease_does_not_increment_metric_when_commit_fails() -> None:
    now = datetime(2026, 8, 19, 8, tzinfo=UTC)
    event = _event(
        status="processing",
        attempt_count=5,
        lease_owner=uuid.uuid4(),
        lease_until=now - timedelta(seconds=1),
    )
    session = _CommitFailingClaimSession([event], now=now, max_attempts=5)
    exhausted_before = OUTBOX_DELIVERY_EXHAUSTED_TOTAL._value.get()

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await outbox_service.claim_pending(
            session,
            max_attempts=5,
            lease_owner=uuid.uuid4(),
            lease_seconds=30,
            now=now,
        )

    assert OUTBOX_DELIVERY_EXHAUSTED_TOTAL._value.get() == exhausted_before


async def test_stale_owner_cannot_complete_reclaimed_event() -> None:
    event_id = uuid.uuid4()
    stale_owner = uuid.uuid4()
    session = _UpdateSession(rowcount=0)

    changed = await outbox_service.mark_sent(
        session,
        event_id,
        lease_owner=stale_owner,
        message_id=str(event_id),
        now=datetime(2026, 8, 19, 8, tzinfo=UTC),
    )

    assert changed is False
    assert session.commits == 1
    sql, params = _compiled(session.statements[0])
    assert "outbox_events.status" in sql
    assert "outbox_events.lease_owner" in sql
    assert "outbox_events.lease_until >" in sql
    assert stale_owner in params.values()


async def test_finalization_uses_database_clock_by_default() -> None:
    event_id = uuid.uuid4()
    owner = uuid.uuid4()
    session = _UpdateSession(rowcount=1)

    changed = await outbox_service.mark_sent(
        session,
        event_id,
        lease_owner=owner,
        message_id=str(event_id),
    )

    assert changed is True
    sql, _ = _compiled(session.statements[0])
    assert "now()" in sql.lower()


async def test_finalization_does_not_increment_attempt_twice() -> None:
    event_id = uuid.uuid4()
    owner = uuid.uuid4()
    session = _UpdateSession(rowcount=1)

    changed = await outbox_service.mark_failed(
        session,
        event_id,
        lease_owner=owner,
        error="broker unavailable",
        now=datetime(2026, 8, 19, 8, tzinfo=UTC),
    )

    assert changed is True
    sql, params = _compiled(session.statements[0])
    set_clause = sql.split(" WHERE ", maxsplit=1)[0]
    assert "attempt_count" not in set_clause
    assert "lease_owner=%(lease_owner" in set_clause
    assert "lease_until=%(lease_until" in set_clause
    assert None in params.values()


async def test_heartbeat_renews_only_live_leases_owned_by_caller() -> None:
    event_ids = [uuid.uuid4(), uuid.uuid4()]
    owner = uuid.uuid4()
    session = _UpdateSession(rowcount=2)

    renewed = await outbox_service.renew_leases(
        session,
        event_ids,
        lease_owner=owner,
        lease_seconds=45,
        now=datetime(2026, 8, 19, 8, tzinfo=UTC),
    )

    assert renewed == 2
    assert session.commits == 1
    sql, params = _compiled(session.statements[0])
    assert "outbox_events.event_id IN" in sql
    assert "outbox_events.status" in sql
    assert "outbox_events.lease_owner" in sql
    assert "outbox_events.lease_until >" in sql
    assert owner in params.values()


def test_outbox_batch_and_lease_settings_are_bounded() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, outbox_batch_size=0)
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, outbox_batch_size=1001)
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None, outbox_lease_seconds=0)

    configured = Settings(_env_file=None)
    assert 1 < configured.outbox_batch_size <= 1000
    assert configured.outbox_lease_seconds >= 5


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


class _SessionMaker:
    def __init__(self, session: Any) -> None:
        self.session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.session)


class _DispatcherSession:
    async def rollback(self) -> None:
        return None


async def test_dispatcher_claims_configured_batch_with_fencing_owner(monkeypatch) -> None:
    session = _DispatcherSession()
    monkeypatch.setattr(
        outbox_dispatcher,
        "get_session_factory",
        lambda: _SessionMaker(session),
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "settings",
        SimpleNamespace(outbox_batch_size=23, outbox_lease_seconds=30),
    )
    claim_calls: list[dict[str, Any]] = []

    async def claim(_session: Any, **kwargs: Any) -> list[OutboxEvent]:
        claim_calls.append(kwargs)
        return []

    monkeypatch.setattr(outbox_service, "claim_pending", claim)

    assert await outbox_dispatcher.poll_outbox_once() == 0
    assert len(claim_calls) == 1
    assert claim_calls[0]["batch_size"] == 23
    assert claim_calls[0]["lease_seconds"] == 30
    assert isinstance(claim_calls[0]["lease_owner"], uuid.UUID)


async def test_long_send_runs_batch_heartbeat_until_finalized(monkeypatch) -> None:
    event = _event()
    session = _DispatcherSession()
    monkeypatch.setattr(
        outbox_dispatcher,
        "get_session_factory",
        lambda: _SessionMaker(session),
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "settings",
        SimpleNamespace(outbox_batch_size=8, outbox_lease_seconds=0.06),
    )
    release_send = threading.Event()
    renew_calls: list[tuple[list[uuid.UUID], uuid.UUID]] = []
    finalized_by: list[uuid.UUID] = []

    async def claim(_session: Any, **kwargs: Any) -> list[OutboxEvent]:
        event.status = "processing"
        event.lease_owner = kwargs["lease_owner"]
        event.lease_until = datetime.now(UTC) + timedelta(
            seconds=kwargs["lease_seconds"]
        )
        event.attempt_count += 1
        return [event]

    async def renew(
        _session: Any,
        event_ids: list[uuid.UUID],
        *,
        lease_owner: uuid.UUID,
        **kwargs: Any,
    ) -> int:
        del kwargs
        renew_calls.append((event_ids, lease_owner))
        release_send.set()
        return len(event_ids)

    async def mark_sent(
        _session: Any,
        _event_id: uuid.UUID,
        *,
        lease_owner: uuid.UUID,
        **kwargs: Any,
    ) -> bool:
        del kwargs
        finalized_by.append(lease_owner)
        return True

    def send(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        if not release_send.wait(timeout=1):
            raise TimeoutError("heartbeat did not run while broker send blocked")

    monkeypatch.setattr(outbox_service, "claim_pending", claim)
    monkeypatch.setattr(outbox_service, "renew_leases", renew, raising=False)
    monkeypatch.setattr(outbox_service, "mark_sent", mark_sent)

    assert await outbox_dispatcher.poll_outbox_once(send=send) == 1
    assert renew_calls
    assert renew_calls[0][0] == [event.event_id]
    assert renew_calls[0][1] == event.lease_owner
    assert finalized_by == [event.lease_owner]


async def test_dispatch_failure_log_does_not_include_payload(monkeypatch) -> None:
    event = _event()
    session = _DispatcherSession()
    monkeypatch.setattr(
        outbox_dispatcher,
        "get_session_factory",
        lambda: _SessionMaker(session),
    )
    monkeypatch.setattr(
        outbox_dispatcher,
        "settings",
        SimpleNamespace(outbox_batch_size=8, outbox_lease_seconds=30),
    )
    warnings: list[tuple[str, dict[str, Any]]] = []
    failed_errors: list[str] = []

    class _Logger:
        def warning(self, name: str, **kwargs: Any) -> None:
            warnings.append((name, kwargs))

    async def claim(_session: Any, **kwargs: Any) -> list[OutboxEvent]:
        event.lease_owner = kwargs.get("lease_owner")
        return [event]

    async def mark_failed(*args: Any, **kwargs: Any) -> bool:
        del args
        failed_errors.append(kwargs["error"])
        return True

    def send(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError(f"broker rejected {event.payload!r}")

    monkeypatch.setattr(outbox_dispatcher, "logger", _Logger())
    monkeypatch.setattr(outbox_service, "claim_pending", claim)
    monkeypatch.setattr(outbox_service, "mark_failed", mark_failed)

    assert await outbox_dispatcher.poll_outbox_once(send=send) == 1
    assert warnings
    assert "do-not-log" not in repr(warnings)
    assert "do-not-log" not in repr(failed_errors)


async def test_poll_loop_logs_exception_type_without_exception_text(monkeypatch) -> None:
    stop_event = asyncio.Event()
    stop_event.set()
    errors: list[tuple[str, dict[str, Any]]] = []
    warnings: list[tuple[str, dict[str, Any]]] = []
    exceptions: list[str] = []

    class _Logger:
        def info(self, name: str, **kwargs: Any) -> None:
            del name, kwargs

        def error(self, name: str, **kwargs: Any) -> None:
            errors.append((name, kwargs))

        def warning(self, name: str, **kwargs: Any) -> None:
            warnings.append((name, kwargs))

        def exception(self, name: str, **kwargs: Any) -> None:
            del kwargs
            exceptions.append(name)

    async def fail_poll(**kwargs: Any) -> int:
        del kwargs
        raise RuntimeError("do-not-log")

    async def cleanup() -> int:
        return 0

    async def refresh_metrics() -> None:
        return None

    monkeypatch.setattr(outbox_dispatcher, "logger", _Logger())
    monkeypatch.setattr(outbox_dispatcher, "poll_outbox_once", fail_poll)
    monkeypatch.setattr(outbox_dispatcher, "cleanup_outbox", cleanup)
    monkeypatch.setattr(outbox_dispatcher, "refresh_outbox_metrics", refresh_metrics)
    monkeypatch.setattr(
        outbox_dispatcher,
        "settings",
        SimpleNamespace(
            outbox_poll_interval_seconds=1,
            outbox_cleanup_interval_seconds=3600,
        ),
    )

    await outbox_dispatcher.run_outbox_dispatcher(stop_event)

    assert exceptions == []
    assert warnings == []
    assert errors == [("outbox.poll_error", {"error_type": "RuntimeError"})]

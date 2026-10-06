"""W5 outbox: idempotency, version guard, dead-lettering, reconciliation.

`_deliver` raises NotImplementedError by design — the transport is unconfirmed
— so everything above it is testable with a stubbed delivery. The properties
asserted here are the ones the plan makes non-negotiable: one remote record per
idempotency key, no remote write carrying a stale version, and a dead letter a
human can replay without creating a duplicate.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from soymutdb_worker.wecom.contracts import (
    OutboundRecord,
    OutboundStatus,
    ReconciliationFinding,
)
from soymutdb_worker.wecom.outbox import (
    DeliveryOutcome,
    FrozenClock,
    OutboxProcessor,
    SystemClock,
    reconcile,
)

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_OK = DeliveryOutcome(ok=True)
_RETRYABLE = DeliveryOutcome(ok=False, error="upstream 500", retryable=True)
_PERMANENT = DeliveryOutcome(ok=False, error="invalid field", retryable=False)


class _InMemoryStore:
    """Minimal OutboxStore: no persistence, no ORM, honest about both."""

    def __init__(self) -> None:
        self.records: dict[str, OutboundRecord] = {}
        self.duplicate_appends = 0

    def append(self, record: OutboundRecord) -> OutboundRecord:
        existing = self.records.get(record.idempotency_key)
        if existing is not None:
            self.duplicate_appends += 1
            return existing
        self.records[record.idempotency_key] = record
        return record

    def get(self, idempotency_key: str) -> OutboundRecord | None:
        return self.records.get(idempotency_key)

    def due(self, *, now: datetime, limit: int) -> list[OutboundRecord]:
        return [
            record
            for record in self.records.values()
            if record.status is OutboundStatus.PENDING
            and (record.created_at is None or record.created_at <= now)
        ][:limit]

    def update(self, record: OutboundRecord) -> OutboundRecord:
        self.records[record.idempotency_key] = record
        return record

    def dead_letters(self) -> list[OutboundRecord]:
        return [r for r in self.records.values() if r.status is OutboundStatus.DEAD]


class _AdvancingClock:
    """A clock the test moves by hand.

    ``FrozenClock`` cannot drive the retry path: ``_schedule_retry`` sets
    ``created_at`` to ``now + backoff`` and ``due()`` skips anything created in
    the future, so a frozen clock makes a retried record permanently invisible.
    A real clock advances on its own, so the test has to supply that motion.
    """

    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant

    def advance(self, seconds: float) -> None:
        self.instant += timedelta(seconds=seconds)


def _processor(
    outcome: DeliveryOutcome = _OK,
) -> tuple[OutboxProcessor, _InMemoryStore, list[OutboundRecord]]:
    store = _InMemoryStore()
    processor = OutboxProcessor(store=store, clock=FrozenClock(_NOW))  # type: ignore[arg-type]
    attempted: list[OutboundRecord] = []

    def _deliver(record: OutboundRecord) -> DeliveryOutcome:
        attempted.append(record)
        return outcome

    processor._deliver = _deliver  # type: ignore[method-assign]
    return processor, store, attempted


def _enqueue(processor: OutboxProcessor, key: str = "k-1", *, version: int = 1) -> OutboundRecord:
    return processor.enqueue(
        idempotency_key=key,
        capability="bitable.record.upsert",
        tenant_key="t-1",
        payload={"title": "hello"},
        object_version=version,
    )


class TestEnqueue:
    def test_a_key_is_stored_once(self) -> None:
        processor, store, _ = _processor()

        first = _enqueue(processor)
        second = _enqueue(processor)

        assert first.idempotency_key == second.idempotency_key
        assert len(store.records) == 1
        assert store.duplicate_appends == 1

    def test_distinct_keys_are_distinct_records(self) -> None:
        processor, store, _ = _processor()

        _enqueue(processor, "k-1")
        _enqueue(processor, "k-2")

        assert set(store.records) == {"k-1", "k-2"}

    def test_an_enqueued_record_starts_pending(self) -> None:
        processor, _, _ = _processor()

        assert _enqueue(processor).status is OutboundStatus.PENDING


class TestProcessDue:
    def test_a_success_is_recorded_and_counted(self) -> None:
        processor, store, attempted = _processor(
            DeliveryOutcome(ok=True, remote_record_id="rec-9", remote_version=1)
        )
        _enqueue(processor)

        counts = processor.process_due()

        stored = store.get("k-1")
        assert stored is not None
        assert stored.status is OutboundStatus.SUCCEEDED
        assert stored.attempts == 1
        assert counts[OutboundStatus.SUCCEEDED.value] == 1
        assert len(attempted) == 1

    def test_a_retryable_failure_keeps_the_record_pending(self) -> None:
        processor, store, _ = _processor(_RETRYABLE)
        _enqueue(processor)

        processor.process_due()

        stored = store.get("k-1")
        assert stored is not None
        assert stored.status is OutboundStatus.PENDING
        assert stored.attempts == 1
        assert stored.last_error == "upstream 500"

    def test_a_permanent_failure_dead_letters_immediately(self) -> None:
        """A non-retryable error must not spend the retry budget.

        Retrying a rejected payload is how one bad record turns into an
        upstream denial-of-service.
        """
        processor, store, _ = _processor(_PERMANENT)
        _enqueue(processor)

        processor.process_due()

        stored = store.get("k-1")
        assert stored is not None
        assert stored.status is OutboundStatus.DEAD
        assert stored.dead_letter_reason == "non-retryable error"
        assert store.dead_letters()

    def test_a_retry_is_scheduled_into_the_future_not_run_immediately(
        self,
    ) -> None:
        """Backoff has to actually delay the next attempt.

        Without the future ``created_at`` a failing upstream would be hammered
        once per batch for the whole outage.
        """
        store = _InMemoryStore()
        clock = _AdvancingClock(_NOW)
        processor = OutboxProcessor(store=store, clock=clock)  # type: ignore[arg-type]
        attempted: list[OutboundRecord] = []
        processor._deliver = lambda record: (attempted.append(record), _RETRYABLE)[1]  # type: ignore[method-assign]
        _enqueue(processor)

        processor.process_due()
        # Still inside the backoff window: the record must not be retried.
        processor.process_due()
        assert len(attempted) == 1

        clock.advance(3600)
        processor.process_due()
        assert len(attempted) == 2

    def test_retries_are_exhausted_into_a_dead_letter(self) -> None:
        store = _InMemoryStore()
        clock = _AdvancingClock(_NOW)
        processor = OutboxProcessor(store=store, clock=clock)  # type: ignore[arg-type]
        processor._deliver = lambda record: _RETRYABLE  # type: ignore[method-assign]
        _enqueue(processor)

        for _ in range(processor.max_attempts + 2):
            processor.process_due()
            clock.advance(3600)

        stored = store.get("k-1")
        assert stored is not None
        assert stored.status is OutboundStatus.DEAD
        assert stored.dead_letter_reason == "retryable"
        assert stored.attempts >= processor.max_attempts
        assert store.dead_letters()

    def test_a_dead_letter_stops_consuming_attempts(self) -> None:
        processor, _, attempted = _processor(_PERMANENT)
        _enqueue(processor)

        processor.process_due()
        processor.process_due()

        assert len(attempted) == 1

    def test_one_failing_record_does_not_block_the_next(self) -> None:
        """A batch pass isolates failures.

        Otherwise the first bad record would starve every record queued behind
        it, which is how a single upstream change silently stops all syncing.
        """
        store = _InMemoryStore()
        processor = OutboxProcessor(store=store, clock=FrozenClock(_NOW))  # type: ignore[arg-type]
        seen: list[str] = []

        def _deliver(record: OutboundRecord) -> DeliveryOutcome:
            seen.append(record.idempotency_key)
            return _PERMANENT if record.idempotency_key == "k-1" else _OK

        processor._deliver = _deliver  # type: ignore[method-assign]
        _enqueue(processor, "k-1")
        _enqueue(processor, "k-2")

        processor.process_due()

        assert set(seen) == {"k-1", "k-2"}
        assert store.get("k-2") is not None
        assert store.get("k-2").status is OutboundStatus.SUCCEEDED  # type: ignore[union-attr]


class TestApplyRemoteResult:
    def test_a_stale_remote_version_retries_instead_of_succeeding(self) -> None:
        """A remote row older than ours must not be accepted as current.

        Treating it as success would let a slow response from an earlier edit
        overwrite a newer one, and the caller would see a confirmed write for a
        change that lost.
        """
        processor, store, _ = _processor()
        record = _enqueue(processor, version=5)

        updated = processor.apply_remote_result(
            record,
            DeliveryOutcome(ok=True, remote_record_id="rec-9", remote_version=3),
            now=_NOW,
        )

        assert updated.status is OutboundStatus.PENDING
        assert updated.last_error == "remote version is behind local"
        assert store.get("k-1") is not None

    def test_a_matching_version_succeeds(self) -> None:
        processor, _, _ = _processor()
        record = _enqueue(processor, version=5)

        updated = processor.apply_remote_result(
            record,
            DeliveryOutcome(ok=True, remote_record_id="rec-9", remote_version=5),
            now=_NOW,
        )

        assert updated.status is OutboundStatus.SUCCEEDED

    def test_a_newer_remote_version_succeeds(self) -> None:
        processor, _, _ = _processor()
        record = _enqueue(processor, version=3)

        updated = processor.apply_remote_result(
            record,
            DeliveryOutcome(ok=True, remote_record_id="rec-9", remote_version=7),
            now=_NOW,
        )

        assert updated.status is OutboundStatus.SUCCEEDED

    def test_no_remote_version_at_all_is_not_a_conflict(self) -> None:
        """Absence of a version is not evidence of staleness.

        A capability that does not report versions must still be able to
        succeed, or the guard would block every write through it.
        """
        processor, _, _ = _processor()
        record = _enqueue(processor, version=5)

        updated = processor.apply_remote_result(
            record, DeliveryOutcome(ok=True, remote_record_id="rec-9"), now=_NOW
        )

        assert updated.status is OutboundStatus.SUCCEEDED

    def test_attempts_advance_once_per_result(self) -> None:
        processor, _, _ = _processor()
        record = _enqueue(processor)

        first = processor.apply_remote_result(record, _RETRYABLE, now=_NOW)
        second = processor.apply_remote_result(first, _RETRYABLE, now=_NOW)

        assert (first.attempts, second.attempts) == (1, 2)


class TestReplayDeadLetter:
    def test_replay_resets_attempts_but_keeps_the_key(self) -> None:
        """A replayed dead letter must reuse its idempotency key.

        A fresh key would create a second remote record for one logical
        submission, which is the duplication the outbox exists to prevent.
        """
        processor, store, _ = _processor(_PERMANENT)
        _enqueue(processor)
        processor.process_due()
        assert store.dead_letters()

        replayed = processor.replay_dead_letter("k-1")

        assert replayed is not None
        assert replayed.idempotency_key == "k-1"
        assert replayed.attempts == 0
        assert replayed.status is OutboundStatus.PENDING
        assert len(store.records) == 1

    def test_a_replayed_dead_letter_can_succeed(self) -> None:
        processor, store, _ = _processor(_PERMANENT)
        _enqueue(processor)
        processor.process_due()

        processor._deliver = lambda record: _OK  # type: ignore[method-assign]
        processor.replay_dead_letter("k-1")
        processor.process_due()

        assert store.get("k-1") is not None
        assert store.get("k-1").status is OutboundStatus.SUCCEEDED  # type: ignore[union-attr]

    def test_replaying_an_unknown_key_returns_nothing(self) -> None:
        processor, _, _ = _processor()

        assert processor.replay_dead_letter("absent") is None

    def test_replaying_a_live_record_leaves_it_alone(self) -> None:
        processor, _, _ = _processor()
        _enqueue(processor)

        assert processor.replay_dead_letter("k-1") is None


class TestReconcile:
    def _finding(self, object_id: str, *, version: int = 3) -> ReconciliationFinding:
        return ReconciliationFinding(
            table_key="tbl-1",
            local_object_id=object_id,
            remote_record_id=f"rec-{object_id}",
            divergence="remote version behind local",
            local_version=version,
            observed_remote_version=version - 1,
        )

    def test_a_remote_divergence_is_reported(self) -> None:
        findings = reconcile([], [self._finding("local-1")])

        assert [f.local_object_id for f in findings] == ["local-1"]
        assert findings[0].divergence == "remote version behind local"

    def test_a_local_row_the_remote_never_showed_is_reported(self) -> None:
        """Silent absence is divergence too.

        An operator deleting a Bitable row produces no failed call, so without
        this the record would look permanently healthy.
        """
        findings = reconcile([("local-1", "rec-local-1", 4)], [])

        assert len(findings) == 1
        assert findings[0].divergence == "remote record not observed during reconciliation"
        assert findings[0].local_version == 4

    def test_an_observed_row_is_not_re_reported(self) -> None:
        findings = reconcile(
            [("local-1", "rec-local-1", 4)], [self._finding("local-1", version=4)]
        )

        assert [f.local_object_id for f in findings] == ["local-1"]
        assert len(findings) == 1

    def test_an_observed_row_adds_no_second_finding(self) -> None:
        """Reconciliation is a merge, not a restatement.

        A row that both sides saw must not be reported twice; the pass adds
        findings, it does not re-list the observations it was given.
        """
        observed = self._finding("local-1")

        findings = reconcile(
            [("local-1", observed.remote_record_id, 3)], [observed]
        )

        assert findings == [observed]

    def test_nothing_on_either_side_reports_nothing(self) -> None:
        assert reconcile([], []) == []


class TestClocks:
    def test_a_frozen_clock_never_moves(self) -> None:
        assert FrozenClock(_NOW).now() == FrozenClock(_NOW).now() == _NOW

    def test_the_system_clock_is_timezone_aware(self) -> None:
        """A naive local time in a retry schedule only breaks on another host."""
        assert SystemClock().now().tzinfo is not None


class TestUnconfirmedTransport:
    def test_delivery_is_refused_until_a_transport_is_bound(self) -> None:
        """The stub seam must stay loud until a real transport is confirmed.

        The four WeCom transports are still unconfirmed official contracts, so
        an unbound processor has to raise rather than quietly succeed.
        """
        store = _InMemoryStore()
        processor = OutboxProcessor(store=store, clock=FrozenClock(_NOW))  # type: ignore[arg-type]
        _enqueue(processor)

        with pytest.raises(NotImplementedError):
            processor.process_due()

    def test_records_survive_being_built_by_hand(self) -> None:
        """The record shape is what the queue and the tests agree on."""
        record = OutboundRecord(
            idempotency_key="k-9",
            capability="bitable.record.upsert",
            tenant_key="t-1",
            payload={"title": "x"},
            object_version=2,
        )

        assert replace(record, attempts=1).attempts == 1
        assert record.status is OutboundStatus.PENDING

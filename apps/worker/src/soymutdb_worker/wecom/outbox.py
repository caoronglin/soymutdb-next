"""Transactional outbox and reconciliation state machine for W5.

## Why an outbox at all

The plan is explicit that "应用 API 写入不继承机器人丢弃失败语义" — an API
write must not be reported as successful because a chat webhook was
best-effort. The existing group robot in `soymutdb_worker/utils/wecom_bot.py`
is exactly that shape: it swallows failures, because losing a notification is
acceptable and blocking a publication on it is not.

Synchronising a Bitable row is a different promise. Once a local object claims
a remote counterpart, "the write happened" and "we told the remote" are two
facts, and the second one fails on its own schedule: token expiry, rate limits,
a remote outage, a conflict. Committing the local transaction and then calling
the remote leaves a window where the local row says "synced" and the remote
says otherwise, and nothing will ever look again.

The outbox closes that window: the intent is written in the *same* transaction
as the local change, and a separate pass performs the remote call. A crash
between the two loses nothing, because the intent is already durable.

## Storage is an interface, not a table

`OutboxStore` is a Protocol so the state machine above it can be exercised
without a database, and so the same rules apply whether the backing store is
PostgreSQL or something else. The concrete table belongs to the API's Alembic
migrations, which are the sole owner of schema lifecycle in this repository —
the worker declares Core columns for compiling statements, exactly as
`soymutdb_worker/tables.py` does, and never creates schema itself.

## Ordering

`object_version` is what makes out-of-order delivery safe. Two workers may
deliver the same object in either order; without a version guard the slower one
wins and silently reverts a newer value. `apply_remote_result` refuses to move
a record backwards, and reports the rejection instead of hiding it.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .contracts import OutboundRecord, OutboundStatus, ReconciliationFinding
from .policy import backoff_delay

logger = logging.getLogger(__name__)


class OutboxStore(Protocol):
    """Durable intent log. Implementations must be transaction-scoped."""

    def append(self, record: OutboundRecord) -> OutboundRecord:
        """Insert or return the existing record for this idempotency key."""

    def get(self, idempotency_key: str) -> OutboundRecord | None: ...

    def due(self, *, now: datetime, limit: int) -> Sequence[OutboundRecord]:
        """Pending records whose next attempt is at or before ``now``."""

    def update(self, record: OutboundRecord) -> OutboundRecord: ...

    def dead_letters(self) -> Sequence[OutboundRecord]: ...


@dataclass(frozen=True)
class DeliveryOutcome:
    """Result of one remote attempt.

    ``remote_version`` is the remote's own version when it reports one. A
    response whose version is older than what we sent is a conflict, not a
    success, and the caller must not treat it as one.
    """

    ok: bool
    remote_record_id: str | None = None
    remote_version: int | None = None
    error: str | None = None
    retryable: bool = True


@dataclass
class OutboxProcessor:
    """Drives records through the outbox lifecycle.

    Holds no transport of its own. The remote call is injected, which keeps the
    state machine testable and keeps this module free of any assumption about
    a WeCom endpoint that has not been confirmed yet.
    """

    store: OutboxStore
    max_attempts: int = 8
    clock: Clock = field(default_factory=lambda: SystemClock())

    # -- enqueue -------------------------------------------------------------------------

    def enqueue(
        self,
        *,
        idempotency_key: str,
        capability: str,
        tenant_key: str,
        payload: dict[str, object],
        object_version: int,
    ) -> OutboundRecord:
        """Record the intent to sync, deduplicating on ``idempotency_key``.

        The caller is expected to have already run the payload through
        `policy.project_outbound_payload`. Re-projecting here would be a second
        place for the rule to live, and a second place to forget it.
        """
        return self.store.append(
            OutboundRecord(
                idempotency_key=idempotency_key,
                capability=capability,
                tenant_key=tenant_key,
                payload=payload,
                object_version=object_version,
                status=OutboundStatus.PENDING,
                created_at=self.clock.now(),
            )
        )

    # -- delivery ------------------------------------------------------------------------

    def process_due(self, *, limit: int = 50) -> dict[str, int]:
        """Attempt every due record once. Returns a per-status count.

        One pass, one attempt per record: a transport that blocks would
        otherwise hold the whole batch, and a failing record must not prevent
        the next one from being tried.
        """
        now = self.clock.now()
        counts = {status.value: 0 for status in OutboundStatus}
        for record in self.store.due(now=now, limit=limit):
            outcome = self._deliver(record)
            updated = self.apply_remote_result(record, outcome, now=now)
            counts[updated.status.value] += 1
        return counts

    def _deliver(self, record: OutboundRecord) -> DeliveryOutcome:
        raise NotImplementedError(
            "OutboxProcessor needs a transport; construct it with one. W5 has no "
            "confirmed WeCom endpoint yet, so there is deliberately no default."
        )

    def apply_remote_result(
        self, record: OutboundRecord, outcome: DeliveryOutcome, *, now: datetime
    ) -> OutboundRecord:
        """Fold a delivery attempt into the stored record.

        A stale remote version is treated as a retryable conflict rather than a
        success: the newer local state still has to land.
        """
        attempts = record.attempts + 1

        stale_remote = (
            outcome.ok
            and outcome.remote_version is not None
            and outcome.remote_version < record.object_version
        )
        if stale_remote:
            logger.warning(
                "wecom.outbox.stale_remote_version",
                extra={
                    "idempotency_key": record.idempotency_key,
                    "local_version": record.object_version,
                    "remote_version": outcome.remote_version,
                },
            )
            return self._schedule_retry(
                record, attempts, error="remote version is behind local", now=now
            )

        if outcome.ok:
            return self.store.update(
                replace(
                    record,
                    status=OutboundStatus.SUCCEEDED,
                    attempts=attempts,
                    last_error=None,
                    payload=record.payload,
                )
            )

        if not outcome.retryable or attempts >= self.max_attempts:
            return self.store.update(
                replace(
                    record,
                    status=OutboundStatus.DEAD,
                    attempts=attempts,
                    last_error=outcome.error,
                    dead_letter_reason="retryable" if outcome.retryable else "non-retryable error",
                )
            )

        return self._schedule_retry(record, attempts, error=outcome.error, now=now)

    def _schedule_retry(
        self, record: OutboundRecord, attempts: int, *, error: str | None, now: datetime
    ) -> OutboundRecord:
        delay = backoff_delay(attempts)
        return self.store.update(
            replace(
                record,
                status=OutboundStatus.PENDING,
                attempts=attempts,
                last_error=error,
                created_at=now + timedelta(seconds=delay),
            )
        )

    # -- operator actions ----------------------------------------------------------------

    def replay_dead_letter(self, idempotency_key: str) -> OutboundRecord | None:
        """Return a dead-lettered record to PENDING for manual replay.

        The attempt counter is reset, because the limit that dead-lettered it
        was reached under conditions the operator has now intervened in. The
        key is kept, so a replay cannot produce a second remote record.
        """
        record = self.store.get(idempotency_key)
        if record is None or record.status is not OutboundStatus.DEAD:
            return None
        return self.store.update(
            replace(
                record,
                status=OutboundStatus.PENDING,
                attempts=0,
                last_error=None,
                dead_letter_reason=None,
                created_at=self.clock.now(),
            )
        )


# --------------------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------------------


def reconcile(
    local_rows: Iterable[tuple[str, str, int]],
    remote_rows: Iterable[ReconciliationFinding],
) -> list[ReconciliationFinding]:
    """Merge local and remote observations into a divergence list.

    A local row with no remote counterpart, or a remote row whose version is
    behind, is a finding. Returning them as data rather than raising is
    deliberate: reconciliation runs on a schedule and must report partial
    divergence without aborting.
    """
    findings = list(remote_rows)
    seen = {(f.local_object_id, f.remote_record_id) for f in findings}
    for local_object_id, remote_record_id, local_version in local_rows:
        if (local_object_id, remote_record_id) not in seen:
            findings.append(
                ReconciliationFinding(
                    table_key="",
                    local_object_id=local_object_id,
                    remote_record_id=remote_record_id,
                    divergence="remote record not observed during reconciliation",
                    local_version=local_version,
                )
            )
    return findings


# --------------------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------------------


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class SystemClock:
    """UTC clock. Timezone-aware, because a naive local time in a retry
    schedule is a bug that only appears on a host in another region."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FrozenClock:
    """Deterministic clock for deterministic runs."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant

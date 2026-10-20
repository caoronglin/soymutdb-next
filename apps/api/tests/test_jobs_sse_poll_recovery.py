"""Regression tests for the SSE poll error handler (P1: unrecoverable stream).

The poll error handler used to swallow the exception without rolling the
session back.  The failed statement aborts the surrounding transaction, so
the next ``db.execute`` raised ``PendingRollbackError`` and the stream
degraded to heartbeats for the rest of its 30-minute life — while logging
one traceback every 2 seconds.

The contract asserted here:

- a transient query failure leaves the poll usable: the *next* cycle must
  return updates again instead of heartbeats forever;
- the failed cycle rolls its transaction back, so no aborted transaction
  is left behind on the pooled connection;
- a database that stays down does not flood the log: the exception is
  rate-limited and the recovery is reported once.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import namedtuple
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import jobs as jobs_module

Row = namedtuple("Row", ["job_type", "job_id", "status", "updated_at"])


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _Recorder:
    """Records the lifecycle of the short-lived poll sessions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def record(self, kind: str, payload: object) -> None:
        self.events.append((kind, payload))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


class _FakePollSession:
    """Short-lived poll session stand-in that can fail on demand."""

    def __init__(
        self,
        recorder: _Recorder,
        rows: list | None = None,
        error: Exception | None = None,
    ) -> None:
        self._recorder = recorder
        self._rows = list(rows or [])
        self._error = error
        self.rollbacks = 0

    async def __aenter__(self) -> _FakePollSession:
        self._recorder.record("open", self)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._recorder.record("close", self)
        return False

    async def execute(self, stmt, params=None) -> _Result:
        self._recorder.record("query", self)
        if self._error is not None:
            raise self._error
        return _Result(self._rows)

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._recorder.record("rollback", self)


class _FakeSessionFactory:
    """Hands out one fake session per cycle (the last one repeats)."""

    def __init__(self, recorder: _Recorder, sessions: list[_FakePollSession]) -> None:
        self._recorder = recorder
        self._sessions = list(sessions)
        self._index = 0
        self.calls = 0

    def __call__(self) -> _FakePollSession:
        self.calls += 1
        session = self._sessions[min(self._index, len(self._sessions) - 1)]
        self._index += 1
        return session


class _SpyRequestSession(AsyncSession):
    """Request-scoped session stand-in; querying it fails the test."""

    def __init__(self) -> None:
        super().__init__()
        self.queries = 0

    async def execute(self, *args, **kwargs):
        self.queries += 1
        raise AssertionError("the request-scoped session must not be used for polling")


class _FakeAsyncio:
    """``asyncio`` stand-in that records the stream's sleep calls."""

    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder
        self._real = asyncio

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def sleep(self, delay, *args, **kwargs):
        self._recorder.record("sleep", delay)
        return await self._real.sleep(0)


class _FakeLogger:
    """structlog stand-in collecting the emitted events."""

    def __init__(self) -> None:
        self.exceptions: list[tuple[str, dict]] = []
        self.infos: list[tuple[str, dict]] = []
        self.warnings: list[tuple[str, dict]] = []

    def exception(self, event: str, **kwargs) -> None:
        self.exceptions.append((event, kwargs))

    def info(self, event: str, **kwargs) -> None:
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))


class _AlwaysConnected:
    """Request stand-in: the client never disconnects."""

    async def is_disconnected(self) -> bool:
        return False


def _install(
    monkeypatch,
    recorder: _Recorder,
    sessions: list[_FakePollSession],
    logger: _FakeLogger | None = None,
) -> _FakeSessionFactory:
    factory = _FakeSessionFactory(recorder, sessions)
    monkeypatch.setattr(jobs_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(jobs_module, "asyncio", _FakeAsyncio(recorder))
    if logger is not None:
        monkeypatch.setattr(jobs_module, "logger", logger)
    return factory


async def _read_frames(body_iterator, count: int) -> list[str]:
    frames: list[str] = []
    async for chunk in body_iterator:
        frames.append(chunk)
        if len(frames) >= count:
            break
    return frames


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPollRecovery:
    async def test_failed_poll_cycle_is_followed_by_a_successful_cycle(
        self, monkeypatch
    ) -> None:
        """A transient failure must not degrade the stream to heartbeats."""
        recorder = _Recorder()
        job_id = uuid.uuid4()
        failing = _FakePollSession(recorder, error=RuntimeError("connection reset"))
        healthy = _FakePollSession(
            recorder, rows=[Row("gwas", job_id, "completed", datetime.now(UTC))]
        )
        _install(monkeypatch, recorder, [failing, healthy])

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            frames = await _read_frames(response.body_iterator, 2)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        # The failed cycle produced no update ...
        assert frames[0] == ": ping\n\n"
        # ... the next cycle recovered and pushed the update.
        assert frames[1].startswith("event: job_update\n")
        assert str(job_id) in frames[1]
        assert "gwas" in frames[1]

    async def test_failed_cycle_rolls_back_its_transaction(self, monkeypatch) -> None:
        """The aborted transaction must not survive the failed cycle."""
        recorder = _Recorder()
        failing = _FakePollSession(recorder, error=RuntimeError("database is down"))
        healthy = _FakePollSession(recorder, rows=[])
        _install(monkeypatch, recorder, [failing, healthy])

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            await _read_frames(response.body_iterator, 2)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert failing.rollbacks == 1
        kinds = recorder.kinds()
        # The rollback happens before the session is handed back.
        assert kinds.index("rollback") < kinds.index("close")

    async def test_repeated_failures_do_not_flood_the_log(self, monkeypatch) -> None:
        """One failing cycle must not log a traceback every 2 seconds."""
        recorder = _Recorder()
        logger = _FakeLogger()
        failing = _FakePollSession(recorder, error=RuntimeError("database is down"))
        _install(monkeypatch, recorder, [failing], logger=logger)

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            frames = await _read_frames(response.body_iterator, 6)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert len(frames) == 6
        # Six failing cycles -> one logged exception, not six.
        assert [event for event, _ in logger.exceptions] == ["jobs_events_poll_error"]

    async def test_recovery_is_reported_once(self, monkeypatch) -> None:
        """The stream reports that the poll works again."""
        recorder = _Recorder()
        logger = _FakeLogger()
        failing = _FakePollSession(recorder, error=RuntimeError("connection reset"))
        healthy = _FakePollSession(
            recorder, rows=[Row("blast", uuid.uuid4(), "running", datetime.now(UTC))]
        )
        _install(monkeypatch, recorder, [failing, healthy], logger=logger)

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            await _read_frames(response.body_iterator, 2)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert [event for event, _ in logger.infos] == ["jobs_events_poll_recovered"]
        assert logger.infos[0][1]["failed_cycles"] == 1

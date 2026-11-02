"""Client-visible contract of the SSE job stream.

The connection-budget fix changed *how* the stream polls PostgreSQL; the
wire format must not change.  These tests pin the parts of the contract a
browser client depends on:

- the ``: ping`` heartbeat comment line when nothing changed;
- the ``event: job_update`` frame with its JSON payload;
- the ``event: stream_end`` frame with ``{"reason": "max_lifetime"}`` when
  the stream reaches its maximum lifetime;
- the clean stop when the client disconnects (no further frames, no
  further database access).
"""

from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import jobs as jobs_module

Row = namedtuple("Row", ["job_type", "job_id", "status", "updated_at"])


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _FakePollSession:
    """Short-lived poll session stand-in."""

    def __init__(self, rows: list | None = None) -> None:
        self._rows = list(rows or [])

    async def __aenter__(self) -> _FakePollSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def execute(self, stmt, params=None) -> _Result:
        return _Result(self._rows)

    async def rollback(self) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session: _FakePollSession) -> None:
        self._session = session
        self.calls = 0

    def __call__(self) -> _FakePollSession:
        self.calls += 1
        return self._session


class _SpyRequestSession(AsyncSession):
    """Request-scoped session stand-in; querying it fails the test."""

    async def execute(self, *args, **kwargs):
        raise AssertionError("the request-scoped session must not be used for polling")


class _AlwaysConnected:
    async def is_disconnected(self) -> bool:
        return False


class _Disconnected:
    async def is_disconnected(self) -> bool:
        return True


def _install(monkeypatch, rows: list | None = None) -> _FakeSessionFactory:
    factory = _FakeSessionFactory(_FakePollSession(rows))
    monkeypatch.setattr(jobs_module, "get_session_factory", lambda: factory)
    return factory


@pytest.mark.asyncio
class TestStreamContract:
    async def test_heartbeat_when_nothing_changed(self, monkeypatch) -> None:
        _install(monkeypatch, rows=[])
        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            async for chunk in response.body_iterator:
                assert chunk == ": ping\n\n"
                break
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

    async def test_job_update_frame_payload(self, monkeypatch) -> None:
        job_id = uuid.uuid4()
        updated = datetime.now(UTC)
        _install(monkeypatch, rows=[Row("analysis", job_id, "running", updated)])
        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        try:
            async for chunk in response.body_iterator:
                break
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert chunk.startswith("event: job_update\n")
        payload = chunk.split("\ndata: ", 1)[1].rstrip("\n")
        assert payload == (
            '{"job_type": "analysis", '
            f'"job_id": "{job_id}", '
            '"status": "running", '
            f'"updated_at": "{updated.isoformat()}"}}'
        )

    async def test_stream_end_after_max_lifetime(self, monkeypatch) -> None:
        """The stream announces its end with the documented reason."""
        _install(monkeypatch, rows=[])
        monkeypatch.setattr(jobs_module, "_MAX_STREAM_SECONDS", 0.01)
        monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0.001)

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(), None
        )
        frames: list[str] = []
        try:
            async for chunk in response.body_iterator:
                frames.append(chunk)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert frames[-1] == 'event: stream_end\ndata: {"reason":"max_lifetime"}\n\n'

    async def test_stream_stops_when_the_client_disconnected(self, monkeypatch) -> None:
        """A disconnected client gets no frames and no database work."""
        factory = _install(monkeypatch, rows=[])
        response = await jobs_module.job_events(
            _Disconnected(), _SpyRequestSession(), None
        )
        frames: list[str] = []
        try:
            async for chunk in response.body_iterator:
                frames.append(chunk)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert frames == []
        assert factory.calls == 0

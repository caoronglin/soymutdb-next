"""Regression tests for the SSE connection budget (P0: pool exhaustion).

``GET /api/v1/jobs/events`` is an anonymous endpoint whose response body is
produced over up to 30 minutes.  FastAPI releases the request-scoped
session only *after* the body has been produced, so polling through that
session pinned one pooled PostgreSQL connection per stream: with
``db_pool_size=3`` / ``db_max_overflow=2`` in production five anonymous
streams exhausted one API worker's whole pool and every other request then
blocked for ``db_pool_timeout``.

The contract asserted here:

- the poll runs on a *short-lived* session (one per cycle) taken from the
  pooled session factory, never on the request-scoped session;
- that session is closed again *before* the stream sleeps, so no connection
  is held across the poll interval;
- one client never holds more than one connection at a time;
- the request-scoped connection (checked out by the optional auth lookup)
  is returned to the pool before the stream starts.

The last test runs against a real PostgreSQL server and checks the pool
itself: while the stream is alive, ``pool.checkedout()`` must be zero.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import namedtuple
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.api.v1 import jobs as jobs_module
from app.core.security import create_access_token
from app.models.auth import User
from app.models.gwas import GwasJob, GwasJobStatus, GwasMethod

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
        self.open_sessions: set[int] = set()
        self.max_open = 0

    def record(self, kind: str, payload: object) -> None:
        self.events.append((kind, payload))
        if kind == "open":
            self.open_sessions.add(id(payload))
            self.max_open = max(self.max_open, len(self.open_sessions))
        elif kind == "close":
            self.open_sessions.discard(id(payload))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


class _FakePollSession:
    """Short-lived poll session stand-in.

    ``__aenter__`` / ``__aexit__`` mirror the real session: the connection
    is checked out on enter and returned to the pool on exit.
    """

    def __init__(
        self,
        recorder: _Recorder,
        rows: list | None = None,
        error: Exception | None = None,
    ) -> None:
        self._recorder = recorder
        self._rows = list(rows or [])
        self._error = error

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
        self._recorder.record("rollback", self)


class _FakeSessionFactory:
    """Session factory stand-in handing out one fake session per cycle.

    The last entry of ``sessions`` is reused for every further call, so a
    single always-failing session models a database that stays down.
    """

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
    """Request-scoped session stand-in that records every use of it.

    It is bound to no engine, and any attempt to query it fails the test.
    """

    def __init__(self, recorder: _Recorder | None = None) -> None:
        super().__init__()
        self._recorder = recorder
        self.queries = 0
        self.rollbacks = 0

    async def execute(self, *args, **kwargs):
        self.queries += 1
        raise AssertionError("the request-scoped session must not be used for polling")

    async def rollback(self) -> None:
        self.rollbacks += 1
        if self._recorder is not None:
            self._recorder.record("request_rollback", self)
        await super().rollback()


class _FakeAsyncio:
    """``asyncio`` stand-in that records the stream's sleep calls.

    Everything except ``sleep`` is delegated to the real module, so the
    event loop clock and ``CancelledError`` keep working.
    """

    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder
        self._real = asyncio

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def sleep(self, delay, *args, **kwargs):
        self._recorder.record("sleep", delay)
        return await self._real.sleep(0)


class _AlwaysConnected:
    """Request stand-in: the client never disconnects."""

    async def is_disconnected(self) -> bool:
        return False


def _install(
    monkeypatch, recorder: _Recorder, sessions: list[_FakePollSession]
) -> _FakeSessionFactory:
    """Patch the jobs module onto the fake session factory and clock."""
    factory = _FakeSessionFactory(recorder, sessions)
    monkeypatch.setattr(jobs_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(jobs_module, "asyncio", _FakeAsyncio(recorder))
    return factory


async def _read_frames(body_iterator, count: int) -> list[str]:
    frames: list[str] = []
    async for chunk in body_iterator:
        frames.append(chunk)
        if len(frames) >= count:
            break
    return frames


# ---------------------------------------------------------------------------
# Unit level: session lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPollSessionLifecycle:
    async def test_poll_uses_a_short_lived_session_not_the_request_scoped_one(
        self, monkeypatch
    ) -> None:
        """The poll must not run on the request-scoped session."""
        recorder = _Recorder()
        rows = [Row("blast", uuid.uuid4(), "running", datetime.now(UTC))]
        _install(monkeypatch, recorder, [_FakePollSession(recorder, rows=rows)])

        request_session = _SpyRequestSession(recorder)
        response = await jobs_module.job_events(_AlwaysConnected(), request_session, None)
        try:
            frames = await _read_frames(response.body_iterator, 1)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert frames[0].startswith("event: job_update\n")
        # The request-scoped session was never queried ...
        assert request_session.queries == 0
        # ... the poll went through a session of the pooled session factory.
        assert recorder.kinds()[:4] == ["request_rollback", "open", "query", "close"]

    async def test_poll_session_is_closed_before_the_stream_sleeps(self, monkeypatch) -> None:
        """The connection is back in the pool before the stream waits."""
        recorder = _Recorder()
        rows = [Row("gwas", uuid.uuid4(), "completed", datetime.now(UTC))]
        _install(monkeypatch, recorder, [_FakePollSession(recorder, rows=rows)])

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(recorder), None
        )
        try:
            await _read_frames(response.body_iterator, 2)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        kinds = recorder.kinds()
        assert kinds[:6] == [
            "request_rollback",
            "open",
            "query",
            "close",
            "sleep",
            "open",
        ]
        # Nothing is checked out while the stream waits for the next cycle.
        assert recorder.open_sessions == set()

    async def test_a_single_client_never_holds_more_than_one_connection(
        self, monkeypatch
    ) -> None:
        """One stream must not accumulate connections over its cycles."""
        recorder = _Recorder()
        _install(monkeypatch, recorder, [_FakePollSession(recorder, rows=[])])

        response = await jobs_module.job_events(
            _AlwaysConnected(), _SpyRequestSession(recorder), None
        )
        try:
            await _read_frames(response.body_iterator, 4)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert recorder.max_open == 1
        assert recorder.open_sessions == set()

    async def test_request_scoped_connection_is_released_before_the_stream_starts(
        self, monkeypatch
    ) -> None:
        """The auth lookup's connection is returned before the first poll."""
        recorder = _Recorder()
        _install(monkeypatch, recorder, [_FakePollSession(recorder, rows=[])])

        request_session = _SpyRequestSession(recorder)
        response = await jobs_module.job_events(_AlwaysConnected(), request_session, None)
        try:
            await _read_frames(response.body_iterator, 1)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert request_session.rollbacks == 1
        kinds = recorder.kinds()
        # The release happens before the stream opens its first poll session.
        assert kinds.index("request_rollback") < kinds.index("open")


# ---------------------------------------------------------------------------
# Real PostgreSQL: the pool itself must stay free while the stream runs
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
class TestPoolIsNotHeldByTheStream:
    @pytest.mark.parametrize("auth_mode", ["header", "query", "anonymous"])
    async def test_auth_identity_survives_request_rollback_without_private_job_leaks(
        self, test_engine, monkeypatch, auth_mode
    ) -> None:
        factory = async_sessionmaker(test_engine, expire_on_commit=False)
        monkeypatch.setattr(jobs_module, "get_session_factory", lambda: factory)
        monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0)
        user_ids = [uuid.uuid4(), uuid.uuid4()]
        job_ids = [uuid.uuid4() for _ in range(3)]
        async with factory() as session:
            session.add_all([
                User(
                    id=user_id, username=f"sse-{user_id}",
                    email=f"{user_id}@sse.test", password_hash="unused",
                )
                for user_id in user_ids
            ])
            await session.flush()
            session.add_all([
                GwasJob(
                    id=job_id, user_id=owner_id,
                    phenotype_file_path="s3://soymutdb/private/phenotype.txt",
                    method=GwasMethod.EMMAX, status=GwasJobStatus.RUNNING,
                    params={}, submitted_at=datetime.now(UTC),
                )
                for job_id, owner_id in zip(job_ids, [*user_ids, None], strict=True)
            ])
            await session.commit()

        try:
            async with factory() as request_session:
                token = create_access_token(str(user_ids[0]))
                request = Request({
                    "type": "http",
                    "headers": [(b"authorization", f"Bearer {token}".encode())]
                    if auth_mode == "header" else [],
                    "query_string": f"access_token={token}".encode()
                    if auth_mode == "query" else b"",
                })
                user = await jobs_module.get_optional_sse_user(request, request_session)
                response = await jobs_module.job_events(
                    _AlwaysConnected(), request_session, user
                )
                if user is not None:
                    # Rollback expires even the PK despite expire_on_commit=False.
                    assert "id" in inspect(user).expired_attributes
                assert test_engine.sync_engine.pool.checkedout() == 0
                try:
                    frames = []
                    for _ in range(3):
                        frames.append(await anext(response.body_iterator))
                        # Check while suspended on each yield, not just after close.
                        assert test_engine.sync_engine.pool.checkedout() == 0
                finally:
                    await response.body_iterator.aclose()
                expected_id = job_ids[2] if auth_mode == "anonymous" else job_ids[0]
                assert all(frame.startswith("event: job_update\n") for frame in frames)
                payloads = [json.loads(frame.split("\ndata: ", 1)[1]) for frame in frames]
                assert {payload["job_id"] for payload in payloads} == {str(expected_id)}
                assert all(set(payload) == {
                    "job_type", "job_id", "status", "updated_at"
                } for payload in payloads)
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["vary"] == "Authorization"
                assert test_engine.sync_engine.pool.checkedout() == 0
                wire = "".join(frames)
                assert token not in wire
                assert "phenotype" not in wire
                assert all(str(user_id) not in wire for user_id in user_ids)
        finally:
            async with factory() as session:
                await session.execute(delete(GwasJob).where(GwasJob.id.in_(job_ids)))
                await session.execute(delete(User).where(User.id.in_(user_ids)))
                await session.commit()

    async def test_no_pooled_connection_is_checked_out_while_the_stream_is_alive(
        self, test_engine, monkeypatch
    ) -> None:
        """The live stream keeps zero pooled connections checked out."""
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(jobs_module, "get_session_factory", lambda: factory)
        monkeypatch.setattr(jobs_module, "_POLL_INTERVAL_SECONDS", 0.01)

        job_id = await _seed_anonymous_gwas_job(factory)
        request_session = factory()
        try:
            # The optional auth lookup leaves a connection checked out.
            await request_session.execute(text("SELECT 1"))
            assert test_engine.sync_engine.pool.checkedout() == 1

            response = await jobs_module.job_events(
                _AlwaysConnected(), request_session, None
            )
            # The request-scoped connection was returned to the pool before
            # the stream started.
            assert test_engine.sync_engine.pool.checkedout() == 0

            try:
                frames = await _read_frames(response.body_iterator, 30)
            finally:
                await response.body_iterator.aclose()  # type: ignore[attr-defined]

            # The stream still sees the job (the poll query really ran).
            assert any(str(job_id) in frame for frame in frames)
            # ... and it holds no connection while it waits for the next cycle.
            assert test_engine.sync_engine.pool.checkedout() == 0
        finally:
            await request_session.close()
            await _delete_gwas_job(factory, job_id)


async def _seed_anonymous_gwas_job(factory) -> uuid.UUID:
    """Insert an anonymous (public) GWAS job and return its id."""
    async with factory() as session:
        job = GwasJob(
            phenotype_file_path="s3://soymutdb/gwas/phenotype.txt",
            method=GwasMethod.EMMAX,
            status=GwasJobStatus.RUNNING,
            params={},
            submitted_at=datetime.now(UTC),
        )
        session.add(job)
        await session.commit()
        return job.id


async def _delete_gwas_job(factory, job_id: uuid.UUID) -> None:
    async with factory() as session:
        await session.execute(delete(GwasJob).where(GwasJob.id == job_id))
        await session.commit()

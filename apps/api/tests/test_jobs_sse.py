"""Job-status SSE endpoint tests (D5) — no docker / no testcontainers.

Covers:
- ``_recent_job_updates``: the three-table UNION query returns the user's
  jobs updated within the trailing window (fake session);
- auth: no token → anonymous (None); invalid token → 401 AuthenticationError;
  valid token accepted via the ``Authorization`` header and via
  ``?access_token=``;
- event stream: pushes a ``job_update`` frame for updated jobs and emits a
  ``: ping`` heartbeat frame when there is nothing to push.

The stream is consumed directly from the ``StreamingResponse`` body iterator
(``httpx``'s ASGITransport cannot handle infinite streams, so no HTTP-level
long-polling here).
"""

from __future__ import annotations

import uuid
from collections import namedtuple
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from app.api.v1 import jobs as jobs_module
from app.core.exceptions import AuthenticationError
from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User

Row = namedtuple("Row", ["job_type", "job_id", "status", "updated_at"])


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in serving a user row and UNION job rows."""

    def __init__(self, user: User | None, job_rows: list | None = None):
        self.user = user
        self.job_rows = list(job_rows or [])
        self.last_stmt = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def rollback(self):
        return None

    async def execute(self, stmt, params=None):
        self.last_stmt = stmt
        sql = str(stmt)
        if "FROM users" in sql:
            return _Result([self.user] if self.user else [])
        if any(
            marker in sql
            for marker in ("UNION", "FROM blast_jobs", "FROM analysis_jobs", "FROM gwas_jobs")
        ):
            return _Result(self.job_rows)
        return _Result([])


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        username="tester",
        email="tester@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=Role(id=1, name=RoleName.RESEARCHER.value),
    )


def _make_request(headers: dict | None = None, query_string: str = "") -> Request:
    """Build a minimal Starlette Request for the endpoint's request param."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/jobs/events",
        "raw_path": b"/api/v1/jobs/events",
        "query_string": query_string.encode("utf-8"),
        "headers": [
            (k.lower().encode("utf-8"), v.encode("utf-8"))
            for k, v in (headers or {}).items()
        ],
        "client": ("testclient", 123),
        "server": ("test", 80),
    }
    return Request(scope)


class _AlwaysConnected:
    """Request stand-in: never reports a disconnected client (we close the
    body iterator manually to end the stream)."""

    async def is_disconnected(self) -> bool:
        return False


async def _read_first_frame(body_iterator) -> str:
    async for chunk in body_iterator:
        return chunk
    raise AssertionError("stream closed before any frame")


# ---------------------------------------------------------------------------
# _recent_job_updates (unit level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRecentJobUpdates:
    async def test_returns_union_rows_for_user(self) -> None:
        from app.api.v1.jobs import _recent_job_updates

        user = _make_user()
        job_id = uuid.uuid4()
        updated = datetime.now(UTC)
        session = FakeDbSession(
            user=user,
            job_rows=[
                Row("blast", job_id, "running", updated),
                Row("gwas", uuid.uuid4(), "completed", updated),
            ],
        )

        events = await _recent_job_updates(session, user.id)  # type: ignore[arg-type]

        assert [e["job_type"] for e in events] == ["blast", "gwas"]
        assert events[0] == {
            "job_type": "blast",
            "job_id": str(job_id),
            "status": "running",
            "updated_at": updated.isoformat(),
        }

    async def test_anonymous_filters_user_id_is_null(self) -> None:
        from app.api.v1.jobs import _recent_job_updates

        session = FakeDbSession(user=None, job_rows=[])
        await _recent_job_updates(session, None)  # type: ignore[arg-type]

        sql = str(session.last_stmt)
        assert "user_id IS NULL" in sql

    async def test_authenticated_filters_by_user_id(self) -> None:
        from app.api.v1.jobs import _recent_job_updates

        user = _make_user()
        session = FakeDbSession(user=user, job_rows=[])
        await _recent_job_updates(session, user.id)  # type: ignore[arg-type]

        # All three UNION branches bind their user filter (PG_UUID columns
        # compile to bound parameters, never literals).
        sql = str(session.last_stmt)
        assert sql.count("user_id = :user_id") == 3


# ---------------------------------------------------------------------------
# Auth resolution (get_optional_sse_user)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOptionalSseUser:
    async def test_no_token_resolves_anonymous(self) -> None:
        from app.api.v1.jobs import get_optional_sse_user

        user = await get_optional_sse_user(
            _make_request(), FakeDbSession(user=None)  # type: ignore[arg-type]
        )
        assert user is None

    async def test_invalid_token_rejected(self) -> None:
        from app.api.v1.jobs import get_optional_sse_user

        with pytest.raises(AuthenticationError):
            await get_optional_sse_user(
                _make_request(headers={"Authorization": "Bearer not-a-jwt"}),
                FakeDbSession(user=None),  # type: ignore[arg-type]
            )

    async def test_bearer_header_accepted(self) -> None:
        from app.api.v1.jobs import get_optional_sse_user

        user = _make_user()
        token = create_access_token(str(user.id))

        resolved = await get_optional_sse_user(
            _make_request(headers={"Authorization": f"Bearer {token}"}),
            FakeDbSession(user=user),  # type: ignore[arg-type]
        )
        assert resolved is not None
        assert resolved.id == user.id

    async def test_access_token_query_param_accepted(self) -> None:
        from app.api.v1.jobs import get_optional_sse_user

        user = _make_user()
        token = create_access_token(str(user.id))

        resolved = await get_optional_sse_user(
            _make_request(query_string=f"access_token={token}"),
            FakeDbSession(user=user),  # type: ignore[arg-type]
        )
        assert resolved is not None
        assert resolved.id == user.id


# ---------------------------------------------------------------------------
# Event stream frames (body iterator, no HTTP long-poll)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestJobEventFrames:
    async def test_anonymous_emits_heartbeat_frame(self, monkeypatch) -> None:
        from app.api.v1.jobs import job_events

        session = FakeDbSession(user=None, job_rows=[])
        monkeypatch.setattr(jobs_module, "get_session_factory", lambda: lambda: session)
        response = await job_events(_AlwaysConnected(), session, None)  # type: ignore[arg-type]
        try:
            chunk = await _read_first_frame(response.body_iterator)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert chunk == ": ping\n\n"

    async def test_authenticated_pushes_job_update_frame(self, monkeypatch) -> None:
        import json

        from app.api.v1.jobs import job_events

        user = _make_user()
        job_id = uuid.uuid4()
        session = FakeDbSession(
            user=user,
            job_rows=[Row("blast", job_id, "running", datetime.now(UTC))],
        )
        monkeypatch.setattr(jobs_module, "get_session_factory", lambda: lambda: session)
        response = await job_events(_AlwaysConnected(), session, user)  # type: ignore[arg-type]
        try:
            chunk = await _read_first_frame(response.body_iterator)
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert chunk.startswith("event: job_update\n")
        data_line = chunk.split("\ndata: ", 1)[1]
        payload = json.loads(data_line)
        assert payload["job_type"] == "blast"
        assert payload["job_id"] == str(job_id)
        assert payload["status"] == "running"
        assert payload["updated_at"] is not None

    async def test_multi_update_frame_per_job(self, monkeypatch) -> None:
        from app.api.v1.jobs import job_events

        user = _make_user()
        updated = datetime.now(UTC)
        session = FakeDbSession(
            user=user,
            job_rows=[
                Row("blast", uuid.uuid4(), "completed", updated),
                Row("gwas", uuid.uuid4(), "failed", updated),
            ],
        )
        monkeypatch.setattr(jobs_module, "get_session_factory", lambda: lambda: session)
        response = await job_events(_AlwaysConnected(), session, user)  # type: ignore[arg-type]
        try:
            frames = []
            async for chunk in response.body_iterator:
                frames.append(chunk)
                if len(frames) == 2:
                    break
        finally:
            await response.body_iterator.aclose()  # type: ignore[attr-defined]

        assert len(frames) == 2
        assert all(f.startswith("event: job_update\n") for f in frames)
        assert "job_type" in frames[0]

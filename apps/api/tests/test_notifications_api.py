"""Notification centre API tests (D2) — no docker, fake DB session.

Covers: authentication gate, pagination caps, unread-first ordering,
unread count, mark-read by ids / all, and the request validation for
the mark-read selector.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.router import api_router
from app.core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User
from app.models.notification import Notification


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class _Result:
    def __init__(self, rows: list, rowcount: int | None = None):
        self._rows = rows
        self.rowcount = rowcount

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one(self):
        return self._rows[0][0] if self._rows and isinstance(self._rows[0], tuple) else (self._rows[0] if self._rows else 0)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _make_user(role: RoleName = RoleName.RESEARCHER) -> User:
    return User(
        id=uuid.uuid4(),
        username="tester",
        email="tester@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=Role(id=1, name=role.value),
    )


def _make_notification(
    user_id: uuid.UUID,
    *,
    type: str = "blast_completed",
    title: str = "BLAST job completed",
    body: str = "BLAST job abc finished.",
    link: str | None = "/blast/jobs/abc",
    read_at: datetime | None = None,
) -> Notification:
    return Notification(
        id=uuid.uuid4(),
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        read_at=read_at,
        created_at=datetime.now(UTC),
    )


class FakeDbSession:
    """AsyncSession stand-in: returns canned notification rows per table."""

    def __init__(
        self,
        notifications: list[Notification] | None = None,
        unread: int | None = None,
        total: int | None = None,
        marked: int = 2,
        user: User | None = None,
    ):
        self.user = user
        self.notifications = notifications or []
        self.unread = unread if unread is not None else len(self.notifications)
        self.total = total if total is not None else len(self.notifications)
        self.marked = marked

    async def execute(self, stmt, params=None):
        text_sql = str(stmt)
        if "FROM users" in text_sql:
            return _Result([self.user] if self.user else [])
        if "UPDATE notifications" in text_sql:
            return _Result([], rowcount=self.marked)
        if "FROM notifications" in text_sql:
            if "count(*)" in text_sql:
                # unread-count query carries read_at IS NULL in the WHERE.
                if "read_at IS NULL" in text_sql or "read_at IS  NULL" in text_sql:
                    return _Result([(self.unread,)])
                return _Result([(self.total,)])
            # Simulate the DB-side ordering: unread first, newest first.
            ordered = sorted(
                self.notifications,
                key=lambda n: (n.read_at is not None, -n.created_at.timestamp()),
            )
            return _Result(ordered)
        return _Result([])

    def add(self, obj) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


def _make_app(db: FakeDbSession) -> FastAPI:
    from app.core.database import get_db

    application = FastAPI(title="SoyMutDB Notifications Test")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.add_exception_handler(ValueError, validation_exception_handler)

    async def override_get_db():
        yield db

    application.dependency_overrides[get_db] = override_get_db
    return application


def _token(user: User) -> str:
    return create_access_token(subject=str(user.id))


async def _client(db: FakeDbSession) -> AsyncClient:
    app = _make_app(db)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


class TestAuth:
    async def test_requires_authentication(self):
        async with await _client(FakeDbSession()) as client:
            r = await client.get("/api/v1/notifications")
            assert r.status_code == 401


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


class TestList:
    async def test_lists_notifications_unread_first(self):
        user = _make_user()
        n_read = _make_notification(user.id, title="old", read_at=datetime.now(UTC))
        n_unread = _make_notification(user.id, title="new")
        # Feed out of order: read row first — the service must reorder.
        db = FakeDbSession(notifications=[n_read, n_unread], unread=1, total=2, user=user)
        async with await _client(db) as client:
            r = await client.get(
                "/api/v1/notifications",
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 200
            payload = r.json()
            assert payload["total"] == 2
            assert payload["unread_count"] == 1
            assert [i["title"] for i in payload["items"]] == ["new", "old"]
            assert payload["items"][0]["read_at"] is None
            assert payload["items"][0]["link"] == "/blast/jobs/abc"

    async def test_limit_is_capped_at_50(self):
        user = _make_user()
        db = FakeDbSession(notifications=[], unread=0, total=0, user=user)
        async with await _client(db) as client:
            r = await client.get(
                "/api/v1/notifications?limit=50",
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 200
            # Over the cap -> 422 by the Query(le=50) bound.
            r2 = await client.get(
                "/api/v1/notifications?limit=51",
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r2.status_code == 422


# ---------------------------------------------------------------------------
# Unread count
# ---------------------------------------------------------------------------


class TestUnreadCount:
    async def test_returns_unread_count(self):
        user = _make_user()
        db = FakeDbSession(notifications=[], unread=7, total=7, user=user)
        async with await _client(db) as client:
            r = await client.get(
                "/api/v1/notifications/unread-count",
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 200
            assert r.json() == {"unread_count": 7}


# ---------------------------------------------------------------------------
# Mark read
# ---------------------------------------------------------------------------


class TestMarkRead:
    async def test_mark_ids_read(self):
        user = _make_user()
        n = _make_notification(user.id)
        db = FakeDbSession(notifications=[n], unread=1, total=1, marked=1, user=user)
        async with await _client(db) as client:
            r = await client.post(
                "/api/v1/notifications/read",
                json={"ids": [str(n.id)]},
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 200
            assert r.json() == {"marked": 1}

    async def test_mark_all_read(self):
        user = _make_user()
        db = FakeDbSession(notifications=[], unread=3, total=3, marked=3, user=user)
        async with await _client(db) as client:
            r = await client.post(
                "/api/v1/notifications/read",
                json={"all": True},
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 200
            assert r.json() == {"marked": 3}

    async def test_empty_selector_is_rejected(self):
        user = _make_user()
        db = FakeDbSession(notifications=[], unread=0, total=0, user=user)
        async with await _client(db) as client:
            r = await client.post(
                "/api/v1/notifications/read",
                json={},
                headers={"Authorization": f"Bearer {_token(user)}"},
            )
            assert r.status_code == 422

    async def test_requires_authentication(self):
        async with await _client(FakeDbSession()) as client:
            r = await client.post("/api/v1/notifications/read", json={"all": True})
            assert r.status_code == 401

"""Notification centre service (D2).

Read/write helpers over :class:`app.models.notification.Notification`.
The worker writes notifications directly through its own narrow store
(``soymutdb_worker.repositories.NotifyStore`` — same table, worker-side
PostgreSQL writes); this service backs the authenticated API endpoints and
provides ``create_notification`` for API-side producers (e.g. seed-request
events) when they need a programmatic insert.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.notification import Notification

#: Hard cap for the list endpoint (unread-first paging).
MAX_LIST_LIMIT = 50


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID | str,
    type: str,
    title: str,
    body: str,
    link: str | None = None,
) -> Notification:
    """Persist a notification row for *user_id* (no dedup — worker-side
    dedup lives in ``NotifyStore`` which keys on user + link)."""
    notification = Notification(
        user_id=uuid.UUID(str(user_id)),
        type=type,
        title=title,
        body=body,
        link=link,
    )
    db.add(notification)
    await db.flush()
    return notification


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
) -> tuple[list[Notification], int, int]:
    """Return ``(items, total, unread_count)`` for *user_id*.

    Ordering is unread-first, then newest first.  *limit* is capped at
    :data:`MAX_LIST_LIMIT`.
    """
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))

    total_q = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id)
    )
    total = (await db.execute(total_q)).scalar_one()

    unread_q = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )
    unread = (await db.execute(unread_q)).scalar_one()

    q = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(
            Notification.read_at.is_(None).desc(),
            Notification.created_at.desc(),
        )
        .limit(limit)
    )
    items = (await db.execute(q)).scalars().all()
    return list(items), int(total), int(unread)


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Number of unread notifications for *user_id*."""
    q = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )
    return int((await db.execute(q)).scalar_one())


async def mark_read(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ids: list[str] | None = None,
    all: bool = False,
) -> int:
    """Mark notifications read; returns the number of updated rows.

    ``all=True`` clears every unread row; otherwise only the listed ids
    (scoped to the caller — other users' rows are never touched).
    """
    now = _utcnow()
    if all:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=now)
        )
    else:
        id_list = [uuid.UUID(str(i)) for i in (ids or [])]
        if not id_list:
            return 0
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(id_list),
            )
            .values(read_at=now)
        )
    result = await db.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)

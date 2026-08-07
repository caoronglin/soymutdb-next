"""Audit-logging helpers: action recording, retention cleanup, and analysis.

All functions are async and accept a :class:`sqlalchemy.ext.asyncio.AsyncSession`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.auth import AuditLog


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    """Create and flush an :class:`AuditLog` entry.

    Returns the created log instance (already added to *db* but **not**
    committed — callers should commit as part of their own transaction).
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(entry)
    await db.flush()
    return entry


async def cleanup_old_audit_logs(db: AsyncSession, days: int = 180) -> int:
    """Delete audit-log entries older than *days*.

    Returns the number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = delete(AuditLog).where(AuditLog.timestamp < cutoff)
    result = await db.execute(stmt)
    await db.commit()
    # SQLAlchemy CursorResult always has rowcount.
    return result.rowcount  # type: ignore[union-attr]


async def compute_online_duration(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Compute online duration (seconds) per user from login/logout audit entries.

    Pairs consecutive login/logout actions for each user, calculating the
    duration between them. Unpaired logins are ignored.

    Returns a list of dicts with keys: user_id, username, total_seconds, login_count.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.action.in_(["login", "logout"]))
        .order_by(AuditLog.user_id, AuditLog.timestamp)
    )
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    # Pair logins with logouts per user.
    sessions_map: dict[uuid.UUID, dict[str, Any]] = {}
    for log in logs:
        if log.user_id is None:
            continue
        uid = log.user_id
        if uid not in sessions_map:
            sessions_map[uid] = {
                "user_id": uid,
                "username": log.user.username if log.user else str(uid),
                "sessions": [],
            }
        if log.action == "login":
            sessions_map[uid]["sessions"].append({"login_at": log.timestamp, "logout_at": None})
        elif log.action == "logout" and sessions_map[uid]["sessions"]:
            for sess in reversed(sessions_map[uid]["sessions"]):
                if sess["logout_at"] is None:
                    sess["logout_at"] = log.timestamp
                    break

    results: list[dict[str, Any]] = []
    for uid, data in sessions_map.items():
        total_seconds = 0.0
        login_count = 0
        for sess in data["sessions"]:
            if sess["logout_at"] is not None and sess["login_at"] is not None:
                delta = sess["logout_at"] - sess["login_at"]
                total_seconds += delta.total_seconds()
                login_count += 1
        results.append(
            {
                "user_id": str(uid),
                "username": data["username"],
                "total_seconds": round(total_seconds, 2),
                "login_count": login_count,
            }
        )

    return results


__all__ = [
    "cleanup_old_audit_logs",
    "compute_online_duration",
    "log_action",
]

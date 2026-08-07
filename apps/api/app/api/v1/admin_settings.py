"""Admin settings endpoints — dynamic key-value configuration via SystemSetting.

Provides generic ``GET /admin/settings/{section}`` and
``PUT /admin/settings/{section}`` endpoints for the admin settings UI
(``apps/admin/src/routes/settings.tsx``).  Each section maps to
``SystemSetting`` rows whose keys start with ``{section}.``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.audit import log_action
from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...models.auth import AuditLog, User
from ...models.system_settings import SystemSetting
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


@router.get("/{section}")
async def get_settings(
    section: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all settings under *section* as a ``{key: value}`` dict.

    Rows are queried from ``SystemSetting`` where the key starts with
    ``{section}.`` (case-insensitive).  The prefix is stripped from the
    returned keys.
    """
    _require_admin(current_user)

    prefix = f"{section}."
    stmt = select(SystemSetting).where(SystemSetting.key.ilike(f"{prefix}%"))
    result = await db.execute(stmt)
    rows = result.scalars().all()

    settings: dict[str, Any] = {}
    for row in rows:
        short_key = row.key[len(prefix) :]
        settings[short_key] = row.value

    return settings


@router.put("/{section}")
async def update_settings(
    section: str,
    payload: dict[str, Any],
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upsert settings under *section*.

    Accepts a flat ``{key: value}`` dict.  Each key is prefixed with
    ``{section}.`` and upserted into ``SystemSetting``.  Admin audit log
    entries are recorded for every change.
    """
    _require_admin(current_user)

    client_ip = request.client.host if request.client else None
    now = datetime.now(timezone.utc)
    prefix = f"{section}."

    # Batch-fetch existing rows for this section to avoid N+1 SELECTs.
    existing_stmt = select(SystemSetting).where(
        SystemSetting.key.in_([f"{prefix}{k}" for k in payload.keys()])
    )
    existing_rows = (await db.execute(existing_stmt)).scalars().all()
    existing_map: dict[str, SystemSetting] = {row.key: row for row in existing_rows}

    for short_key, value in payload.items():
        full_key = f"{prefix}{short_key}"
        # Convert non-string values to JSON strings for storage.
        str_value: str
        if isinstance(value, bool):
            str_value = str(value).lower()
        elif not isinstance(value, str):
            import json  # noqa: PLC0415 — lazy import for non-string values
            str_value = json.dumps(value)
        else:
            str_value = value

        row = existing_map.get(full_key)
        if row:
            row.value = str_value
            row.updated_at = now
            row.updated_by = str(current_user.id)
        else:
            db.add(
                SystemSetting(
                    key=full_key,
                    value=str_value,
                    updated_at=now,
                    updated_by=str(current_user.id),
                )
            )

    # Record a single audit-log entry for the batch update.
    await log_action(
        db,
        user_id=current_user.id,
        action=f"settings_update:{section}",
        resource_type="system_settings",
        new_value=payload,
        ip_address=client_ip,
    )

    await db.commit()

    return await get_settings(section, current_user=current_user, db=db)

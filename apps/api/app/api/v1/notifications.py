"""Notification centre endpoints (D2).

Authenticated endpoints for the in-app notification bell:
- list (unread first, paged), unread count, and mark-read (subset or all).

Any authenticated user may read their own notifications (no RBAC gate —
notifications are personal).  Responses use the unified error envelope
(401 when unauthenticated) via ``get_current_user``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.auth import User
from ...schemas.notifications import (
    MarkReadRequest,
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from ...services import notification_service
from .deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    response: Response,
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    """List the caller's notifications, unread first, newest first.

    ``total`` / ``unread_count`` reflect the full set (not just the page).
    """
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    items, total, unread = await notification_service.list_notifications(
        db, current_user.id, limit=limit
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        unread_count=unread,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    """Return the caller's unread notification count (bell badge)."""
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    count = await notification_service.unread_count(db, current_user.id)
    return UnreadCountResponse(unread_count=count)


@router.post("/read", response_model=MarkReadResponse, status_code=status.HTTP_200_OK)
async def mark_notifications_read(
    request: MarkReadRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MarkReadResponse:
    """Mark a subset (``ids``) or all (``all``) notifications as read.

    ``ids`` are always scoped to the caller; foreign ids are ignored.
    """
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    marked = await notification_service.mark_read(
        db,
        current_user.id,
        ids=request.ids,
        all=request.all,
    )
    return MarkReadResponse(marked=marked)


__all__ = ["router"]

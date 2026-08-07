"""Analytics tracking endpoints: pixel tracker and admin summary."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
)

from ...core.security import RoleName, has_role
from ...services.analytics_service import (
    TRACKING_PIXEL,
    AnalyticsService,
    hash_ip,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(tags=["analytics"])

analytics = AnalyticsService()

SESSION_COOKIE_NAME = "sm_sid"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def _resolve_session_id(request: Request, response: Response) -> str:
    """Return an existing session ID from the cookie or mint a new one.

    Sets the session cookie on *response* when a new ID is generated.
    """
    existing = request.cookies.get(SESSION_COOKIE_NAME)
    if existing:
        try:
            # Validate it looks like a UUID to avoid garbage in the cookie.
            uuid.UUID(existing)
            return existing
        except (ValueError, TypeError):
            pass

    new_sid = uuid.uuid4().hex
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=new_sid,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return new_sid


def _is_dnt(request: Request) -> bool:
    """Return True if the client sent DNT: 1 (Do Not Track)."""
    dnt = request.headers.get("dnt") or request.headers.get("DNT")
    return dnt == "1"


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honouring X-Forwarded-For behind proxies."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


# --------------------------------------------------------------------------- #
# Tracking pixel
# --------------------------------------------------------------------------- #


@router.get("/track.gif", include_in_schema=False)
async def track_pixel(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    event: str = Query(default="pageview", pattern="^(pageview|click|search|widget)$"),
    page: str | None = Query(default=None, max_length=255),
    path: str | None = Query(default=None, max_length=1024),
    widget: str | None = Query(default=None, max_length=255),
    q: str | None = Query(default=None, max_length=512),
    ref: str | None = Query(default=None, max_length=1024),
    source: str | None = Query(default=None, max_length=255),
    duration: int = Query(default=0, ge=0, le=86_400_000),
) -> Response:
    """1×1 transparent GIF pixel – non-blocking event collector.

    The pixel is returned immediately; the ClickHouse insert is scheduled
    as a background task so the HTTP round-trip is never delayed.
    Respects the ``DNT: 1`` header by skipping persistence.
    """
    session_id = _resolve_session_id(request, response)
    user_agent = request.headers.get("user-agent", "")
    ip_raw = _client_ip(request)
    ip_hash = hash_ip(ip_raw) if ip_raw else ""
    referrer = ref or request.headers.get("referer", "")

    # If DNT is set we still return the pixel (so pages render cleanly) but
    # skip writing to ClickHouse.
    if not _is_dnt(request):
        background_tasks.add_task(
            analytics.record_event,
            session_id=session_id,
            event_type=event,
            page=page,
            path=path,
            widget_name=widget,
            search_query=q,
            source=source,
            referrer=referrer,
            user_agent=user_agent[:500],
            ip_hash=ip_hash,
            duration_ms=duration,
        )

    # Cache-busting headers + pixel body.
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return Response(
        content=TRACKING_PIXEL,
        media_type="image/gif",
        status_code=200,
    )


# --------------------------------------------------------------------------- #
# Admin analytics summary
# --------------------------------------------------------------------------- #


@router.get("/admin/analytics/summary")
async def analytics_summary(
    days: int = Query(default=7, ge=1, le=365),
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Aggregate analytics metrics for the admin dashboard.

    Returns event totals, unique sessions, breakdowns by type/page/referrer/
    search term, and a daily time series.  Administrator-only.
    """
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        from ...core.exceptions import AuthorizationError
        raise AuthorizationError("Administrator role required")

    return await analytics.get_summary(days=days)

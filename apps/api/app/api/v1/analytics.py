"""Analytics tracking endpoints: pixel tracker and admin summary.

First-party privacy contract
---------------------------
This is the ingress side of the contract documented in
:mod:`app.services.analytics_privacy`. The endpoints are not behind
authentication and never treat the request's site, host, client IP or user
agent as a permission or as an identity — they only ever store what the pure
normaliser returns:

* ``page`` / ``path`` become a canonical route template or ``/other``; a raw
  identifier, query string or full URL is never forwarded.
* ``referrer`` / ``source`` become one of four finite categories describing a
  *client-supplied* header hint, not a verified traffic source.
* ``q`` (search text), ``widget`` (free-text label), the ``User-Agent`` header
  and any IP-derived value are accepted for client compatibility and then
  dropped: they are never passed to the store.
* Only the opaque ``sm_sid`` cookie counts sessions. No new tracking identity
  is minted and no per-site column exists.

``DNT: 1`` short-circuits both verbs *before* a session id is resolved and
before any cookie is set: the client gets a no-store private pixel, no cookie
is created or refreshed, and no background write is queued. A cookie the
browser already holds is left untouched — it is neither deleted nor rewritten.

Input handling
--------------
Both verbs validate the pixel protocol by hand instead of through FastAPI
parameter/pydantic validation. A framework-generated 422 would echo the
rejected value back to the caller, which is exactly the raw data this contract
must not disclose. Invalid or malformed input therefore returns the same
transparent pixel with nothing queued and nothing stored.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any, TypedDict

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
)
from pydantic import ValidationError

from ...core.config import get_settings
from ...core.security import RoleName, has_role
from ...schemas.analytics import AnalyticsSummary, WebVitalEvent
from ...services.analytics_privacy import classify_referrer, normalize_analytics_page
from ...services.analytics_service import (
    MAX_DURATION_MS,
    MAX_WEB_VITAL_VALUE,
    TRACKING_PIXEL,
    VALID_EVENT_TYPES,
    VALID_WEB_VITAL_NAMES,
    VALID_WEB_VITAL_RATINGS,
    AnalyticsService,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(tags=["analytics"])

analytics = AnalyticsService()

SESSION_COOKIE_NAME = "sm_sid"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

#: Event types the GET pixel accepts. ``performance`` is a finite member of the
#: protocol, not an open string.
_GET_EVENT_TYPES: frozenset[str] = frozenset(VALID_EVENT_TYPES | {"performance"})

#: Longest raw query parameter/beacon field the ingress will even look at. The
#: normaliser bounds page input on its own; this keeps a pathological request
#: from reaching the JSON parse or the pure functions at all.
MAX_RAW_PARAM_LENGTH = 2048

#: Largest beacon body read before the request is treated as malformed.
MAX_BEACON_BODY_BYTES = 8192

#: A plain signed decimal integer, ASCII digits only, bounded length.
_INTEGER = re.compile(r"\A[+-]?[0-9]{1,18}\Z")


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
    """Return a forwarded IP only when the immediate peer is trusted.

    Direct callers control ``X-Forwarded-For``; accepting it unconditionally
    lets them spoof the value that privacy-hashed for telemetry.

    The analytics write path no longer derives anything from the request IP;
    this helper is retained because it defines the proxy boundary for any
    future caller and is covered by its own regression tests.
    """
    peer_ip = request.client.host if request.client and request.client.host else ""
    trusted_proxies = set(get_settings().analytics_trusted_proxy_ips)
    xff = request.headers.get("x-forwarded-for")
    if xff and peer_ip in trusted_proxies:
        return xff.split(",")[0].strip()
    return peer_ip


# --------------------------------------------------------------------------- #
# Manual pixel-protocol validation
# --------------------------------------------------------------------------- #


def _query_param(request: Request, name: str) -> str | None:
    """Return the first raw value of query parameter *name*, or ``None``.

    Reading the raw query string instead of declaring a validated FastAPI
    parameter is deliberate: a rejected parameter would otherwise come back as
    a 422 whose body repeats the rejected value.
    """
    value = request.query_params.get(name)
    if value is None:
        return None
    if len(value) > MAX_RAW_PARAM_LENGTH:
        # Too long to be a value we ever normalise; treated as malformed.
        raise ValueError(name)
    return value


def _parse_int(value: str) -> int | None:
    """Return *value* as an int, or ``None`` when it is not a plain integer.

    Only ASCII digits are accepted and the length is capped, so an exotic
    numeral or a multi-thousand-digit string cannot reach :func:`int`.
    """
    text = value.strip()
    if not _INTEGER.fullmatch(text):
        return None
    return int(text)


def _parse_float(value: str) -> float | None:
    """Return *value* as a finite float, or ``None``.

    ``nan``/``inf`` parse successfully as floats but are not measurements, so
    they are rejected explicitly rather than silently stored.
    """
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


class _EventArgs(TypedDict):
    """Shape of one queued page-view event (see ``record_event``)."""

    event_type: str
    page: str | None
    path: str
    widget_name: str
    search_query: str
    source: str
    referrer: str
    user_agent: str
    ip_hash: str
    duration_ms: int


class _VitalArgs(TypedDict):
    """Shape of one queued Web Vital (see ``record_web_vital``)."""

    name: str
    value: float
    rating: str
    path: str


def _bounded_param(
    request: Request,
    name: str,
    allowed: frozenset[str] | None = None,
) -> str | None:
    """Return a single-valued free-text parameter, or ``None`` when unusable.

    A repeated parameter is rejected outright: which of the values "the" referrer
    is would otherwise be an accident of ordering.
    """
    value = _query_param(request, name)
    if value is None:
        return None
    if len(request.query_params.getlist(name)) > 1:
        raise ValueError(name)
    if allowed is not None and value not in allowed:
        raise ValueError(name)
    return value


# --------------------------------------------------------------------------- #
# Tracking pixel
# --------------------------------------------------------------------------- #


def _pixel_response() -> Response:
    """Return the 1x1 transparent GIF with a private, no-store policy."""
    response = Response(content=TRACKING_PIXEL, media_type="image/gif")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def _tracking_response(request: Request) -> tuple[Response, str]:
    """Create a no-store pixel response and bind its session cookie."""
    response = _pixel_response()
    session_id = _resolve_session_id(request, response)
    return response, session_id


async def _read_beacon_payload(request: Request) -> dict[str, Any] | None:
    """Return the beacon body as a dict, or ``None`` when it is unusable.

    A body that is too large, not JSON, or not a JSON object is treated as
    malformed. Nothing from the body is logged or echoed.
    """
    try:
        raw = await request.body()
    except Exception:
        return None
    if not raw or len(raw) > MAX_BEACON_BODY_BYTES:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _beacon_value_is_usable(value: object) -> bool:
    """Return True when a beacon ``value`` is a real measurement.

    Checked before :func:`WebVitalEvent.model_validate` because pydantic's lax
    mode coerces a JSON boolean into ``1.0``: a beacon saying ``"value": true``
    would otherwise be stored as a one-millisecond measurement. ``NaN`` and
    ``Infinity`` parse as JSON numbers too, and are rejected here rather than
    relying on a field constraint to happen to exclude them. This mirrors the
    GET verb's ``_parse_float`` and the store boundary's own guard.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _web_vital_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the existing hidden beacon protocol, or return ``None``.

    ``WebVitalEvent`` still defines the protocol (name/value/rating ranges and
    the optional ``url``); it is validated here by hand so a rejected payload
    produces a silent drop instead of a 422 that echoes the offending value.
    ``id`` and ``ts`` are accepted and ignored.
    """
    if not _beacon_value_is_usable(payload.get("value")):
        return None
    try:
        event = WebVitalEvent.model_validate(payload)
    except ValidationError:
        return None
    return {"name": event.name, "value": event.value, "rating": event.rating, "url": event.url}


@router.get("/track.gif", include_in_schema=False)
async def track_pixel(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """1×1 transparent GIF pixel – non-blocking event collector.

    The pixel is returned immediately; the analytics write is scheduled as a
    background task so the HTTP round-trip is never delayed. Parameters keep
    their existing names and meanings for current callers, but only the values
    the normaliser produces are stored.
    """
    # DNT is honoured before the session id is resolved: no cookie is read,
    # written or refreshed on this path, and nothing is queued.
    if _is_dnt(request):
        return _pixel_response()

    try:
        event = _bounded_param(request, "event")
        event_type = "pageview" if event is None else event
        if event_type not in _GET_EVENT_TYPES:
            raise ValueError("event")

        raw_duration = _bounded_param(request, "duration")
        duration = 0 if raw_duration is None else _parse_int(raw_duration)
        if duration is None or not 0 <= duration <= MAX_DURATION_MS:
            raise ValueError("duration")

        page_raw = _bounded_param(request, "page")
        path_raw = _bounded_param(request, "path")
        # Free text: accepted for compatibility, then dropped without storage.
        _bounded_param(request, "q")
        _bounded_param(request, "widget")
        ref_raw = _bounded_param(request, "ref")
        source_raw = _bounded_param(request, "source")

        # One of the two payloads is built per branch and queued after the
        # cookie is minted. Declared up front so every surviving path binds
        # exactly one of them.
        event_args: _EventArgs | None = None
        vital: _VitalArgs | None = None
        if event_type == "performance":
            name = _bounded_param(request, "name", VALID_WEB_VITAL_NAMES)
            rating = _bounded_param(request, "rating", VALID_WEB_VITAL_RATINGS)
            raw_value = _bounded_param(request, "value")
            value = None if raw_value is None else _parse_float(raw_value)
            if name is None or rating is None or value is None:
                raise ValueError("web_vital")
            if not 0 <= value <= MAX_WEB_VITAL_VALUE:
                raise ValueError("web_vital_value")
            vital = {
                "name": name,
                "value": value,
                "rating": rating,
                "path": normalize_analytics_page(path_raw or request.url.path),
            }
        else:
            referrer_hint = ref_raw or request.headers.get("referer", "")
            if len(referrer_hint) > MAX_RAW_PARAM_LENGTH:
                raise ValueError("referrer")
            event_args = {
                "event_type": event_type,
                "page": normalize_analytics_page(page_raw),
                "path": normalize_analytics_page(path_raw or request.url.path),
                # Search text and widget labels are never stored.
                "widget_name": "",
                "search_query": "",
                "source": classify_referrer(source_raw) if source_raw else "",
                "referrer": classify_referrer(referrer_hint),
                # No user-agent string and no IP-derived identifier is stored.
                "user_agent": "",
                "ip_hash": "",
                "duration_ms": duration,
            }
    except ValueError:
        # Malformed input: same pixel, nothing queued, nothing stored, and the
        # rejected value is never reflected back to the caller.
        return _pixel_response()

    # The cookie is minted only when a write is actually queued.
    response, session_id = _tracking_response(request)
    if vital is not None:
        background_tasks.add_task(
            analytics.record_web_vital,
            session_id=session_id,
            # No user-agent string and no IP-derived identifier is stored.
            user_agent="",
            ip_hash="",
            **vital,
        )
    elif event_args is not None:
        background_tasks.add_task(
            analytics.record_event, session_id=session_id, **event_args
        )
    # Both payloads cannot be unset: the branch above built exactly one, and a
    # malformed input returned before reaching here.
    return response


@router.post("/track.gif", include_in_schema=False)
async def track_pixel_beacon(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Accept the JSON payload emitted by navigator.sendBeacon.

    Same guards as the GET pixel: ``DNT: 1`` returns before any cookie work,
    and a malformed body is dropped rather than echoed.
    """
    if _is_dnt(request):
        return _pixel_response()

    payload = await _read_beacon_payload(request)
    vital = None if payload is None else _web_vital_from_payload(payload)
    if vital is None:
        return _pixel_response()

    response, session_id = _tracking_response(request)
    background_tasks.add_task(
        analytics.record_web_vital,
        session_id=session_id,
        name=vital["name"],
        value=vital["value"],
        rating=vital["rating"],
        # A beacon may carry the full page URL; only its template is stored.
        path=normalize_analytics_page(vital["url"] or request.url.path),
        user_agent="",
        ip_hash="",
    )
    return response


# --------------------------------------------------------------------------- #
# Admin analytics summary
# --------------------------------------------------------------------------- #


@router.get("/admin/analytics/summary")
async def analytics_summary(
    response: Response,
    days: int = Query(default=7, ge=1, le=365),
    current_user=Depends(get_current_user),
) -> AnalyticsSummary:
    """Aggregate visit metrics for the administrator dashboard.

    Returns event totals, unique sessions, breakdowns by event type, by
    canonical route template and by referrer category, and a daily count
    series.

    Every label is a fixed constant of this API and never caller data: a route
    template such as ``/mutants/:publicId`` or ``/other``, one of the four
    referrer categories (``direct``, ``search``, ``social``, ``other``), a
    finite event type, or a ``YYYY-MM-DD`` day. Free-text search terms are
    neither queried nor returned, so ``top_searches`` is always empty and
    ``top_searches_available`` is always ``false``.

    Each section carries an ``*_available`` flag, which is ``false`` when the
    analytics store could not be read: an unavailable store is therefore never
    displayed as a window with no traffic. A referrer category describes a
    client-supplied header hint, not a verified traffic source, and unique
    sessions count opaque cookie sessions, not people.

    Administrator-only, and the response is ``private, no-store``.
    """
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        from ...core.exceptions import AuthorizationError
        raise AuthorizationError("Administrator role required")

    # Per-user aggregate: never a shared cache, never a stale read.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization, Cookie"

    return await analytics.get_summary(days=days)

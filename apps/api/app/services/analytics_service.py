"""Analytics tracking service – writes behavioural events to native PostgreSQL.

Events (pageview, click, search, widget) are inserted asynchronously so the
HTTP response (a 1x1 transparent GIF) is never blocked by database I/O.

First-party privacy contract
---------------------------
Both writers are the store boundary and normalise every free-form value with
:mod:`app.services.analytics_privacy` before an insert is issued, so the same
canonicalisation applies whether a row is written by the HTTP ingress or by any
other caller. The normalisers are idempotent, so normalising at both boundaries
is harmless and either one alone would still be safe.

What is stored
--------------
* ``page`` / ``path`` – a canonical route template or ``/other``, never a raw
  identifier, query string, host or full URL.
* ``referrer`` / ``source`` – one of the finite referrer categories. The
  category describes a *client-supplied* header hint and is not evidence of a
  true traffic source.
* ``widget_name`` / ``search_query`` / ``user_agent`` / ``ip_hash`` – dropped.
  Free-text widget labels, search terms, browser strings and anything derived
  from an address are not stored, because migration ``0047`` gives the
  analytics tables no column to store them in. The parameters remain in the
  method signature for call compatibility and are discarded before the insert
  is built, so a future caller passing one changes nothing. Session counting
  keeps using the opaque cookie the browser already holds; no new tracking
  identity is minted here.

The read path (:meth:`AnalyticsService.get_summary`) applies the same
normalisation to rows already in the table, so historical raw labels collapse
into templates/categories and their counts are merged. Those breakdown queries
are grouped by the **stored** label and are never truncated before
normalisation, because a ``LIMIT`` applied there would silently drop groups
that were about to be merged into one template; the cap is applied to the
merged result instead. ``top_searches`` is no longer queried or returned, free-
text search history is never exposed, and every section carries an
``*_available`` flag so "the store could not be read" can be told apart from
"zero visits".

Storage
-------
Both tables are plain PostgreSQL rows in the authoritative store, written
through :class:`~app.services.analytics_repository.AnalyticsRepository` with
bound parameters on a session from :func:`get_session_factory`. There is no
ClickHouse client, no dialect translation and no second analytical store to
keep in step. Aggregates are ordinary SQL — ``COUNT(*)`` and
``COUNT(DISTINCT session_id)`` — and the reporting window is a bound UTC
cutoff computed in Python, never an interval interpolated into statement text.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from structlog import get_logger

from ..core.config import get_settings
from ..core.database import get_session_factory
from ..schemas.analytics import AnalyticsSummary
from .analytics_privacy import (
    normalize_analytics_page,
    referrer_column_value,
)
from .analytics_repository import (
    EVENT_COLUMNS,
    EVENTS_TABLE,
    WEB_VITAL_COLUMNS,
    WEB_VITALS_TABLE,
    AnalyticsRepository,
)

logger = get_logger(__name__)

__all__ = [
    "EVENTS_TABLE",
    "EVENT_COLUMNS",
    "MAX_DURATION_MS",
    "MAX_WEB_VITAL_VALUE",
    "TRACKING_PIXEL",
    "VALID_EVENT_TYPES",
    "VALID_WEB_VITAL_NAMES",
    "VALID_WEB_VITAL_RATINGS",
    "WEB_VITALS_TABLE",
    "WEB_VITAL_COLUMNS",
    "AnalyticsService",
    "hash_ip",
]

VALID_EVENT_TYPES = {"pageview", "click", "search", "widget"}
#: Immutable allow-lists: they are compared against caller input and must not
#: be mutable at runtime, so a frozenset is both the correct type and what the
#: request-bound parser expects.
VALID_WEB_VITAL_NAMES = frozenset({"LCP", "FID", "INP", "CLS", "TTFB", "FCP"})
VALID_WEB_VITAL_RATINGS = frozenset({"good", "needs-improvement", "poor"})

#: Upper bound for both ``duration_ms`` and a Web Vital ``value``. A metric
#: outside it is a broken client, not a measurement, and is never stored.
MAX_DURATION_MS = 86_400_000
MAX_WEB_VITAL_VALUE = 86_400_000

#: Event types a summary may report. ``performance`` events are written to the
#: Web Vitals table, so a legacy copy in the events table collapses into the
#: finite ``other`` bucket rather than appearing as an invented type.
SUMMARY_EVENT_TYPES: frozenset[str] = frozenset(VALID_EVENT_TYPES | {"performance"})
SUMMARY_EVENT_TYPE_OTHER = "other"

#: Daily time-series labels are kept as written; only this exact shape is
#: reported, so a time series can never be merged into a biological namespace.
_DAY_LABEL = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

#: Upper bound on a summary breakdown list after labels are merged.
SUMMARY_LIMIT = 20

#: Published bounds of the summary window. The API validates the same range;
#: the service repeats it because it is reachable directly, and a window is
#: turned into a cutoff here rather than into SQL text.
MIN_SUMMARY_DAYS = 1
MAX_SUMMARY_DAYS = 365

# 1×1 transparent GIF (43 bytes) – cached once at module load.
TRACKING_PIXEL: bytes = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def hash_ip(ip: str, salt: str | None = None) -> str:
    """Return a salted SHA-256 hex digest of *ip* (never store raw IPs).

    Kept for callers that need a non-reversible correlation key. The analytics
    write path no longer derives or stores anything from the request IP.
    """
    effective_salt = salt if salt is not None else get_settings().analytics_ip_salt
    return hashlib.sha256(f"{effective_salt}:{ip}".encode()).hexdigest()


def _opaque_session_id(value: object) -> uuid.UUID | None:
    """Return *value* parsed as the opaque cookie id this API mints.

    The ingress mints ``uuid4().hex`` and accepts any cookie that parses as a
    UUID, so both the hyphenated and hex forms are legitimate. Rejecting
    anything else here keeps an arbitrary caller-supplied string out of the
    ``session_id`` column without logging the rejected value. The parsed UUID
    is also what gets bound: the column is a ``UUID``, so handing the driver a
    value PostgreSQL would have to re-parse is one more way for a rejected
    string to reach storage.
    """
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return None


def _bounded_window_days(days: object) -> int:
    """Return the summary window length clamped to the published bounds."""
    try:
        value = int(days)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        value = MIN_SUMMARY_DAYS
    return max(MIN_SUMMARY_DAYS, min(value, MAX_SUMMARY_DAYS))


def _summary_event_label(value: object) -> str:
    """Reduce a stored event type to a finite label.

    A legacy row with an event type this build does not recognise collapses into
    one ``other`` bucket instead of being echoed into the JSON payload.
    """
    text = str(value)
    return text if text in SUMMARY_EVENT_TYPES else SUMMARY_EVENT_TYPE_OTHER


def _merged_breakdown(
    label_of: Callable[[object], str],
    rows: Any,
    *,
    limit: int | None = SUMMARY_LIMIT,
) -> list[dict[str, Any]]:
    """Map stored labels through *label_of*, then merge equal labels.

    Historical rows hold raw values (``/mutants/42``, a full referrer URL), and
    several of them can normalise to the same template. Merging before the cap
    is what makes the reported count for ``/mutants/:publicId`` the sum over
    every raw URL that maps to it — which is only true because the caller
    receives *all* stored-label groups: the caller must not pre-truncate
    ``rows``, or this function silently reports a lower bound.
    """
    merged: dict[str, int] = {}
    for row in rows:
        label = label_of(row[0])
        if not label:
            # An empty stored value carries no category and is not reported.
            continue
        merged[label] = merged.get(label, 0) + int(row[1])
    items = [
        {"label": label, "count": count}
        for label, count in merged.items()
    ]
    items.sort(key=lambda item: (-item["count"], item["label"]))
    return items[:limit] if limit is not None else items


def _day_series(rows: Any) -> list[dict[str, Any]]:
    """Return the daily counts with their dates preserved exactly.

    The time series is never merged: a date bucket stays one bucket, and a row
    whose label is not a plain ``YYYY-MM-DD`` date is dropped rather than being
    folded into another series.
    """
    items: list[dict[str, Any]] = []
    for row in rows:
        label = str(row[0])
        if not _DAY_LABEL.match(label):
            continue
        items.append({"label": label, "count": int(row[1])})
    items.sort(key=lambda item: item["label"])
    return items


def _availability_keys(availability: dict[str, bool]) -> dict[str, bool]:
    """Flatten section availability into top-level ``*_available`` flags."""
    return {f"{key}_available": value for key, value in availability.items()}


class AnalyticsService:
    """Async service for recording and querying analytics events.

    *session_factory* exists so a test can hand the service a session it
    controls; production callers construct ``AnalyticsService()`` and every
    statement runs on a session from :func:`get_session_factory`, the same
    PostgreSQL engine the rest of the API uses.
    """

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory

    def _new_session(self) -> Any:
        """Return a session from the injected factory, else the global one."""
        factory = self._session_factory or get_session_factory()
        return factory()

    # ------------------------------------------------------------------ #
    # Write path (fire-and-forget friendly)
    # ------------------------------------------------------------------ #

    async def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        page: str | None = None,
        path: str | None = None,
        widget_name: str | None = None,
        search_query: str | None = None,
        source: str | None = None,
        referrer: str | None = None,
        user_agent: str | None = None,
        ip_hash: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        """Insert a single sanitised event row into PostgreSQL.

        This method is ``await``-able so the caller can decide whether to
        block, fire-and-forget via ``asyncio.create_task``, or run via
        FastAPI ``BackgroundTasks``.

        Every caller-supplied string is normalised here, at the store boundary:
        pages become route templates, referrer/source become finite categories.
        Passing *widget_name*, *search_query*, *user_agent* or *ip_hash* is
        accepted for call compatibility and dropped: the native table has no
        column for any of them, so the values are never read, bound or stored.
        """
        if event_type not in VALID_EVENT_TYPES:
            logger.warning("invalid_event_type")
            return
        opaque_session = _opaque_session_id(session_id)
        if opaque_session is None:
            logger.warning("invalid_session_id")
            return

        # Duration is a client-controlled number: keep it inside the accepted
        # range instead of writing a value the summary would report as a real
        # dwell time.
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            logger.warning("invalid_duration_ms")
            duration_ms = 0
        elif not 0 <= duration_ms <= MAX_DURATION_MS:
            logger.warning("duration_ms_out_of_range", duration_ms=duration_ms)
            duration_ms = min(max(duration_ms, 0), MAX_DURATION_MS)

        page_template = normalize_analytics_page(page)
        path_template = normalize_analytics_page(path)
        # One owner for the classification policy: the pure normaliser. The
        # column rule ("no hint at all" stays empty) lives with it too.
        referrer_category = referrer_column_value(referrer)
        source_category = referrer_column_value(source)

        now = datetime.now(UTC)
        start = time.perf_counter()
        try:
            async with self._new_session() as session:
                await AnalyticsRepository(session).insert_event(
                    {
                        "timestamp": now,
                        "session_id": opaque_session,
                        "event_type": event_type,
                        "page": page_template,
                        "path": path_template,
                        "source": source_category,
                        "referrer": referrer_category,
                        "duration_ms": duration_ms,
                    }
                )
            logger.debug(
                "analytics_event_recorded",
                event_type=event_type,
                page=page_template,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except Exception:
            # Never let analytics errors surface to the request lifecycle.
            logger.exception(
                "analytics_insert_failed",
                event_type=event_type,
                page=page_template,
            )

    async def record_web_vital(
        self,
        *,
        session_id: str,
        name: str,
        value: float,
        rating: str,
        path: str = "",
        user_agent: str = "",
        ip_hash: str = "",
    ) -> None:
        """Store one validated, sanitised Web Vital in its native PostgreSQL table.

        ``path`` is reduced to a route template, and *user_agent* / *ip_hash*
        are dropped: the table has no column for a browser string or an
        address, so a vital row cannot disclose one even by accident. A metric
        whose value is not a finite number inside the accepted range is dropped
        rather than stored.
        """
        if name not in VALID_WEB_VITAL_NAMES or rating not in VALID_WEB_VITAL_RATINGS:
            # The rejected value is deliberately not logged: an unknown metric
            # name is caller-supplied free text, exactly what this module never
            # records. The event key alone is enough to spot a broken client.
            logger.warning("invalid_web_vital")
            return
        opaque_session = _opaque_session_id(session_id)
        if opaque_session is None:
            logger.warning("invalid_session_id")
            return
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= MAX_WEB_VITAL_VALUE
        ):
            logger.warning("invalid_web_vital_value")
            return

        path_template = normalize_analytics_page(path)
        try:
            async with self._new_session() as session:
                await AnalyticsRepository(session).insert_web_vital(
                    {
                        "timestamp": datetime.now(UTC),
                        "session_id": opaque_session,
                        "metric_name": name,
                        "value": float(value),
                        "rating": rating,
                        "path": path_template,
                    }
                )
        except Exception:
            # RUM is best-effort and must never affect page delivery.
            logger.exception(
                "web_vital_insert_failed",
                metric_name=name,
            )

    # ------------------------------------------------------------------ #
    # Read path (admin dashboards)
    # ------------------------------------------------------------------ #

    async def get_summary(
        self,
        days: int = 7,
    ) -> AnalyticsSummary:
        """Return aggregate analytics summary over the last *days* days.

        Every label that comes back from storage is normalised a second time
        before it is returned, so rows written before the write path was
        hardened still cannot disclose a raw internal identifier, a full URL or
        a query string: historical ``/mutants/42`` and ``/mutants/MUT-1`` are
        both reported as ``/mutants/:publicId`` and their counts merged.

        ``top_searches`` is never queried or populated, so free-text search
        history is not exposed; the key is still present (always empty) so an
        older typed client keeps its shape. Every section carries an
        ``*_available`` boolean, so a store that could not be read is
        distinguishable from a window with genuinely no traffic — a failure
        never reports a confident zero.

        Breakdown queries are grouped by the **stored** label and are never
        truncated before normalisation: a raw-label ``LIMIT`` would drop whole
        groups of rows that were about to collapse into the same template, and
        the reported count for e.g. ``/mutants/:publicId`` would silently be a
        lower bound. The cost of that choice is one output row per distinct
        stored label in the window (unbounded for historical rows written before
        the templates existed, bounded to the template set afterwards), which is
        merged and then cut to :data:`SUMMARY_LIMIT` in Python.
        """
        result: dict[str, Any] = {
            "total_events": 0,
            "unique_sessions": 0,
            "events_by_type": [],
            "top_pages": [],
            "top_referrers": [],
            # Free-text search terms are never queried or returned.
            "top_searches": [],
            "events_by_day": [],
        }
        availability: dict[str, bool] = {
            key: False for key in result
        }
        # ``top_searches`` stays unavailable whatever the store reports.
        availability["top_searches"] = False

        # A bound UTC cutoff rather than an interval in statement text: the day
        # count is clamped here, and the same window is applied by every query.
        cutoff = datetime.now(UTC) - timedelta(days=_bounded_window_days(days))
        try:
            async with self._new_session() as session:
                await session.execute(text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                ))
                repository = AnalyticsRepository(session)
                counts = await repository.counts(cutoff=cutoff)
                breakdowns = await repository.breakdowns(cutoff=cutoff)
        except Exception:
            logger.exception("analytics_summary_failed")
            # Keep the same keys, but mark everything as unavailable: zero is a
            # fact, "could not ask" is not.
            for key in result:
                result[key] = [] if isinstance(result[key], list) else 0
            for key in availability:
                availability[key] = False
            return AnalyticsSummary.model_validate(
                {**result, **_availability_keys(availability)}
            )

        result["total_events"] = counts.total_events
        result["unique_sessions"] = counts.unique_sessions
        result["events_by_type"] = _merged_breakdown(
            _summary_event_label, breakdowns.events_by_type, limit=None
        )
        result["top_pages"] = _merged_breakdown(
            normalize_analytics_page, breakdowns.top_pages
        )
        result["top_referrers"] = _merged_breakdown(
            referrer_column_value, breakdowns.top_referrers
        )
        result["events_by_day"] = _day_series(breakdowns.events_by_day)
        for key in result:
            if key == "top_searches":
                continue
            availability[key] = True

        return AnalyticsSummary.model_validate(
            {**result, **_availability_keys(availability)}
        )

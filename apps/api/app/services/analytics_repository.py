"""Native PostgreSQL statements for anonymous analytics telemetry.

The service owns the privacy contract; this module owns the SQL. Nothing here
normalises, labels or filters a value, and nothing here names a column that
migration ``0047`` does not create. An analytics row holds a route template, a
referrer category, an opaque session id, a bounded duration and a timestamp —
there is no widget, search-term, browser-string or address column to write to,
so no caller can reintroduce one by passing one.

Every value reaches the database as a bound parameter. The reporting window is
a UTC cutoff the caller computes and passes as ``:cutoff``: a day count is
never interpolated into statement text, and a day bucket is derived in UTC
rather than in whatever time zone the database session happens to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

EVENTS_TABLE = "analytics_events"
WEB_VITALS_TABLE = "web_vitals"

#: Columns an event insert binds, in statement order. The service builds its
#: parameter mapping in this order, so the pair is the write contract: a new
#: key on either side is a visible change rather than a silent extra column.
EVENT_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "session_id",
    "event_type",
    "page",
    "path",
    "source",
    "referrer",
    "duration_ms",
)
WEB_VITAL_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "session_id",
    "metric_name",
    "value",
    "rating",
    "path",
)

_INSERT_EVENT = text(
    f'INSERT INTO {EVENTS_TABLE} ("timestamp", session_id, event_type, page, '
    "path, source, referrer, duration_ms) VALUES "
    "(:timestamp, :session_id, :event_type, :page, :path, :source, :referrer, "
    ":duration_ms)"
)
_INSERT_WEB_VITAL = text(
    f'INSERT INTO {WEB_VITALS_TABLE} ("timestamp", session_id, metric_name, '
    "value, rating, path) VALUES "
    "(:timestamp, :session_id, :metric_name, :value, :rating, :path)"
)

_TOTAL_EVENTS = text(f'SELECT COUNT(*) FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff')
_UNIQUE_SESSIONS = text(
    f'SELECT COUNT(DISTINCT session_id) FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff'
)
_EVENTS_BY_TYPE = text(
    f'SELECT event_type, COUNT(*) AS cnt FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff '
    "GROUP BY event_type ORDER BY cnt DESC"
)
# No LIMIT on a breakdown: a stored-label limit would drop whole groups of rows
# that are about to be normalised into one template, making the reported count
# for that template a lower bound. The cap is applied after merging.
_TOP_PAGES = text(
    f'SELECT page, COUNT(*) AS cnt FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff '
    "AND event_type = 'pageview' AND page <> '' GROUP BY page ORDER BY cnt DESC"
)
_TOP_REFERRERS = text(
    f'SELECT referrer, COUNT(*) AS cnt FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff '
    "AND referrer <> '' GROUP BY referrer ORDER BY cnt DESC"
)
# A day bucket is a UTC calendar day, formatted as the ``YYYY-MM-DD`` label the
# summary contract publishes. Doing it in SQL keeps the bucket and its count in
# one row; the read path still re-checks the label shape before reporting it.
_EVENTS_BY_DAY = text(
    f'SELECT to_char(("timestamp" AT TIME ZONE \'UTC\')::date, \'YYYY-MM-DD\') AS day, '
    f'COUNT(*) AS cnt FROM {EVENTS_TABLE} WHERE "timestamp" >= :cutoff '
    'GROUP BY ("timestamp" AT TIME ZONE \'UTC\')::date ORDER BY day ASC'
)


@dataclass(frozen=True)
class SummaryCounts:
    """The two scalar sections of an admin summary."""

    total_events: int = 0
    unique_sessions: int = 0


@dataclass(frozen=True)
class SummaryBreakdowns:
    """Grouped rows keyed by the **stored** label, never pre-truncated."""

    events_by_type: list[tuple[str, int]] = field(default_factory=list)
    top_pages: list[tuple[str, int]] = field(default_factory=list)
    top_referrers: list[tuple[str, int]] = field(default_factory=list)
    events_by_day: list[tuple[str, int]] = field(default_factory=list)


class AnalyticsRepository:
    """Reads and writes the native analytics tables through one session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event(self, values: dict[str, Any]) -> None:
        """Insert one already-normalised event row and commit it."""
        await self._session.execute(_INSERT_EVENT, values)
        await self._session.commit()

    async def insert_web_vital(self, values: dict[str, Any]) -> None:
        """Insert one already-normalised Web Vital row and commit it."""
        await self._session.execute(_INSERT_WEB_VITAL, values)
        await self._session.commit()

    async def counts(self, *, cutoff: datetime) -> SummaryCounts:
        """Return total events and distinct opaque sessions since *cutoff*."""
        return SummaryCounts(
            total_events=await self._scalar(_TOTAL_EVENTS, cutoff),
            unique_sessions=await self._scalar(_UNIQUE_SESSIONS, cutoff),
        )

    async def breakdowns(self, *, cutoff: datetime) -> SummaryBreakdowns:
        """Return the grouped rows for the window, one row per stored label."""
        return SummaryBreakdowns(
            events_by_type=await self._rows(_EVENTS_BY_TYPE, cutoff),
            top_pages=await self._rows(_TOP_PAGES, cutoff),
            top_referrers=await self._rows(_TOP_REFERRERS, cutoff),
            events_by_day=await self._rows(_EVENTS_BY_DAY, cutoff),
        )

    async def _scalar(self, statement: TextClause, cutoff: datetime) -> int:
        result = await self._session.execute(statement, {"cutoff": cutoff})
        return int(result.scalar() or 0)

    async def _rows(self, statement: TextClause, cutoff: datetime) -> list[tuple[str, int]]:
        result = await self._session.execute(statement, {"cutoff": cutoff})
        return [(str(label), int(count)) for label, count in result.all()]

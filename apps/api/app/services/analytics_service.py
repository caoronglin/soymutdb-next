"""Analytics tracking service – writes behavioural events to ClickHouse.

Events (pageview, click, search, widget) are inserted asynchronously so the
HTTP response (a 1x1 transparent GIF) is never blocked by database I/O.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any

from structlog import get_logger

from ..core.database import get_clickhouse_client

logger = get_logger(__name__)

EVENTS_TABLE = "analytics_events"

VALID_EVENT_TYPES = {"pageview", "click", "search", "widget"}

# 1×1 transparent GIF (43 bytes) – cached once at module load.
TRACKING_PIXEL: bytes = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


def hash_ip(ip: str, salt: str = "soymutdb-analytics") -> str:
    """Return a salted SHA-256 hex digest of *ip* (never store raw IPs)."""
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


class AnalyticsService:
    """Async service for recording and querying analytics events."""

    def __init__(self) -> None:
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        """Lazily await the ClickHouse client factory (it returns a coroutine)."""
        if self._client is None:
            self._client = await get_clickhouse_client()
        return self._client

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
        """Insert a single event row into ClickHouse.

        This method is ``await``-able so the caller can decide whether to
        block, fire-and-forget via ``asyncio.create_task``, or run via
        FastAPI ``BackgroundTasks``.
        """
        if event_type not in VALID_EVENT_TYPES:
            logger.warning("invalid_event_type", event_type=event_type)
            return

        now = datetime.now(UTC)
        start = time.perf_counter()
        try:
            client = await self._get_client()
            await client.insert(
                EVENTS_TABLE,
                data=[[
                    now,
                    session_id,
                    event_type,
                    page or "",
                    path or "",
                    widget_name or "",
                    search_query or "",
                    source or "",
                    referrer or "",
                    user_agent or "",
                    ip_hash or "",
                    duration_ms,
                ]],
                column_names=[
                    "timestamp", "session_id", "event_type", "page", "path",
                    "widget_name", "search_query", "source", "referrer",
                    "user_agent", "ip_hash", "duration_ms",
                ],
            )
            logger.debug(
                "analytics_event_recorded",
                event_type=event_type,
                session_id=session_id[:8],
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except Exception:
            # Never let analytics errors surface to the request lifecycle.
            logger.exception(
                "analytics_insert_failed",
                event_type=event_type,
                session_id=session_id[:8],
            )

    # ------------------------------------------------------------------ #
    # Read path (admin dashboards)
    # ------------------------------------------------------------------ #

    async def get_summary(
        self,
        days: int = 7,
    ) -> dict[str, Any]:
        """Return aggregate analytics summary over the last *days* days."""
        qp = {"days": days}
        queries: dict[str, str] = {
            "total_events": f"""
                SELECT count() FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
            """,
            "unique_sessions": f"""
                SELECT uniqExact(session_id) FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
            """,
            "events_by_type": f"""
                SELECT event_type, count() AS cnt
                FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
                GROUP BY event_type
                ORDER BY cnt DESC
            """,
            "top_pages": f"""
                SELECT page, count() AS cnt
                FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
                  AND event_type = 'pageview'
                  AND page != ''
                GROUP BY page
                ORDER BY cnt DESC
                LIMIT 20
            """,
            "top_referrers": f"""
                SELECT referrer, count() AS cnt
                FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
                  AND referrer != ''
                GROUP BY referrer
                ORDER BY cnt DESC
                LIMIT 20
            """,
            "top_searches": f"""
                SELECT search_query, count() AS cnt
                FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
                  AND event_type = 'search'
                  AND search_query != ''
                GROUP BY search_query
                ORDER BY cnt DESC
                LIMIT 20
            """,
            "events_by_day": f"""
                SELECT toDate(timestamp) AS d, count() AS cnt
                FROM {EVENTS_TABLE}
                WHERE timestamp >= now() - INTERVAL %(days)s DAY
                GROUP BY d
                ORDER BY d ASC
            """,
        }

        result: dict[str, Any] = {}
        try:
            client = await self._get_client()
            for key, q in queries.items():
                res = await client.query(q, parameters=qp)
                if key in (
                    "events_by_type",
                    "top_pages",
                    "top_referrers",
                    "top_searches",
                    "events_by_day",
                ):
                    result[key] = [
                        {"label": str(row[0]), "count": int(row[1])}
                        for row in res.result_rows
                    ]
                else:
                    val = res.first_row[0] if res.row_count else 0
                    result[key] = int(val)
        except Exception:
            logger.exception("analytics_summary_failed")
            return {
                "total_events": 0,
                "unique_sessions": 0,
                "events_by_type": [],
                "top_pages": [],
                "top_referrers": [],
                "top_searches": [],
                "events_by_day": [],
            }
        return result

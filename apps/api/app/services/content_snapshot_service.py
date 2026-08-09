"""Content snapshot aggregation (E2-2).

Builds the frozen snapshot contract served by ``GET /content/snapshot``
(docs/design/static-content-richtext-2026-08.md §4.1):

.. code-block:: jsonc

    {
      "schema_version": 1,
      "generated_at": "ISO8601",
      "news": {
        "source_total": 128,   // DB public-visible total
        "included_total": 128, // actually included (<= 500)
        "truncated": false,    // source_total > 500
        "items": [ /* public NewsSummary, published_at desc */ ]
      },
      "news_detail": { "<slug>": { /* public detail HTML */ } | null },
      "about": { title_en, title_zh, summary_en, summary_zh, content_en, content_zh }
    }

Visibility rules are identical to the public news endpoints (status=published
+ is_published + visibility window, reusing ``NewsService._visible_conditions``).
Truncation semantics: when ``source_total > 500`` the snapshot keeps the 500
newest and sets ``truncated=true``.  Visibility-window articles are included
in the list but their ``news_detail`` entry is ``null`` — they are never
statically generated (avoids stale public files after unpublish), so their
detail pages fall back to the API at runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.content import NewsArticle
from ..models.system_settings import SystemSetting
from ..schemas.news import NewsDetailResponse, NewsSummaryResponse
from .news_service import NewsService

#: Hard cap on the number of articles included in a snapshot (list + detail).
SNAPSHOT_MAX_ARTICLES = 500

#: ``about.*`` keys served by the snapshot (mirrors ``site.py``).
_ABOUT_KEYS = (
    "title_en",
    "title_zh",
    "summary_en",
    "summary_zh",
    "content_en",
    "content_zh",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ContentSnapshotService:
    """Aggregates the public content snapshot for SSG builds."""

    def __init__(self) -> None:
        self._news_service = NewsService()

    async def build_snapshot(self, db: AsyncSession) -> dict:
        """Return the full snapshot payload (JSON-serialisable)."""
        now = _utcnow()
        conditions = self._news_service._visible_conditions(now)

        # source_total: every DB-visible article (no cap).
        source_total = int(
            await db.scalar(
                select(func.count()).select_from(NewsArticle).where(*conditions)
            )
            or 0
        )

        # included: newest 500 visible articles (published_at desc).
        stmt = (
            select(NewsArticle)
            .where(*conditions)
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.id.desc(),
            )
            .limit(SNAPSHOT_MAX_ARTICLES)
        )
        rows = (await db.execute(stmt)).scalars().all()

        items = [
            NewsSummaryResponse.model_validate(r).model_dump(mode="json")
            for r in rows
        ]
        included_total = len(items)
        truncated = source_total > SNAPSHOT_MAX_ARTICLES

        # news_detail: full detail for articles WITHOUT a visibility window;
        # window articles are explicitly null (never statically generated).
        news_detail: dict[str, object] = {}
        for row in rows:
            if row.visible_from is None and row.visible_to is None:
                news_detail[row.slug] = NewsDetailResponse.model_validate(
                    row
                ).model_dump(mode="json")
            else:
                news_detail[row.slug] = None

        return {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "news": {
                "source_total": source_total,
                "included_total": included_total,
                "truncated": truncated,
                "items": items,
            },
            "news_detail": news_detail,
            "about": await self._load_about(db),
        }

    async def _load_about(self, db: AsyncSession) -> dict[str, str | None]:
        """Load the ``about.*`` settings (missing keys degrade to None)."""
        prefix = "about."
        stmt = select(SystemSetting).where(
            SystemSetting.key.in_([f"{prefix}{k}" for k in _ABOUT_KEYS])
        )
        rows = (await db.execute(stmt)).scalars().all()
        values: dict[str, str] = {row.key[len(prefix):]: row.value for row in rows}
        return {key: values.get(key) for key in _ABOUT_KEYS}


__all__ = ["ContentSnapshotService", "SNAPSHOT_MAX_ARTICLES"]

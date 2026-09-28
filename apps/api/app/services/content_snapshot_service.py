"""Content snapshot aggregation (E2-2).

Builds the frozen snapshot contract served by ``GET /content/snapshot``
(docs/design/static-content-richtext-2026-08.md §4.1):

.. code-block:: jsonc

    {
      "schema_version": 2,
      "generated_at": "ISO8601",
      "news": {
        "source_total": 128,   // DB public-visible total
        "included_total": 128, // actually included (<= 500)
        "truncated": false,    // source_total > 500
        "items": [ /* public NewsSummary, published_at desc */ ]
      },
      "news_detail": { "<slug>": { /* public detail HTML */ } | null },
      "about": { title_en, title_zh, summary_en, summary_zh, content_en, content_zh },
      "publications": [ /* newest bilingual publications, capped at 100 */ ],
      "static_pages": [ /* published StaticPage entries, sort_order/slug ascending */ ]
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

from ..core.sanitize import sanitize_rich_html
from ..core.site_variant import SiteVariant, variant_section
from ..models.content import NewsArticle, Publication, StaticPage
from ..models.system_settings import SystemSetting
from ..schemas.content import PublicationResponse, StaticPageResponse
from ..schemas.news import NewsDetailResponse, NewsSummaryResponse
from .news_service import NewsService

#: Hard cap on the number of articles included in a snapshot (list + detail).
SNAPSHOT_MAX_ARTICLES = 500

#: Hard cap on the number of publications included in a snapshot.
SNAPSHOT_MAX_PUBLICATIONS = 100

#: Hard cap on published static pages included in a snapshot.
SNAPSHOT_MAX_PAGES = 200

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

    async def build_snapshot(
        self,
        db: AsyncSession,
        *,
        release_id: int | None = None,
        page_definition_version: int | None = None,
        source_checksums: dict[str, str] | None = None,
        variant: SiteVariant = SiteVariant.EXTERNAL,
    ) -> dict:
        """Return the full snapshot payload (JSON-serialisable).

        ``release_id`` / ``page_definition_version`` make the snapshot
        *release-aware*: builds for an explicit release pin those identifiers
        so the generated tree and manifest can be matched to the source data
        they were built from.  Immutable build keys therefore differ by
        release, while the mutable active-release alias (read without an
        explicit release) stays available for interactive public reads.
        """
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

        snapshot: dict[str, object] = {
            "schema_version": 2,
            "generated_at": now.isoformat(),
            "news": {
                "source_total": source_total,
                "included_total": included_total,
                "truncated": truncated,
                "items": items,
            },
            "news_detail": news_detail,
            "about": await self._load_about(db, variant=variant),
            "publications": await self._load_publications(db),
            # Unpublished pages are deliberately omitted: emitting a null or
            # draft record would let SSG retain stale public output.
            "static_pages": await self._load_static_pages(db),
            "site_variant": variant.value,
        }

        # Release-aware metadata: present for explicit builds, absent for the
        # mutable active-release alias used by interactive public reads.
        if release_id is not None:
            snapshot["release_id"] = release_id
        if page_definition_version is not None:
            snapshot["page_definition_version"] = page_definition_version
        if source_checksums:
            snapshot["source_checksums"] = source_checksums

        return snapshot

    async def _load_about(
        self,
        db: AsyncSession,
        *,
        variant: SiteVariant = SiteVariant.EXTERNAL,
    ) -> dict[str, str | None]:
        """Load variant-scoped ``about.*`` settings with legacy fallback.

        The variant namespace is authoritative; the legacy non-variant keys are
        read only so a deployment can switch to the variant build before an
        administrator saves the first variant revision. Both are fetched in one
        round trip and the variant value wins when present.
        """
        selected_section = variant_section("about", variant)
        legacy_section = "about"
        selected_keys = {key: f"{selected_section}.{key}" for key in _ABOUT_KEYS}
        legacy_keys = {key: f"{legacy_section}.{key}" for key in _ABOUT_KEYS}
        rows = (
            await db.execute(
                select(SystemSetting).where(
                    SystemSetting.key.in_(
                        sorted({*selected_keys.values(), *legacy_keys.values()})
                    )
                )
            )
        ).scalars().all()
        raw_values = {row.key: row.value for row in rows}

        values: dict[str, str | None] = {
            key: raw_values.get(selected_keys[key], raw_values.get(legacy_keys[key]))
            for key in _ABOUT_KEYS
        }
        # Defence in depth: published content must not become an unsanitized
        # HTML source for SSG simply because a legacy write skipped the CMS
        # sanitizer. `/site/about` sanitizes on read; the snapshot must match.
        rich_keys = {"content_en", "content_zh"}
        return {
            key: (
                sanitize_rich_html(value)
                if key in rich_keys and value is not None
                else value
            )
            for key, value in values.items()
        }

    async def _load_publications(self, db: AsyncSession) -> list[dict[str, object]]:
        """Return the newest publications (year desc, id desc) as dicts."""
        stmt = (
            select(Publication)
            .order_by(Publication.year.desc().nullslast(), Publication.id.desc())
            .limit(SNAPSHOT_MAX_PUBLICATIONS)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            PublicationResponse(
                # The DOI is the public locator; the persistence key is not part
                # of the snapshot contract (see content.py).
                title=p.title,
                title_zh=p.title_zh,
                authors=p.authors,
                authors_zh=p.authors_zh,
                journal=p.journal,
                year=p.year,
                doi=p.doi,
                pmid=p.pmid,
                abstract=p.abstract,
                abstract_zh=p.abstract_zh,
                is_featured=p.is_featured,
                created_at=p.created_at,
            ).model_dump(mode="json")
            for p in rows
        ]


    async def _load_static_pages(self, db: AsyncSession) -> list[dict[str, object]]:
        """Return published pages in the deterministic public navigation order."""
        stmt = (
            select(StaticPage)
            .where(StaticPage.status == "published")
            .order_by(StaticPage.sort_order.asc(), StaticPage.slug.asc())
            .limit(SNAPSHOT_MAX_PAGES)
        )
        rows = (await db.execute(stmt)).scalars().all()
        pages: list[dict[str, object]] = []
        for page in rows:
            payload = StaticPageResponse.model_validate(page).model_dump(mode="json")
            payload["content_en"] = sanitize_rich_html(str(payload.get("content_en") or ""))
            if payload.get("content_zh") is not None:
                payload["content_zh"] = sanitize_rich_html(str(payload["content_zh"]))
            pages.append(payload)
        return pages


__all__ = [
    "ContentSnapshotService",
    "SNAPSHOT_MAX_ARTICLES",
    "SNAPSHOT_MAX_PAGES",
    "SNAPSHOT_MAX_PUBLICATIONS",
]

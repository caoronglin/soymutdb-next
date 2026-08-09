"""News operations service (B1).

Business logic for the news operations pipeline:
- public listing / featured / detail (published only, honouring the
  visible_from / visible_to window)
- HMAC short-lived preview tokens (15 min, stateless, NOT a JWT)
- admin CRUD with the is_published <-> status double-write contract

Preview token contract::

    token = hmac_sha256(slug + exp, settings.jwt_secret).hexdigest()
    url   = /news/{slug}?preview=<token>&exp=<exp>

``exp`` is a unix timestamp.  Verification requires the signature to match
AND ``now <= exp <= now + 15min`` (tokens cannot be minted in the future).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ConflictError, NotFoundError
from ..models.content import NewsArticle
from ..schemas.news import (
    CarouselGroupResponse,
    NewsCreate,
    NewsFeaturedResponse,
    NewsListResponse,
    NewsReorderRequest,
    NewsReorderResponse,
    NewsStatus,
    NewsSummaryResponse,
    NewsUpdate,
)

#: Preview token lifetime (seconds) – 15 minutes per the operations plan.
PREVIEW_TTL_SECONDS = 900

_settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _is_visible(article: NewsArticle, *, now: datetime | None = None) -> bool:
    """True when the article is published and inside its visibility window."""
    if article.status != NewsStatus.PUBLISHED.value or not article.is_published:
        return False
    now = now or _utcnow()
    if article.visible_from is not None and article.visible_from > now:
        return False
    if article.visible_to is not None and article.visible_to < now:
        return False
    return True


# ---------------------------------------------------------------------------
# Preview tokens (HMAC, stateless, short-lived)
# ---------------------------------------------------------------------------


def sign_preview_token(slug: str, *, ttl: int = PREVIEW_TTL_SECONDS) -> tuple[str, int]:
    """Return ``(token, exp)`` for *slug*.

    ``token = hmac_sha256(slug + exp, jwt_secret).hexdigest()`` — stateless,
    verifiable without any DB lookup or token store.
    """
    exp = int(time.time()) + max(1, int(ttl))
    message = f"{slug}{exp}".encode("utf-8")
    token = hmac.new(
        _settings.jwt_secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    return token, exp


def verify_preview_token(slug: str, token: str | None, exp: int | None) -> bool:
    """Verify an HMAC preview token for *slug*.

    Rejects missing/malformed tokens, expired tokens and tokens with an
    ``exp`` further than ``PREVIEW_TTL_SECONDS`` in the future (prevents
    attackers from crafting arbitrarily long-lived exp values once the secret
    leaks — the signature check below would still fail, but fail fast here).
    """
    if not token or exp is None:
        return False
    try:
        exp_int = int(exp)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if exp_int < now or exp_int > now + PREVIEW_TTL_SECONDS:
        return False
    expected = hmac.new(
        _settings.jwt_secret.encode("utf-8"),
        f"{slug}{exp_int}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, token)


# ---------------------------------------------------------------------------
# Public queries
# ---------------------------------------------------------------------------


class NewsService:
    """News business logic backed by PostgreSQL."""

    # -- visibility filter shared by every public query --------------------

    def _visible_conditions(self, now: datetime) -> list:
        return [
            NewsArticle.status == NewsStatus.PUBLISHED.value,
            NewsArticle.is_published.is_(True),
            or_(
                NewsArticle.visible_from.is_(None),
                NewsArticle.visible_from <= now,
            ),
            or_(
                NewsArticle.visible_to.is_(None),
                NewsArticle.visible_to >= now,
            ),
        ]

    async def list_articles(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> NewsListResponse:
        """Paginated public list (published only, category filter)."""
        now = _utcnow()
        conditions = self._visible_conditions(now)
        if category is not None:
            conditions.append(NewsArticle.category == category)

        total = int(
            await db.scalar(
                select(func.count()).select_from(NewsArticle).where(*conditions)
            )
            or 0
        )
        offset = (page - 1) * page_size
        stmt = (
            select(NewsArticle)
            .where(*conditions)
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.id.desc(),
            )
            .offset(offset)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return NewsListResponse(
            items=[NewsSummaryResponse.model_validate(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def featured(self, db: AsyncSession) -> NewsFeaturedResponse:
        """Homepage block: 5 featured articles + carousel groups."""
        now = _utcnow()
        conditions = self._visible_conditions(now)

        featured_rows = (
            await db.execute(
                select(NewsArticle)
                .where(*conditions)
                .order_by(
                    NewsArticle.featured_sort.asc(),
                    NewsArticle.published_at.desc().nullslast(),
                    NewsArticle.id.desc(),
                )
                .limit(5)
            )
        ).scalars().all()

        carousel_rows = (
            await db.execute(
                select(NewsArticle)
                .where(*conditions, NewsArticle.carousel_group.isnot(None))
                .order_by(
                    NewsArticle.carousel_group.asc(),
                    NewsArticle.carousel_sort.asc(),
                    NewsArticle.published_at.desc().nullslast(),
                )
            )
        ).scalars().all()

        carousel: list[CarouselGroupResponse] = []
        for row in carousel_rows:
            if not row.carousel_group:
                continue
            if not carousel or carousel[-1].group != row.carousel_group:
                carousel.append(
                    CarouselGroupResponse(
                        group=row.carousel_group,
                        items=[NewsSummaryResponse.model_validate(row)],
                    )
                )
            else:
                carousel[-1].items.append(NewsSummaryResponse.model_validate(row))

        return NewsFeaturedResponse(
            featured=[
                NewsSummaryResponse.model_validate(r) for r in featured_rows
            ],
            carousel=carousel,
        )

    async def get_by_slug(
        self,
        db: AsyncSession,
        slug: str,
        *,
        preview: str | None = None,
        exp: int | None = None,
    ) -> NewsArticle:
        """Detail lookup.

        Published + visible articles are always returned.  Hidden/draft
        articles are only returned when a valid HMAC preview token for the
        slug is supplied; otherwise the article is indistinguishable from a
        missing one (404).
        """
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.slug == slug)
        )
        article = result.scalar_one_or_none()
        if article is None:
            raise NotFoundError(f"News article '{slug}' not found")
        if not _is_visible(article):
            if not verify_preview_token(slug, preview, exp):
                raise NotFoundError(f"News article '{slug}' not found")
        return article

    # -- admin CRUD --------------------------------------------------------

    async def create_article(
        self, db: AsyncSession, payload: NewsCreate, author_id
    ) -> NewsArticle:
        """Create a draft/published/archived article.

        Double-write: ``is_published`` mirrors ``status``; publishing stamps
        ``published_at``.
        """
        published = payload.status == NewsStatus.PUBLISHED
        article = NewsArticle(
            title_en=payload.title_en,
            title_zh=payload.title_zh,
            content_en=payload.content_en,
            content_zh=payload.content_zh,
            slug=payload.slug,
            category=payload.category,
            cover_url=payload.cover_url,
            featured_sort=payload.featured_sort,
            carousel_group=payload.carousel_group,
            carousel_sort=payload.carousel_sort,
            status=payload.status.value,
            visible_from=payload.visible_from,
            visible_to=payload.visible_to,
            is_published=published,
            published_at=_utcnow() if published else None,
            author_id=author_id,
        )
        db.add(article)
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ConflictError(f"News slug '{payload.slug}' already exists") from exc
        await db.commit()
        await db.refresh(article)
        return article

    async def update_article(
        self, db: AsyncSession, news_id: int, payload: NewsUpdate, user_id
    ) -> NewsArticle:
        """Partial update with status/is_published double-write."""
        article = await self._get_by_id(db, news_id)

        if payload.title_en is not None:
            article.title_en = payload.title_en
        if payload.title_zh is not None:
            article.title_zh = payload.title_zh
        if payload.content_en is not None:
            article.content_en = payload.content_en
        if payload.content_zh is not None:
            article.content_zh = payload.content_zh
        if payload.slug is not None:
            article.slug = payload.slug
        if payload.category is not None:
            article.category = payload.category
        if payload.cover_url is not None:
            article.cover_url = payload.cover_url
        if payload.featured_sort is not None:
            article.featured_sort = payload.featured_sort
        if payload.carousel_group is not None:
            article.carousel_group = payload.carousel_group
        if payload.carousel_sort is not None:
            article.carousel_sort = payload.carousel_sort
        if payload.visible_from is not None:
            article.visible_from = payload.visible_from
        if payload.visible_to is not None:
            article.visible_to = payload.visible_to

        # status wins when both are supplied (status is the source of truth).
        if payload.status is not None:
            self._apply_status(article, payload.status)
        elif payload.is_published is not None:
            self._apply_status(
                article,
                NewsStatus.PUBLISHED if payload.is_published else NewsStatus.DRAFT,
            )

        try:
            await db.commit()
        except IntegrityError as exc:
            raise ConflictError(f"News slug '{article.slug}' already exists") from exc
        await db.refresh(article)
        return article

    async def delete_article(self, db: AsyncSession, news_id: int) -> None:
        """Hard delete (admin only)."""
        article = await self._get_by_id(db, news_id)
        await db.delete(article)
        await db.commit()

    async def reorder(
        self, db: AsyncSession, payload: NewsReorderRequest
    ) -> NewsReorderResponse:
        """Apply a full drag-and-drop ordering of ``featured_sort`` values.

        Fails loudly (404) when any referenced article does not exist, so a
        stale client drag cannot silently drop articles from the homepage.
        """
        ids = [item.id for item in payload.items]
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.id.in_(ids))
        )
        found = {a.id: a for a in result.scalars().all()}
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise NotFoundError(
                f"News article(s) not found: {', '.join(missing)}"
            )
        for item in payload.items:
            found[item.id].featured_sort = item.featured_sort
        await db.commit()
        return NewsReorderResponse(updated=len(payload.items))

    # -- helpers -----------------------------------------------------------

    async def _get_by_id(self, db: AsyncSession, news_id: int) -> NewsArticle:
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.id == news_id)
        )
        article = result.scalar_one_or_none()
        if article is None:
            raise NotFoundError(f"News article {news_id} not found")
        return article

    @staticmethod
    def _apply_status(article: NewsArticle, status: NewsStatus) -> None:
        """Sync ``status``, ``is_published`` and ``published_at`` (double-write)."""
        article.status = status.value
        if status == NewsStatus.PUBLISHED:
            article.is_published = True
            if article.published_at is None:
                article.published_at = _utcnow()
        else:
            article.is_published = False

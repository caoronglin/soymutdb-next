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
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import log_action
from ..core.config import get_settings
from ..core.exceptions import ConflictError, NotFoundError, ValidationError
from ..core.sanitize import sanitize_rich_html
from ..models.content import NewsArticle
from ..models.media import MediaAsset, MediaAssetStatus
from ..schemas.news import (
    CarouselGroupResponse,
    DeletedNewsListResponse,
    DeletedNewsSummaryResponse,
    NewsCreate,
    NewsFeaturedResponse,
    NewsListResponse,
    NewsReorderRequest,
    NewsReorderResponse,
    NewsStatus,
    NewsSummaryResponse,
    NewsUpdate,
)
from .cache import delete_prefix
from .content_snapshot_cache import invalidate_mutable_content_snapshot
from .external_article_service import verify_external_article_preview_attestation
from .media_service import validate_public_media_url

#: Preview token lifetime (seconds) – 15 minutes per the operations plan.
PREVIEW_TTL_SECONDS = 900

_settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def non_deleted_news_condition():
    """Return the canonical predicate excluding soft-deleted news rows."""
    return NewsArticle.deleted_at.is_(None)


async def _invalidate_public_news_caches() -> None:
    """Best-effort cache invalidation after the database commit succeeds.

    Redis is an accelerator, never the CMS source of truth.  ``delete_prefix``
    absorbs Redis failures, so a write remains durable even during a cache
    outage while successful cache nodes stop serving stale homepage/snapshot data.
    """
    await delete_prefix("news:featured")
    await invalidate_mutable_content_snapshot()


def _is_visible(article: NewsArticle, *, now: datetime | None = None) -> bool:
    """True when the article is published and inside its visibility window."""
    if (
        article.deleted_at is not None
        or article.status != NewsStatus.PUBLISHED.value
        or not article.is_published
    ):
        return False
    now = now or _utcnow()
    if article.visible_from is not None and article.visible_from > now:
        return False
    if article.visible_to is not None and article.visible_to < now:
        return False
    return True


def public_news_visibility_conditions(now: datetime | None = None) -> list:
    """Return the canonical SQL predicates for every unauthenticated news read.

    Both the modern ``/news`` API and retained ``/content/news`` compatibility
    routes must use this exact status/double-write/visibility-window contract.
    """
    current_time = now or _utcnow()
    return [
        non_deleted_news_condition(),
        NewsArticle.status == NewsStatus.PUBLISHED.value,
        NewsArticle.is_published.is_(True),
        or_(
            NewsArticle.visible_from.is_(None),
            NewsArticle.visible_from <= current_time,
        ),
        or_(
            NewsArticle.visible_to.is_(None),
            NewsArticle.visible_to >= current_time,
        ),
    ]


async def _resolve_cover(
    db: AsyncSession,
    *,
    asset_id: UUID | None,
    cover_url: str | None,
    alt_text: str | None,
) -> tuple[UUID | None, str | None, str | None]:
    """Resolve a library asset or validate a legacy HTTPS cover URL."""
    if asset_id is not None:
        asset = await db.scalar(
            select(MediaAsset).where(
                MediaAsset.id == asset_id,
                MediaAsset.status == MediaAssetStatus.READY.value,
            )
        )
        if asset is None:
            raise ValidationError("cover_asset_id must reference a ready media asset")
        effective_alt = (alt_text or asset.alt_text or "").strip() or None
        if not effective_alt:
            raise ValidationError("cover_alt_text is required for a cover asset")
        return asset.id, asset.public_url, effective_alt
    resolved_url = validate_public_media_url(cover_url)
    if resolved_url is None:
        return None, None, None
    return None, resolved_url, (alt_text or "").strip() or None


def _resolve_external_provenance(
    source_preview_token: str | None,
) -> tuple[str | None, str | None, str | None, datetime | None]:
    """Rehydrate provenance exclusively from one signed preview attestation.

    Browser forms never get to assert platform, URL, fingerprint, or source
    date directly. A missing token means a locally authored article; callers
    that attach a source must first obtain a short-lived preview attestation.
    """
    if source_preview_token is None:
        return None, None, None, None
    attestation = verify_external_article_preview_attestation(source_preview_token)
    return (
        attestation.platform,
        attestation.source_url,
        attestation.source_content_hash,
        attestation.source_published_at,
    )


# ---------------------------------------------------------------------------
# Preview tokens (HMAC, stateless, short-lived)
# ---------------------------------------------------------------------------


def sign_preview_token(slug: str, *, ttl: int = PREVIEW_TTL_SECONDS) -> tuple[str, int]:
    """Return ``(token, exp)`` for *slug*.

    ``token = hmac_sha256(slug + exp, jwt_secret).hexdigest()`` — stateless,
    verifiable without any DB lookup or token store.
    """
    exp = int(time.time()) + max(1, int(ttl))
    message = f"{slug}{exp}".encode()
    token = hmac.new(_settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
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
        f"{slug}{exp_int}".encode(),
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
        """Compatibility wrapper around the shared public-read contract."""
        return public_news_visibility_conditions(now)

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
            await db.scalar(select(func.count()).select_from(NewsArticle).where(*conditions)) or 0
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

    async def list_articles_admin(
        self,
        db: AsyncSession,
        *,
        status_filter: str | None = None,
        category: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> NewsListResponse:
        """Admin paginated list — sees ALL statuses (draft/published/archived).

        Optional filters: status (draft|published|archived), category, and
        a title/keyword ``search`` (case-insensitive ILIKE on title_en +
        title_zh).
        """
        page = max(1, page)
        page_size = min(100, max(1, page_size))

        conditions: list = [non_deleted_news_condition()]
        if status_filter is not None:
            conditions.append(NewsArticle.status == status_filter)
        if category is not None:
            conditions.append(NewsArticle.category == category)
        if search is not None and search.strip():
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    NewsArticle.title_en.ilike(pattern),
                    NewsArticle.title_zh.ilike(pattern),
                )
            )

        total = int(
            await db.scalar(select(func.count()).select_from(NewsArticle).where(*conditions)) or 0
        )
        offset = (page - 1) * page_size
        stmt = (
            select(NewsArticle)
            .where(*conditions)
            .order_by(
                NewsArticle.created_at.desc(),
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

    async def list_deleted_articles_admin(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> DeletedNewsListResponse:
        """Administrator paginated metadata-only list of soft-deleted articles."""
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        condition = NewsArticle.deleted_at.isnot(None)
        total = int(
            await db.scalar(select(func.count()).select_from(NewsArticle).where(condition)) or 0
        )
        offset = (page - 1) * page_size
        stmt = (
            select(NewsArticle)
            .where(condition)
            .order_by(NewsArticle.deleted_at.desc(), NewsArticle.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return DeletedNewsListResponse(
            items=[DeletedNewsSummaryResponse.model_validate(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def featured(self, db: AsyncSession) -> NewsFeaturedResponse:
        """Homepage block: 5 featured articles + carousel groups."""
        now = _utcnow()
        conditions = self._visible_conditions(now)

        featured_rows = (
            (
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
            )
            .scalars()
            .all()
        )

        carousel_rows = (
            (
                await db.execute(
                    select(NewsArticle)
                    .where(*conditions, NewsArticle.carousel_group.isnot(None))
                    .order_by(
                        NewsArticle.carousel_group.asc(),
                        NewsArticle.carousel_sort.asc(),
                        NewsArticle.published_at.desc().nullslast(),
                    )
                )
            )
            .scalars()
            .all()
        )

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
            featured=[NewsSummaryResponse.model_validate(r) for r in featured_rows],
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
            select(NewsArticle).where(NewsArticle.slug == slug, non_deleted_news_condition())
        )
        article = result.scalar_one_or_none()
        if article is None or article.deleted_at is not None:
            raise NotFoundError(f"News article '{slug}' not found")
        if not _is_visible(article):
            if not verify_preview_token(slug, preview, exp):
                raise NotFoundError(f"News article '{slug}' not found")
        return article

    # -- admin CRUD --------------------------------------------------------

    async def create_article(self, db: AsyncSession, payload: NewsCreate, author_id) -> NewsArticle:
        """Create a draft/published/archived article.

        Double-write: ``is_published`` mirrors ``status``; publishing stamps
        ``published_at``.
        """
        published = payload.status == NewsStatus.PUBLISHED
        cover_asset_id, cover_url, cover_alt_text = await _resolve_cover(
            db,
            asset_id=payload.cover_asset_id,
            cover_url=payload.cover_url,
            alt_text=payload.cover_alt_text,
        )
        source_platform, source_url, source_content_hash, source_published_at = (
            _resolve_external_provenance(payload.source_preview_token)
        )
        article = NewsArticle(
            title_en=payload.title_en,
            title_zh=payload.title_zh,
            content_en=sanitize_rich_html(payload.content_en),
            content_zh=(sanitize_rich_html(payload.content_zh) if payload.content_zh else None),
            source_platform=source_platform,
            source_url=source_url,
            source_content_hash=source_content_hash,
            source_published_at=source_published_at,
            source_synced_at=_utcnow() if source_platform is not None else None,
            slug=payload.slug,
            category=payload.category,
            cover_asset_id=cover_asset_id,
            cover_url=cover_url,
            cover_alt_text=cover_alt_text,
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
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A news slug or external source URL already exists") from exc
        await _invalidate_public_news_caches()
        await db.refresh(article)
        return article

    async def update_article(
        self, db: AsyncSession, news_id: int, payload: NewsUpdate, user_id
    ) -> NewsArticle:
        """Partial update with status/is_published double-write.

        Null semantics (D4 contract, via ``model_fields_set``):

        - **Field absent from the request** -> left untouched.
        - **Nullable field explicitly ``null``** (category, cover_url,
          carousel_group, title_zh, content_zh, visible_from, visible_to)
          -> cleared to NULL (e.g. removing a cover image).
        - **Non-nullable field explicitly ``null``** (title_en, content_en,
          slug, featured_sort, carousel_sort) -> ignored, previous value is
          kept (the DB columns are NOT NULL; a client sending ``null`` for
          these means "no change", not "clear").
        """
        article = await self._get_by_id(db, news_id)
        provided = payload.model_fields_set

        # Non-nullable fields: null means "leave unchanged".
        if "title_en" in provided and payload.title_en is not None:
            article.title_en = payload.title_en
        if "content_en" in provided and payload.content_en is not None:
            article.content_en = sanitize_rich_html(payload.content_en)
        if "slug" in provided and payload.slug is not None:
            article.slug = payload.slug
        if "featured_sort" in provided and payload.featured_sort is not None:
            article.featured_sort = payload.featured_sort
        if "carousel_sort" in provided and payload.carousel_sort is not None:
            article.carousel_sort = payload.carousel_sort

        # Nullable fields: explicit null clears, absent keeps.
        for field in (
            "title_zh",
            "category",
            "carousel_group",
            "visible_from",
            "visible_to",
        ):
            if field in provided:
                setattr(article, field, getattr(payload, field))
        # content_zh is nullable but rich-text: sanitize when a string is
        # supplied, clear when explicitly null.
        if "content_zh" in provided:
            article.content_zh = (
                sanitize_rich_html(payload.content_zh) if payload.content_zh is not None else None
            )

        # A library asset is canonical. The legacy URL path remains available
        # for older integrations, but unsafe schemes and storage URLs are rejected.
        if "cover_asset_id" in provided:
            if payload.cover_asset_id is None and payload.cover_url:
                # Existing integrations may send an explicit null asset id
                # alongside their still-valid legacy HTTPS URL.
                article.cover_asset_id = None
                article.cover_url = validate_public_media_url(payload.cover_url)
                article.cover_alt_text = (
                    (payload.cover_alt_text or "").strip() or None
                    if "cover_alt_text" in provided
                    else None
                )
            elif payload.cover_asset_id is None:
                article.cover_asset_id = None
                article.cover_url = None
                article.cover_alt_text = None
            else:
                resolved_id, resolved_url, resolved_alt = await _resolve_cover(
                    db,
                    asset_id=payload.cover_asset_id,
                    cover_url=None,
                    alt_text=(
                        payload.cover_alt_text
                        if "cover_alt_text" in provided
                        else article.cover_alt_text
                    ),
                )
                article.cover_asset_id = resolved_id
                article.cover_url = resolved_url
                article.cover_alt_text = resolved_alt
        elif "cover_url" in provided:
            article.cover_asset_id = None
            article.cover_url = validate_public_media_url(payload.cover_url)
            article.cover_alt_text = (
                (payload.cover_alt_text or "").strip() or None if payload.cover_url else None
            )
        if "cover_alt_text" in provided and "cover_asset_id" not in provided:
            article.cover_alt_text = (
                (payload.cover_alt_text or "").strip() or None if article.cover_url else None
            )

        if payload.clear_source_provenance:
            article.source_platform = None
            article.source_url = None
            article.source_content_hash = None
            article.source_published_at = None
            article.source_synced_at = None
        elif "source_preview_token" in provided:
            if payload.source_preview_token is None:
                raise ValidationError("source_preview_token must not be null")
            (
                article.source_platform,
                article.source_url,
                article.source_content_hash,
                article.source_published_at,
            ) = _resolve_external_provenance(payload.source_preview_token)
            article.source_synced_at = _utcnow()

        # status wins when both are supplied (status is the source of truth).
        if payload.status is not None:
            self._apply_status(article, payload.status)
        elif payload.is_published is not None:
            self._apply_status(
                article,
                NewsStatus.PUBLISHED if payload.is_published else NewsStatus.DRAFT,
            )

        # Validate a visibility window only when this request changes it. This
        # keeps unrelated edits safe for legacy records that predate the strict
        # window invariant, while still validating the final state for any
        # visibility mutation (including a one-sided partial update).
        if (
            {"visible_from", "visible_to"} & provided
            and article.visible_from is not None
            and article.visible_to is not None
            and article.visible_from >= article.visible_to
        ):
            raise ValidationError("visible_from must be earlier than visible_to")

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A news slug or external source URL already exists") from exc
        await _invalidate_public_news_caches()
        await db.refresh(article)
        return article

    async def delete_article(self, db: AsyncSession, news_id: int, *, actor_id: UUID) -> None:
        """Soft-delete an article and record the lifecycle transition atomically."""
        article = await self._get_by_id(db, news_id)
        article.deleted_at = _utcnow()
        article.deleted_by = actor_id
        await log_action(
            db,
            user_id=actor_id,
            action="news_deleted",
            resource_type="news_article",
            resource_id=str(article.id),
            old_value={"lifecycle": "active", "slug": article.slug},
            new_value={"lifecycle": "soft_deleted", "slug": article.slug},
        )
        await db.commit()
        await _invalidate_public_news_caches()

    async def restore_article(
        self, db: AsyncSession, news_id: int, *, actor_id: UUID
    ) -> NewsArticle:
        """Restore one soft-deleted article and record the transition atomically."""
        article = await self._get_by_id(db, news_id, include_deleted=True)
        if article.deleted_at is None:
            raise NotFoundError(f"News article {news_id} not found")
        article.deleted_at = None
        article.deleted_by = None
        await log_action(
            db,
            user_id=actor_id,
            action="news_restored",
            resource_type="news_article",
            resource_id=str(article.id),
            old_value={"lifecycle": "soft_deleted", "slug": article.slug},
            new_value={"lifecycle": "active", "slug": article.slug},
        )
        await db.commit()
        await _invalidate_public_news_caches()
        await db.refresh(article)
        return article

    async def purge_article(self, db: AsyncSession, news_id: int, *, actor_id: UUID) -> None:
        """Permanently remove one soft-deleted article while retaining lifecycle audit."""
        article = await self._get_by_id(db, news_id, include_deleted=True)
        if article.deleted_at is None:
            raise NotFoundError(f"News article {news_id} not found")
        article_id = article.id
        slug = article.slug
        await log_action(
            db,
            user_id=actor_id,
            action="news_purged",
            resource_type="news_article",
            resource_id=str(article_id),
            old_value={"lifecycle": "soft_deleted", "slug": slug},
            new_value={"lifecycle": "purged", "slug": slug},
        )
        await db.delete(article)
        await db.commit()
        await _invalidate_public_news_caches()

    async def reorder(self, db: AsyncSession, payload: NewsReorderRequest) -> NewsReorderResponse:
        """Apply a full drag-and-drop ordering of ``featured_sort`` values.

        Fails loudly (404) when any referenced article does not exist, so a
        stale client drag cannot silently drop articles from the homepage.
        """
        ids = [item.id for item in payload.items]
        result = await db.execute(
            select(NewsArticle).where(NewsArticle.id.in_(ids), non_deleted_news_condition())
        )
        found = {a.id: a for a in result.scalars().all()}
        missing = [str(i) for i in ids if i not in found]
        if missing:
            raise NotFoundError(f"News article(s) not found: {', '.join(missing)}")
        for item in payload.items:
            found[item.id].featured_sort = item.featured_sort
        await db.commit()
        await _invalidate_public_news_caches()
        return NewsReorderResponse(updated=len(payload.items))

    # -- helpers -----------------------------------------------------------

    async def _get_by_id(
        self, db: AsyncSession, news_id: int, *, include_deleted: bool = False
    ) -> NewsArticle:
        conditions = [NewsArticle.id == news_id]
        if not include_deleted:
            conditions.append(non_deleted_news_condition())
        result = await db.execute(select(NewsArticle).where(*conditions))
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
            article.published_at = None

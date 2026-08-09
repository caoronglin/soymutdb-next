"""Public news endpoints (B1): list / featured / detail.

Contract:
- ``GET /api/v1/news?category=&page=&page_size=``  published only,
  visibility window honoured, newest first
- ``GET /api/v1/news/featured``                    5 featured + carousel groups
- ``GET /api/v1/news/{slug}?preview=&exp=``        detail; hidden/draft
  articles require a valid HMAC preview token (15 min, stateless)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.news import (
    NewsDetailResponse,
    NewsFeaturedResponse,
    NewsListResponse,
)
from ...services.cache import get_or_set
from ...services.news_service import NewsService

router = APIRouter(prefix="/news", tags=["news"])
service = NewsService()

#: Short TTL (60s) for the homepage featured block: content changes
#: frequently through the admin pipeline, so the cached copy must go stale
#: quickly.  The empty result (no published articles yet) is cached too —
#: anti-penetration: the loader runs at most once per TTL instead of on
#: every homepage hit.
FEATURED_CACHE_TTL_SECONDS = 60


@router.get("", response_model=NewsListResponse)
async def list_news(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> NewsListResponse:
    """Paginated public news list (published only)."""
    return await service.list_articles(
        db, category=category, page=page, page_size=page_size
    )


@router.get("/featured", response_model=NewsFeaturedResponse)
async def featured_news(
    db: AsyncSession = Depends(get_db),
) -> NewsFeaturedResponse:
    """Homepage block: 5 featured articles + carousel groups.

    Read-hot query cached in Redis with a short TTL (60s, content changes
    frequently); a Redis failure degrades to a direct query.
    """
    payload = await get_or_set(
        "news:featured",
        ttl=FEATURED_CACHE_TTL_SECONDS,
        loader=lambda: _load_featured_news(db),
    )
    return NewsFeaturedResponse.model_validate(payload)


async def _load_featured_news(db: AsyncSession) -> dict:
    """Compute the featured block (loader for the Redis cache)."""
    return (await service.featured(db)).model_dump(mode="json")


@router.get("/{slug}", response_model=NewsDetailResponse)
async def get_news(
    slug: str,
    db: AsyncSession = Depends(get_db),
    preview: str | None = Query(default=None),
    exp: int | None = Query(default=None, ge=0),
) -> NewsDetailResponse:
    """Article detail.

    Published + visible articles are public.  Draft/hidden articles return a
    valid HMAC preview token URL from the admin endpoint
    (``/admin/news/{id}/preview-token``) and are then accessible with
    ``?preview=<token>&exp=<ts>`` without login.
    """
    article = await service.get_by_slug(db, slug, preview=preview, exp=exp)
    return NewsDetailResponse.model_validate(article)

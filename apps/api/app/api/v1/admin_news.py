"""Admin news endpoints (B1): CRUD, drag reorder, HMAC preview tokens.

Requires ``researcher`` role or higher (hierarchical RBAC, see
``app.core.security.has_role``).

Contract:
- ``POST   /api/v1/admin/news``                          create (201)
- ``PUT    /api/v1/admin/news/{news_id}``                update
- ``DELETE /api/v1/admin/news/{news_id}``                delete (204)
- ``PATCH  /api/v1/admin/news/reorder``                  featured_sort drag order
- ``GET    /api/v1/admin/news/{news_id}/preview-token``  HMAC token (15 min)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.content import NewsArticle
from ...schemas.news import (
    NewsCreate,
    NewsDetailResponse,
    NewsReorderRequest,
    NewsReorderResponse,
    NewsUpdate,
    PreviewTokenResponse,
)
from ...services.news_service import NewsService, sign_preview_token
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/news", tags=["admin-news"])
service = NewsService()


def _require_researcher(user: User) -> User:
    """Raise :class:`AuthorizationError` unless *user* is researcher+."""
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.RESEARCHER):
        raise AuthorizationError("Researcher access required")
    return user


async def _get_article(db: AsyncSession, news_id: int) -> NewsArticle:
    result = await db.execute(
        select(NewsArticle).where(NewsArticle.id == news_id)
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise NotFoundError(f"News article {news_id} not found")
    return article


@router.post(
    "",
    response_model=NewsDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_news(
    payload: NewsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsDetailResponse:
    """Create a news article (draft by default; publish via ``status``)."""
    _require_researcher(current_user)
    article = await service.create_article(db, payload, current_user.id)
    return NewsDetailResponse.model_validate(article)


@router.put("/{news_id}", response_model=NewsDetailResponse)
async def update_news(
    news_id: int,
    payload: NewsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsDetailResponse:
    """Partial update; ``status``/``is_published`` stay double-written."""
    _require_researcher(current_user)
    article = await service.update_article(db, news_id, payload, current_user.id)
    return NewsDetailResponse.model_validate(article)


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Hard-delete a news article."""
    _require_researcher(current_user)
    await service.delete_article(db, news_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/reorder", response_model=NewsReorderResponse)
async def reorder_news(
    payload: NewsReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsReorderResponse:
    """Apply a full drag-and-drop ordering of ``featured_sort``."""
    _require_researcher(current_user)
    return await service.reorder(db, payload)


@router.get("/{news_id}/preview-token", response_model=PreviewTokenResponse)
async def preview_token(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PreviewTokenResponse:
    """Mint a 15-minute stateless HMAC preview token for a hidden/draft article.

    The returned ``url`` (``/api/v1/news/{slug}?preview=<token>&exp=<ts>``)
    can be opened without login; verification happens on the public detail
    endpoint.  The token is NOT a JWT — no server-side state, HMAC-signed
    with ``settings.jwt_secret``.
    """
    _require_researcher(current_user)
    article = await _get_article(db, news_id)
    token, exp = sign_preview_token(article.slug)
    url = f"/api/v1/news/{article.slug}?preview={token}&exp={exp}"
    return PreviewTokenResponse(preview=token, exp=exp, url=url)

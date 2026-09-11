"""Admin news endpoints (B1): list (all statuses), CRUD, drag reorder, HMAC preview tokens.

Requires the ``content_editor`` capability (hierarchical RBAC, see
``app.core.security.has_role``).

Contract:
- ``GET    /api/v1/admin/news``                        list (all statuses, filter+search)
- ``POST   /api/v1/admin/news``                        create (201)
- ``PUT    /api/v1/admin/news/{news_id}``              update
- ``DELETE /api/v1/admin/news/{news_id}``              soft delete (204)
- ``POST   /api/v1/admin/news/{news_id}/restore``       administrator restore
- ``PATCH  /api/v1/admin/news/reorder``                featured_sort drag order
- ``GET    /api/v1/admin/news/{news_id}/preview-token``  HMAC token (15 min)
- ``POST   /api/v1/admin/news/external-preview``        fetch + sanitize for review only
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.ratelimit import external_article_preview_rate_limiter
from ...core.security import RoleName, has_role, require_admin_roles
from ...models.auth import User
from ...models.content import NewsArticle
from ...schemas.news import (
    DeletedNewsListResponse,
    ExternalArticlePreviewRequest,
    ExternalArticlePreviewResponse,
    NewsCreate,
    NewsDetailResponse,
    NewsListResponse,
    NewsReorderRequest,
    NewsReorderResponse,
    NewsUpdate,
    PreviewTokenResponse,
)
from ...services.external_article_service import (
    ExternalArticlePreviewService,
    sign_external_article_preview,
)
from ...services.news_service import NewsService, sign_preview_token
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/news", tags=["admin-news"])
service = NewsService()
external_preview_service = ExternalArticlePreviewService()


def _require_content_editor(user: User) -> User:
    """Raise :class:`AuthorizationError` unless *user* can manage content."""
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.CONTENT_EDITOR):
        raise AuthorizationError("Content editor access required")
    return user


def _require_administrator(user: User) -> User:
    """Raise unless *user* is allowed to restore soft-deleted news."""
    require_admin_roles(get_user_roles(user))
    return user


@router.get("", response_model=NewsListResponse)
async def list_news_admin(
    status_filter: str | None = Query(
        default=None,
        description="Filter by status: draft, published, archived (case-insensitive).",
    ),
    category: str | None = Query(default=None, description="Filter by category (exact match)."),
    search: str | None = Query(default=None, description="Case-insensitive title search."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsListResponse:
    """List ALL news articles — including drafts and archived.

    Unlike the public ``GET /news`` (published only), this admin endpoint
    sees every status and supports ``status_filter``, ``category`` and
    ``search`` parameters.
    """
    _require_content_editor(current_user)
    sf = status_filter.lower() if status_filter else None
    return await service.list_articles_admin(
        db,
        status_filter=sf,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get("/deleted", response_model=DeletedNewsListResponse)
async def list_deleted_news_admin(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeletedNewsListResponse:
    """List soft-deleted news metadata; restricted to administrators."""
    _require_administrator(current_user)
    return await service.list_deleted_articles_admin(db, page=page, page_size=page_size)


async def _get_article(db: AsyncSession, news_id: int) -> NewsArticle:
    result = await db.execute(
        select(NewsArticle).where(NewsArticle.id == news_id, NewsArticle.deleted_at.is_(None))
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise NotFoundError(f"News article {news_id} not found")
    return article


@router.post("/external-preview", response_model=ExternalArticlePreviewResponse)
async def preview_external_article(
    payload: ExternalArticlePreviewRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ExternalArticlePreviewResponse:
    """Fetch one approved external article for editor review.

    This explicit, bounded fetch never creates, updates, or publishes a CMS
    record.  The client must apply the returned sanitized HTML to the normal
    draft form and save it through the existing publishing workflow.
    """

    _require_content_editor(current_user)
    client_ip = request.client.host if request.client else None
    await external_article_preview_rate_limiter.enforce(
        user_id=str(current_user.id), client_ip=client_ip
    )
    preview = await external_preview_service.preview(payload.platform, payload.source_url)
    return ExternalArticlePreviewResponse(
        platform=preview.platform,
        source_url=preview.source_url,
        title=preview.title,
        content_html=preview.content_html,
        source_preview_token=sign_external_article_preview(preview),
        source_published_at=preview.source_published_at,
    )


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
    _require_content_editor(current_user)
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
    _require_content_editor(current_user)
    article = await service.update_article(db, news_id, payload, current_user.id)
    return NewsDetailResponse.model_validate(article)


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Soft-delete a news article while preserving its audit history."""
    _require_content_editor(current_user)
    await service.delete_article(db, news_id, actor_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{news_id}/restore", response_model=NewsDetailResponse)
async def restore_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsDetailResponse:
    """Restore a soft-deleted article; only administrators may do this."""
    _require_administrator(current_user)
    article = await service.restore_article(db, news_id, actor_id=current_user.id)
    return NewsDetailResponse.model_validate(article)


@router.delete("/{news_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_news(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Permanently remove a soft-deleted article; only administrators may do this."""
    _require_administrator(current_user)
    await service.purge_article(db, news_id, actor_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/reorder", response_model=NewsReorderResponse)
async def reorder_news(
    payload: NewsReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NewsReorderResponse:
    """Apply a full drag-and-drop ordering of ``featured_sort``."""
    _require_content_editor(current_user)
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
    _require_content_editor(current_user)
    article = await _get_article(db, news_id)
    token, exp = sign_preview_token(article.slug)
    url = f"/api/v1/news/{article.slug}?preview={token}&exp={exp}"
    return PreviewTokenResponse(preview=token, exp=exp, url=url)

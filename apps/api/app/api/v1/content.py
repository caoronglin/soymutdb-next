"""Content endpoints: news, publications, static pages, downloads."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...models.content import (
    DownloadFile,
    NewsArticle,
    Publication,
    StaticPage,
)
from ...schemas.content import (
    DownloadFileResponse,
    NewsResponse,
    PublicationResponse,
    SignedUrlResponse,
    StaticPageResponse,
)
from ...services.cache import get_or_set
from ...services.content_snapshot_service import ContentSnapshotService
from ...utils.s3 import generate_presigned_url

router = APIRouter(prefix="/content", tags=["content"])


# ---------------------------------------------------------------------------
# Snapshot (SSG content feed)
# ---------------------------------------------------------------------------


@router.get("/snapshot")
async def content_snapshot(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_id: int | None = Query(default=None, ge=1),
    page_definition_version: int | None = Query(default=None, ge=1),
) -> dict:
    """Public content snapshot for static builds (E2-2).

    Frozen contract in ``docs/design/static-content-richtext-2026-08.md``
    §4.1: schema_version/generated_at/news{source_total,included_total,
    truncated,items}/news_detail{slug: detail|null}/about/publications.

    Release-aware: pass ``release_id`` (and optionally
    ``page_definition_version``) to build an immutable, release-pinned
    snapshot whose cache key differs by release.  Without an explicit
    ``release_id`` the mutable active-release alias is served, for interactive
    public reads only.

    Aggregation is cached in Redis for 60 s (cache.py); the response carries
    an ETag so build-time fetchers can short-circuit with 304.
    """
    if release_id is not None:
        cache_key = f"content:snapshot:release:{release_id}:pv:{page_definition_version}"
    else:
        cache_key = "content:snapshot"
    payload = await get_or_set(
        cache_key,
        60,
        loader=lambda: _build_snapshot(
            db,
            release_id=release_id,
            page_definition_version=page_definition_version,
        ),
    )
    etag = '"' + hashlib.sha256(
        payload["generated_at"].encode("utf-8")
    ).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        response.status_code = 304
        return {}
    response.headers["ETag"] = etag
    return payload


async def _build_snapshot(
    db: AsyncSession,
    *,
    release_id: int | None = None,
    page_definition_version: int | None = None,
) -> dict:
    service = ContentSnapshotService()
    return await service.build_snapshot(
        db,
        release_id=release_id,
        page_definition_version=page_definition_version,
    )


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


@router.get("/news", response_model=list[NewsResponse])
async def list_news(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[NewsResponse]:
    """List published news articles."""
    result = await db.execute(
        select(NewsArticle)
        .where(NewsArticle.is_published.is_(True))
        .order_by(NewsArticle.published_at.desc())
        .limit(limit)
    )
    return [_news_to_response(n) for n in result.scalars().all()]


@router.get("/news/{slug}", response_model=NewsResponse)
async def get_news(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> NewsResponse:
    result = await db.execute(
        select(NewsArticle).where(
            NewsArticle.slug == slug, NewsArticle.is_published.is_(True)
        )
    )
    article = result.scalar_one_or_none()
    if article is None:
        raise NotFoundError(f"News article '{slug}' not found")
    return _news_to_response(article)


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------


@router.get("/publications", response_model=list[PublicationResponse])
async def list_publications(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[PublicationResponse]:
    """List publications."""
    result = await db.execute(
        select(Publication)
        .order_by(Publication.year.desc().nullslast(), Publication.id.desc())
        .limit(limit)
    )
    return [_pub_to_response(p) for p in result.scalars().all()]


@router.get("/publications/{publication_id}", response_model=PublicationResponse)
async def get_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
) -> PublicationResponse:
    result = await db.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    pub = result.scalar_one_or_none()
    if pub is None:
        raise NotFoundError(f"Publication {publication_id} not found")
    return _pub_to_response(pub)


# ---------------------------------------------------------------------------
# Static pages
# ---------------------------------------------------------------------------


@router.get("/pages", response_model=list[StaticPageResponse])
async def list_pages(
    db: AsyncSession = Depends(get_db),
) -> list[StaticPageResponse]:
    """List published static pages."""
    result = await db.execute(
        select(StaticPage)
        .where(StaticPage.status == "published")
        .order_by(StaticPage.sort_order.asc(), StaticPage.slug)
    )
    return [_page_to_response(p) for p in result.scalars().all()]


@router.get("/pages/{slug}", response_model=StaticPageResponse)
async def get_page(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> StaticPageResponse:
    result = await db.execute(
        select(StaticPage).where(
            StaticPage.slug == slug, StaticPage.status == "published"
        )
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page '{slug}' not found")
    return _page_to_response(page)


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


@router.get("/downloads", response_model=list[DownloadFileResponse])
async def list_downloads(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(default=None),
) -> list[DownloadFileResponse]:
    """List downloadable files."""
    stmt = select(DownloadFile).order_by(DownloadFile.created_at.desc())
    if category is not None:
        stmt = stmt.where(DownloadFile.category == category)
    result = await db.execute(stmt)
    return [_dl_to_response(d) for d in result.scalars().all()]


@router.get("/downloads/{file_id}/url", response_model=SignedUrlResponse)
async def get_download_url(
    file_id: int,
    db: AsyncSession = Depends(get_db),
) -> SignedUrlResponse:
    """Generate a pre-signed download URL for a file.

    If the file URL is an S3 path (``s3://bucket/key``) a pre-signed URL is
    generated.  Otherwise the file URL is returned directly.
    """
    result = await db.execute(select(DownloadFile).where(DownloadFile.id == file_id))
    dl = result.scalar_one_or_none()
    if dl is None:
        raise NotFoundError(f"Download file {file_id} not found")

    url = dl.file_url
    expires_in = 3600

    if url.startswith("s3://"):
        try:
            url = generate_presigned_url(url, expires_in=expires_in)
        except Exception:
            # Fall back to the raw S3 path if presigning fails
            pass

    return SignedUrlResponse(url=url, expires_in=expires_in)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _news_to_response(n: NewsArticle) -> NewsResponse:
    return NewsResponse(
        id=str(n.id),
        title_en=n.title_en,
        title_zh=n.title_zh,
        slug=n.slug,
        category=n.category,
        is_published=n.is_published,
        published_at=n.published_at,
        created_at=n.created_at,
        updated_at=n.updated_at,
    )


def _pub_to_response(p: Publication) -> PublicationResponse:
    return PublicationResponse(
        id=str(p.id),
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
    )


def _page_to_response(p: StaticPage) -> StaticPageResponse:
    return StaticPageResponse(
        id=str(p.id),
        slug=p.slug,
        title_en=p.title_en,
        title_zh=p.title_zh,
        content_en=p.content_en,
        content_zh=p.content_zh,
        status=p.status,
        category=p.category,
        summary=p.summary,
        sort_order=p.sort_order,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _dl_to_response(d: DownloadFile) -> DownloadFileResponse:
    return DownloadFileResponse(
        id=str(d.id),
        name=d.name,
        description=d.description,
        file_url=d.file_url,
        file_size=d.file_size,
        category=d.category,
        download_count=d.download_count,
        created_at=d.created_at,
    )

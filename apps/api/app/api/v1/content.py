"""Content endpoints: news, publications, static pages, downloads."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...core.database import get_db
from ...core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from ...core.security import RoleName, has_role
from ...core.site_variant import SiteVariant
from ...models.auth import User
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
from ...services.news_service import public_news_visibility_conditions
from ...services.release_context import ReleaseContext, get_release_context
from ...utils.s3 import generate_presigned_url
from .deps import get_optional_user, get_user_roles

logger = get_logger(__name__)

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
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    current_user: User | None = Depends(get_optional_user),
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
    if variant is SiteVariant.INTERNAL:
        if current_user is None:
            raise AuthenticationError("Internal content requires authentication")
        if not has_role(get_user_roles(current_user), RoleName.VIEWER):
            raise AuthorizationError("Viewer role required for internal content")
    if release_id is not None:
        cache_key = (
            f"content:snapshot:{variant.value}"
            f":release:{release_id}:pv:{page_definition_version}"
        )
    else:
        cache_key = f"content:snapshot:{variant.value}"
    payload = await get_or_set(
        cache_key,
        60,
        loader=lambda: _build_snapshot(
            db,
            release_id=release_id,
            page_definition_version=page_definition_version,
            variant=variant,
        ),
    )
    etag = '"' + hashlib.sha256(
        payload["generated_at"].encode("utf-8")
    ).hexdigest()[:16] + '"'
    # The snapshot is mutable, so shared caches must revalidate before reuse.
    # Internal snapshots also vary by Authorization and must never be shared.
    response.headers["Cache-Control"] = (
        "private, no-store"
        if variant is SiteVariant.INTERNAL
        else "public, max-age=0, must-revalidate"
    )
    response.headers["Vary"] = (
        "Authorization" if variant is SiteVariant.INTERNAL else "Accept"
    )
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        response.status_code = 304
        return {}
    return payload


async def _build_snapshot(
    db: AsyncSession,
    *,
    release_id: int | None = None,
    page_definition_version: int | None = None,
    variant: SiteVariant = SiteVariant.EXTERNAL,
) -> dict:
    service = ContentSnapshotService()
    return await service.build_snapshot(
        db,
        release_id=release_id,
        page_definition_version=page_definition_version,
        variant=variant,
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
        .where(*public_news_visibility_conditions())
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
            NewsArticle.slug == slug, *public_news_visibility_conditions()
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


@router.get("/publications/{doi:path}", response_model=PublicationResponse)
async def get_publication(
    doi: str,
    db: AsyncSession = Depends(get_db),
) -> PublicationResponse:
    """Get one publication by its DOI.

    ``doi`` is the publication's own scholarly identifier (it contains ``/``, so
    the route uses a path converter). The persistence key is not a locator: a
    numeric value returns the same not-found response as an unknown DOI, so the
    endpoint is not an existence oracle for internal ids.
    """
    normalized = doi.strip()
    if not normalized or not normalized.lower().startswith("10."):
        # A bare integer is a persistence-key probe, not a DOI.
        raise NotFoundError(f"Publication {doi!r} not found")
    result = await db.execute(
        select(Publication).where(Publication.doi == normalized)
    )
    pub = result.scalar_one_or_none()
    if pub is None:
        raise NotFoundError(f"Publication {doi!r} not found")
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
    release_context: ReleaseContext = Depends(get_release_context),
    category: str | None = Query(default=None),
) -> list[DownloadFileResponse]:
    """List downloadable files belonging to the resolved published release.

    ``download_files.release_id`` is nullable, and the list previously selected
    every row — including drafts and files not (yet) bound to any release. Both
    are excluded here, so a file only appears once its release is published.
    """
    stmt = (
        select(DownloadFile)
        .where(DownloadFile.release_id == release_context.release_id)
        .order_by(DownloadFile.created_at.desc())
    )
    if category is not None:
        stmt = stmt.where(DownloadFile.category == category)
    result = await db.execute(stmt)
    return [_dl_to_response(d) for d in result.scalars().all()]


@router.get("/downloads/{file_id}/url", response_model=SignedUrlResponse)
async def get_download_url(
    file_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> SignedUrlResponse:
    """Generate a download URL for a file in the resolved published release.

    The file must be bound to the resolved release: an id from a draft release
    (or an unbound row) is not a valid locator. If the stored location is an S3
    path a pre-signed URL is minted; a plain HTTP(S) location is returned
    as-is; anything else is refused rather than handed to the client as a
    download target.
    """
    result = await db.execute(
        select(DownloadFile).where(
            DownloadFile.id == file_id,
            DownloadFile.release_id == release_context.release_id,
        )
    )
    dl = result.scalar_one_or_none()
    if dl is None:
        raise NotFoundError(f"Download file {file_id} not found")

    expires_in = 3600
    url = dl.file_url

    if url.startswith("s3://"):
        try:
            url = generate_presigned_url(url, expires_in=expires_in)
        except Exception as exc:
            # Falling back to the raw ``s3://`` path would hand the client a
            # URL it cannot fetch; fail closed instead.
            logger.warning(
                "download_presign_failed", file_id=file_id, error=str(exc)
            )
            raise ServiceUnavailableError(
                "The download link could not be generated; try again shortly."
            ) from exc
    elif not _is_safe_download_url(url):
        raise ValidationError(
            "This file's stored location is not a supported download target"
        )

    # A presigned URL is a capability: never let a cache retain it.
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"

    return SignedUrlResponse(url=url, expires_in=expires_in)


#: Download targets must be an object-store path or a plain web URL. Anything
#: else (``javascript:``, ``data:``, a local ``file:`` path) is not a download.
_SAFE_DOWNLOAD_SCHEMES = ("http://", "https://")


def _is_safe_download_url(url: str) -> bool:
    """True when *url* is an acceptable client-facing download target."""
    return url.lower().startswith(_SAFE_DOWNLOAD_SCHEMES)


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
        sha256=d.sha256,
        license=d.license,
        generated_at=d.generated_at,
        source_ref=d.source_ref,
    )

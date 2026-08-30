"""Admin content endpoints: full CRUD + versioning for static pages (administrator-only)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.sanitize import sanitize_rich_html
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.content import ContentVersion, StaticPage
from ...schemas.content import (
    ContentVersionResponse,
    PageStatus,
    StaticPageCreate,
    StaticPageDetailResponse,
    StaticPageMigrationDryRunRequest,
    StaticPageMigrationDryRunResponse,
    StaticPageUpdate,
)
from ...services.static_page_migration_service import migrate_static_pages
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/content", tags=["admin-content"])


def _require_admin(user: User) -> None:
    """Raise :class:`AuthorizationError` unless *user* is an administrator."""
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


async def _get_current_version(db: AsyncSession, page_id: int) -> int:
    """Return the highest version number for *page_id* (0 if none)."""
    result = await db.execute(
        select(func.max(ContentVersion.version)).where(
            ContentVersion.page_id == page_id
        )
    )
    current = result.scalar_one_or_none()
    return int(current) if current is not None else 0


async def _get_current_versions(
    db: AsyncSession, page_ids: list[int]
) -> dict[int, int]:
    """Load current version numbers for a page list in one grouped query."""
    if not page_ids:
        return {}
    result = await db.execute(
        select(ContentVersion.page_id, func.max(ContentVersion.version))
        .where(ContentVersion.page_id.in_(page_ids))
        .group_by(ContentVersion.page_id)
    )
    return {page_id: int(version) for page_id, version in result.all() if version is not None}


def _page_to_detail_response(
    page: StaticPage, current_version: int
) -> StaticPageDetailResponse:
    """Serialise a :class:`StaticPage` into a :class:`StaticPageDetailResponse`."""
    author_name: str | None = None
    if page.author is not None:
        author_name = page.author.full_name or page.author.username
    return StaticPageDetailResponse(
        id=str(page.id),
        slug=page.slug,
        title_en=page.title_en,
        title_zh=page.title_zh,
        content_en=page.content_en,
        content_zh=page.content_zh,
        status=page.status,
        category=page.category,
        summary=page.summary,
        sort_order=page.sort_order,
        created_at=page.created_at,
        updated_at=page.updated_at,
        author_name=author_name,
        published_at=page.published_at,
        current_version=current_version,
    )


def _version_to_response(version: ContentVersion) -> ContentVersionResponse:
    """Serialise a :class:`ContentVersion` into a :class:`ContentVersionResponse`."""
    return ContentVersionResponse(
        id=str(version.id),
        page_id=str(version.page_id),
        version=version.version,
        title_en=version.title_en,
        title_zh=version.title_zh,
        content_en=version.content_en,
        content_zh=version.content_zh,
        summary=version.summary,
        edited_by=str(version.edited_by) if version.edited_by else None,
        edit_comment=version.edit_comment,
        created_at=version.created_at,
    )


# ---------------------------------------------------------------------------
# 1. List pages (including drafts)
# ---------------------------------------------------------------------------


@router.get("/pages")
async def list_pages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict[str, object]:
    """List all static pages (including drafts) with optional filters."""
    _require_admin(current_user)

    conditions = []
    if status_filter is not None:
        conditions.append(StaticPage.status == status_filter)
    if category is not None:
        conditions.append(StaticPage.category == category)
    where_clause = and_(*conditions) if conditions else None

    count_stmt = select(func.count()).select_from(StaticPage)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    offset = (page - 1) * page_size
    stmt = (
        select(StaticPage)
        .order_by(StaticPage.sort_order.asc(), StaticPage.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    result = await db.execute(stmt)
    pages = result.scalars().all()

    current_versions = await _get_current_versions(db, [p.id for p in pages])
    items = [_page_to_detail_response(p, current_versions.get(p.id, 0)) for p in pages]

    return {"items": items, "total": total}



@router.post(
    "/pages/migrate-to-page-builder/dry-run",
    response_model=StaticPageMigrationDryRunResponse,
)
async def dry_run_page_builder_migration(
    payload: StaticPageMigrationDryRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageMigrationDryRunResponse:
    """Preview a StaticPage migration without mutating source or target rows."""
    _require_admin(current_user)
    report = await migrate_static_pages(db, dry_run=True, slugs=payload.slugs)
    return StaticPageMigrationDryRunResponse(
        dry_run=report.dry_run,
        created=report.created,
        skipped=report.skipped,
        invalid=report.invalid,
        items=[
            {
                "static_page_id": item.static_page_id,
                "slug": item.slug,
                "route": item.route,
                "outcome": item.outcome,
                "error_code": item.error_code,
                "message": item.message,
            }
            for item in report.items
        ],
    )

# ---------------------------------------------------------------------------
# 2. Get a single page
# ---------------------------------------------------------------------------


@router.get("/pages/{page_id}", response_model=StaticPageDetailResponse)
async def get_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Get a single static page with full detail."""
    _require_admin(current_user)

    result = await db.execute(select(StaticPage).where(StaticPage.id == page_id))
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")
    cv = await _get_current_version(db, page.id)
    return _page_to_detail_response(page, cv)


# ---------------------------------------------------------------------------
# 3. Create a new page
# ---------------------------------------------------------------------------


@router.post(
    "/pages",
    response_model=StaticPageDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_page(
    payload: StaticPageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Create a new static page and its first content version."""
    _require_admin(current_user)

    published_at: datetime | None = None
    if payload.status == PageStatus.PUBLISHED:
        published_at = datetime.now(datetime.UTC)

    page = StaticPage(
        slug=payload.slug,
        title_en=payload.title_en,
        title_zh=payload.title_zh,
        content_en=sanitize_rich_html(payload.content_en),
        content_zh=(
            sanitize_rich_html(payload.content_zh)
            if payload.content_zh
            else None
        ),
        status=payload.status.value,
        author_id=current_user.id,
        summary=payload.summary,
        category=payload.category,
        sort_order=payload.sort_order,
        published_at=published_at,
    )
    db.add(page)
    await db.flush()

    version = ContentVersion(
        page_id=page.id,
        version=1,
        title_en=payload.title_en,
        title_zh=payload.title_zh,
        content_en=sanitize_rich_html(payload.content_en),
        content_zh=(
            sanitize_rich_html(payload.content_zh)
            if payload.content_zh
            else None
        ),
        summary=payload.summary,
        edited_by=current_user.id,
        edit_comment=payload.edit_comment,
    )
    db.add(version)
    await db.commit()
    await db.refresh(page)
    await db.refresh(version)

    return _page_to_detail_response(page, 1)


# ---------------------------------------------------------------------------
# 4. Update a page
# ---------------------------------------------------------------------------


@router.put("/pages/{page_id}", response_model=StaticPageDetailResponse)
async def update_page(
    page_id: int,
    payload: StaticPageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Update a static page and create a new content version snapshot."""
    _require_admin(current_user)

    result = await db.execute(select(StaticPage).where(StaticPage.id == page_id))
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    new_title_en = payload.title_en if payload.title_en is not None else page.title_en
    new_title_zh = payload.title_zh if payload.title_zh is not None else page.title_zh
    new_content_en = (
        sanitize_rich_html(payload.content_en)
        if payload.content_en is not None
        else page.content_en
    )
    new_content_zh = (
        sanitize_rich_html(payload.content_zh)
        if payload.content_zh is not None
        else page.content_zh
    )
    new_summary = payload.summary if payload.summary is not None else page.summary
    new_category = payload.category if payload.category is not None else page.category
    new_sort_order = (
        payload.sort_order if payload.sort_order is not None else page.sort_order
    )

    page.title_en = new_title_en
    page.title_zh = new_title_zh
    page.content_en = new_content_en
    page.content_zh = new_content_zh
    page.summary = new_summary
    page.category = new_category
    page.sort_order = new_sort_order

    current_version = await _get_current_version(db, page.id)
    next_version = current_version + 1

    version = ContentVersion(
        page_id=page.id,
        version=next_version,
        title_en=new_title_en,
        title_zh=new_title_zh,
        content_en=new_content_en,
        content_zh=new_content_zh,
        summary=new_summary,
        edited_by=current_user.id,
        edit_comment=payload.edit_comment,
    )
    db.add(version)
    await db.commit()
    await db.refresh(page)

    return _page_to_detail_response(page, next_version)


# ---------------------------------------------------------------------------
# 5. Delete a page
# ---------------------------------------------------------------------------


@router.delete("/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a static page and its versions (CASCADE)."""
    _require_admin(current_user)

    result = await db.execute(select(StaticPage).where(StaticPage.id == page_id))
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    await db.delete(page)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# 6. Publish a page
# ---------------------------------------------------------------------------


@router.post("/pages/{page_id}/publish", response_model=StaticPageDetailResponse)
async def publish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Set a page's status to 'published' and record the publication time."""
    _require_admin(current_user)

    result = await db.execute(select(StaticPage).where(StaticPage.id == page_id))
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    page.status = PageStatus.PUBLISHED.value
    if page.published_at is None:
        page.published_at = datetime.now(datetime.UTC)
    await db.commit()
    await db.refresh(page)

    cv = await _get_current_version(db, page.id)
    return _page_to_detail_response(page, cv)


# ---------------------------------------------------------------------------
# 7. Unpublish a page
# ---------------------------------------------------------------------------


@router.post("/pages/{page_id}/unpublish", response_model=StaticPageDetailResponse)
async def unpublish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Set a page's status back to 'draft'."""
    _require_admin(current_user)

    result = await db.execute(select(StaticPage).where(StaticPage.id == page_id))
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    page.status = PageStatus.DRAFT.value
    await db.commit()
    await db.refresh(page)

    cv = await _get_current_version(db, page.id)
    return _page_to_detail_response(page, cv)


# ---------------------------------------------------------------------------
# 8. List all versions of a page
# ---------------------------------------------------------------------------


@router.get(
    "/pages/{page_id}/versions",
    response_model=list[ContentVersionResponse],
)
async def list_versions(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ContentVersionResponse]:
    """List all content versions for a page (newest first)."""
    _require_admin(current_user)

    page_result = await db.execute(
        select(StaticPage).where(StaticPage.id == page_id)
    )
    if page_result.scalar_one_or_none() is None:
        raise NotFoundError(f"Page {page_id} not found")

    result = await db.execute(
        select(ContentVersion)
        .where(ContentVersion.page_id == page_id)
        .order_by(ContentVersion.version.desc())
    )
    versions = result.scalars().all()
    return [_version_to_response(v) for v in versions]


# ---------------------------------------------------------------------------
# 9. Get a specific version
# ---------------------------------------------------------------------------


@router.get(
    "/pages/{page_id}/versions/{version_num}",
    response_model=ContentVersionResponse,
)
async def get_version(
    page_id: int,
    version_num: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContentVersionResponse:
    """Get a specific content version of a page."""
    _require_admin(current_user)

    result = await db.execute(
        select(ContentVersion).where(
            ContentVersion.page_id == page_id,
            ContentVersion.version == version_num,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError(
            f"Version {version_num} for page {page_id} not found"
        )
    return _version_to_response(version)


# ---------------------------------------------------------------------------
# 10. Restore a previous version
# ---------------------------------------------------------------------------


@router.post(
    "/pages/{page_id}/versions/{version_num}/restore",
    response_model=StaticPageDetailResponse,
)
async def restore_version(
    page_id: int,
    version_num: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StaticPageDetailResponse:
    """Restore a previous version: copy its content back to the page and snapshot."""
    _require_admin(current_user)

    page_result = await db.execute(
        select(StaticPage).where(StaticPage.id == page_id)
    )
    page = page_result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")

    version_result = await db.execute(
        select(ContentVersion).where(
            ContentVersion.page_id == page_id,
            ContentVersion.version == version_num,
        )
    )
    version = version_result.scalar_one_or_none()
    if version is None:
        raise NotFoundError(
            f"Version {version_num} for page {page_id} not found"
        )

    page.title_en = version.title_en
    page.title_zh = version.title_zh
    page.content_en = version.content_en
    page.content_zh = version.content_zh
    page.summary = version.summary

    current_version = await _get_current_version(db, page.id)
    next_version = current_version + 1

    new_version = ContentVersion(
        page_id=page.id,
        version=next_version,
        title_en=version.title_en,
        title_zh=version.title_zh,
        content_en=version.content_en,
        content_zh=version.content_zh,
        summary=version.summary,
        edited_by=current_user.id,
        edit_comment=f"Restored from version {version_num}",
    )
    db.add(new_version)
    await db.commit()
    await db.refresh(page)

    return _page_to_detail_response(page, next_version)

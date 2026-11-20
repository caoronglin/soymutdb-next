"""Page Builder service: versioned create/edit/preview/publish operations.

All mutations create a fresh ``PageDefinitionVersion``; a version once
``published`` is never mutated.  Draft edits carry an optimistic
``base_version`` so concurrent editors get a 409 instead of silently
overwriting each other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from ..core.task_contract import PAGE_BUILDER_PUBLISH_TASK
from ..models.outbox import OutboxEvent
from ..models.page_builder import (
    PageDefinition,
    PageDefinitionStatus,
    PageDefinitionVersion,
)
from ..services.outbox_service import enqueue_task_event
from .registry import validate_definition, validate_plugin_launchers, validate_route

#: Domain event consumed by the dedicated Page Builder lifecycle task. Static
#: artifact deployment remains an explicit, target-scoped publication action.
PAGE_DEFINITION_PUBLISH_REQUESTED_EVENT = "page_definition_publish_requested"


async def list_pages(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    route: str | None = None,
) -> tuple[list[PageDefinition], int]:
    """Return ``(pages, total)`` ordered by route."""
    conditions = []
    if route:
        conditions.append(PageDefinition.route == route)

    count_stmt = select(func.count()).select_from(PageDefinition)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(await db.scalar(count_stmt) or 0)

    stmt = select(PageDefinition).order_by(PageDefinition.route.asc())
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    pages = list(result.scalars().all())
    return pages, total


async def get_latest_versions(
    db: AsyncSession, page_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PageDefinitionVersion]:
    """Load one latest version per page with a single query."""
    if not page_ids:
        return {}

    latest = (
        select(
            PageDefinitionVersion.page_id,
            func.max(PageDefinitionVersion.version).label("latest_version"),
        )
        .where(PageDefinitionVersion.page_id.in_(page_ids))
        .group_by(PageDefinitionVersion.page_id)
        .subquery()
    )
    result = await db.execute(
        select(PageDefinitionVersion).join(
            latest,
            (PageDefinitionVersion.page_id == latest.c.page_id)
            & (PageDefinitionVersion.version == latest.c.latest_version),
        )
    )
    return {version.page_id: version for version in result.scalars().all()}


async def _latest_version(
    db: AsyncSession, page: PageDefinition
) -> PageDefinitionVersion | None:
    result = await db.execute(
        select(PageDefinitionVersion)
        .where(PageDefinitionVersion.page_id == page.id)
        .order_by(PageDefinitionVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_page(db: AsyncSession, page_id: uuid.UUID) -> PageDefinition:
    result = await db.execute(
        select(PageDefinition).where(PageDefinition.id == page_id)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page {page_id} not found")
    return page


async def get_page_by_route(db: AsyncSession, route: str) -> PageDefinition:
    result = await db.execute(
        select(PageDefinition).where(PageDefinition.route == route)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise NotFoundError(f"Page for route {route!r} not found")
    return page


async def create_page(
    db: AsyncSession,
    *,
    route: str,
    title_key: str,
    definition: dict,
    edited_by: uuid.UUID,
    plugin_states: dict[str, Any] | None = None,
) -> tuple[PageDefinition, PageDefinitionVersion]:
    """Create a page and its first (draft) version."""
    route = validate_route(route)
    cleaned = validate_definition({**definition, "title_key": title_key})
    if plugin_states is not None:
        validate_plugin_launchers(cleaned, plugin_states)

    existing = await db.scalar(
        select(PageDefinition).where(PageDefinition.route == route)
    )
    if existing is not None:
        raise ConflictError(f"Route {route!r} already exists")

    page = PageDefinition(route=route, title_key=title_key)
    try:
        db.add(page)
        await db.flush()
        version = PageDefinitionVersion(
            page_id=page.id,
            version=1,
            status=PageDefinitionStatus.DRAFT,
            definition=cleaned,
            edited_by=edited_by,
        )
        db.add(version)
        await db.commit()
    except IntegrityError as exc:
        # A concurrent create won the unique ``route`` constraint. Report the
        # same 409 the pre-check produces instead of leaking a 500.
        await db.rollback()
        raise ConflictError(f"Route {route!r} already exists") from exc
    await db.refresh(page)
    await db.refresh(version)
    return page, version


async def update_draft(
    db: AsyncSession,
    *,
    page_id: uuid.UUID,
    base_version: int,
    definition: dict,
    edit_comment: str | None,
    edited_by: uuid.UUID,
    plugin_states: dict[str, Any] | None = None,
) -> tuple[PageDefinition, PageDefinitionVersion]:
    """Apply an optimistic draft edit, creating a new version row.

    Raises :class:`ConflictError` if ``base_version`` does not match the
    current latest version (concurrent edit / stale editor).
    """
    page = await get_page(db, page_id)
    latest = await _latest_version(db, page)

    if latest is None:
        expected = 0
    else:
        expected = latest.version

    if base_version != expected:
        raise ConflictError(
            f"Version conflict: expected base {expected}, got {base_version}",
            details={"expected": expected, "received": base_version},
        )

    if latest is not None and latest.status == PageDefinitionStatus.PUBLISHED:
        # Publishing freezes the latest version; the next edit starts a new
        # draft on top of it (still allowed, but explicit).
        pass

    cleaned = validate_definition(definition)
    if plugin_states is not None:
        validate_plugin_launchers(cleaned, plugin_states)
    version = PageDefinitionVersion(
        page_id=page.id,
        version=expected + 1,
        status=PageDefinitionStatus.DRAFT,
        definition=cleaned,
        edited_by=edited_by,
        edit_comment=edit_comment,
    )
    db.add(version)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Another editor inserted the same (page_id, version) between our read
        # and commit. Re-read the winner and surface the usual 409.
        await db.rollback()
        latest_now = (
            await db.execute(
                select(PageDefinitionVersion)
                .where(PageDefinitionVersion.page_id == page_id)
                .order_by(PageDefinitionVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        actual = latest_now.version if latest_now is not None else 0
        raise ConflictError(
            f"Version conflict: expected base {actual}, got {base_version}",
            details={"expected": actual, "received": base_version},
        ) from exc
    await db.refresh(version)
    await db.refresh(page)
    return page, version


async def preview(
    db: AsyncSession,
    *,
    page_id: uuid.UUID | None,
    route: str | None,
    definition: dict,
    plugin_states: dict[str, Any] | None = None,
) -> dict:
    """Validate a preview definition without persisting anything.

    Returns the cleaned definition plus the version number the next save would
    create. Preview never mutates the page or the public tree; the Admin
    preview panel renders the response directly.
    """
    cleaned = validate_definition(definition)
    if plugin_states is not None:
        validate_plugin_launchers(cleaned, plugin_states)

    version_preview: int = 0
    page: PageDefinition | None = None
    if page_id is not None:
        page = await get_page(db, page_id)
    elif route is not None:
        page = await get_page_by_route(db, route)

    if page is not None:
        latest = await _latest_version(db, page)
        version_preview = (latest.version if latest is not None else 0) + 1

    return {"definition": cleaned, "version_preview": version_preview}


async def get_versions(
    db: AsyncSession, page_id: uuid.UUID
) -> list[PageDefinitionVersion]:
    await get_page(db, page_id)
    result = await db.execute(
        select(PageDefinitionVersion)
        .where(PageDefinitionVersion.page_id == page_id)
        .order_by(PageDefinitionVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_version(
    db: AsyncSession, page_id: uuid.UUID, version_id: uuid.UUID
) -> PageDefinitionVersion:
    await get_page(db, page_id)
    result = await db.execute(
        select(PageDefinitionVersion).where(
            PageDefinitionVersion.id == version_id,
            PageDefinitionVersion.page_id == page_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"Version {version_id} not found for page {page_id}")
    return version


async def publish_request(
    db: AsyncSession,
    *,
    page_id: uuid.UUID,
    version_id: uuid.UUID | None,
    reason: str | None,
    edited_by: uuid.UUID,
    plugin_states: dict[str, Any] | None = None,
) -> tuple[PageDefinition, PageDefinitionVersion, OutboxEvent]:
    """Validate and mark a version ``requested``, emitting a publish event.

    The page builder never mutates public files: it emits a typed task event
    consumed by the dedicated lifecycle worker. Static multi-target deployment
    remains a separate explicit workflow. Returns ``(page, version, event)``.
    """
    page = await get_page(db, page_id)

    # Lock the row before deciding the transition. Without this, a concurrent
    # ``publish_now`` (or the publication worker) can publish the version
    # between our read and commit, and we would write PUBLISHED back to
    # REQUESTED. ``populate_existing`` forces a fresh read past the identity map.
    statement = select(PageDefinitionVersion).where(
        PageDefinitionVersion.page_id == page_id
    )
    if version_id is not None:
        statement = statement.where(PageDefinitionVersion.id == version_id)
    else:
        statement = statement.order_by(PageDefinitionVersion.version.desc()).limit(1)
    version = (
        await db.execute(
            statement.with_for_update(of=PageDefinitionVersion).execution_options(
                populate_existing=True
            )
        )
    ).scalar_one_or_none()

    if version is None:
        if version_id is not None:
            raise NotFoundError(f"Version {version_id} not found for page {page_id}")
        raise NotFoundError(f"Page {page_id} has no versions")

    if version.status == PageDefinitionStatus.PUBLISHED:
        raise ConflictError(f"Version {version.version} is already published")

    # Re-validate the stored definition (defence in depth — a definition can
    # never reach ``requested`` without passing the registry).
    cleaned = validate_definition(version.definition)
    if plugin_states is not None:
        validate_plugin_launchers(cleaned, plugin_states)
    version.definition = cleaned
    version.status = PageDefinitionStatus.REQUESTED
    version.edit_comment = version.edit_comment or reason

    event = await enqueue_task_event(
        db,
        aggregate_type="page_definition",
        aggregate_id=str(page.id),
        event_type=PAGE_DEFINITION_PUBLISH_REQUESTED_EVENT,
        task_name=PAGE_BUILDER_PUBLISH_TASK,
        kwargs={
            "page_id": str(page.id),
            "version_id": str(version.id),
        },
        metadata={
            "requested_by": str(edited_by),
            "reason": reason,
            "route": page.route,
            "version": version.version,
        },
    )
    await db.commit()
    await db.refresh(version)
    await db.refresh(page)
    return page, version, event


async def publish_version(db: AsyncSession, version: PageDefinitionVersion) -> None:
    """Mark a version published (called by the publication pipeline)."""
    version.status = PageDefinitionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    await db.commit()


async def publish_now(
    db: AsyncSession,
    *,
    page_id: uuid.UUID,
    version_id: uuid.UUID | None,
    reason: str | None,
    edited_by: uuid.UUID,
    plugin_states: dict[str, Any] | None = None,
) -> tuple[PageDefinition, PageDefinitionVersion]:
    """Validate and publish a version immediately, within the admin request.

    The row lock keeps this idempotent against a concurrent worker
    ``publish_definition`` for the same version: exactly one transition wins.
    """
    page = await get_page(db, page_id)
    statement = select(PageDefinitionVersion).where(
        PageDefinitionVersion.page_id == page_id
    )
    if version_id is not None:
        statement = statement.where(PageDefinitionVersion.id == version_id)
    else:
        statement = statement.order_by(PageDefinitionVersion.version.desc())
    version = (
        await db.execute(
            statement.limit(1).with_for_update(of=PageDefinitionVersion)
        )
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"Page {page_id} has no versions")

    if version.status == PageDefinitionStatus.PUBLISHED:
        raise ConflictError(f"Version {version.version} is already published")

    cleaned = validate_definition(version.definition)
    if plugin_states is not None:
        validate_plugin_launchers(cleaned, plugin_states)
    version.definition = cleaned
    version.status = PageDefinitionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)
    version.edit_comment = version.edit_comment or reason
    await db.commit()
    await db.refresh(version)
    await db.refresh(page)
    return page, version


async def get_published(
    db: AsyncSession, *, page_id: uuid.UUID | None = None, route: str | None = None
) -> PageDefinitionVersion | None:
    """Return the latest published version for a page (by id or route)."""
    if page_id is None and route is None:
        raise ValidationError("page_id or route is required")
    if page_id is not None:
        page = await get_page(db, page_id)
    else:
        page = await get_page_by_route(db, route)  # type: ignore[arg-type]
    if page_id is None:
        page_id = page.id
    result = await db.execute(
        select(PageDefinitionVersion)
        .where(
            PageDefinitionVersion.page_id == page_id,
            PageDefinitionVersion.status == PageDefinitionStatus.PUBLISHED,
        )
        .order_by(PageDefinitionVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


__all__ = [
    "PAGE_DEFINITION_PUBLISH_REQUESTED_EVENT",
    "create_page",
    "get_latest_versions",
    "get_page",
    "get_page_by_route",
    "get_published",
    "get_version",
    "get_versions",
    "list_pages",
    "preview",
    "publish_request",
    "publish_version",
    "update_draft",
]

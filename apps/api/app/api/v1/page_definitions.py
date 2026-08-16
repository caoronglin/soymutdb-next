"""Public (unauthenticated) read endpoint for published page definitions.

Serves the latest ``published`` definition for a route, optionally pinned to
a specific immutable version id.  This is the read-contract shared by the
public Web renderer and the SSG publication pipeline; it never exposes draft
or preview versions.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...models.page_builder import PageDefinitionStatus, PageDefinitionVersion
from ...page_builder import service as page_service
from ...page_builder.schemas import (
    PageDefinitionStatusEnum,
    PageDefinitionVersionResponse,
)

router = APIRouter(prefix="/page-definitions", tags=["page-definitions"])


def _version_to_response(
    v: PageDefinitionVersion,
) -> PageDefinitionVersionResponse:
    return PageDefinitionVersionResponse(
        id=v.id,
        page_id=v.page_id,
        version=v.version,
        status=PageDefinitionStatusEnum(v.status),
        definition=v.definition,
        edited_by=v.edited_by,
        edit_comment=v.edit_comment,
        published_at=v.published_at,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


@router.get("/{route:path}", response_model=PageDefinitionVersionResponse)
async def get_page_definition(
    route: str,
    version: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> PageDefinitionVersionResponse:
    """Return a published definition for *route* (optionally pinned version)."""
    # Normalise the leading slash (APIRouter strips it for ``{route:path}``).
    norm_route = route if route.startswith("/") else f"/{route}"

    if version is not None:
        # A pinned version must belong to the route's page and be published.
        page = await page_service.get_page_by_route(db, norm_route)
        result = await db.execute(
            select(PageDefinitionVersion).where(
                PageDefinitionVersion.id == version,
                PageDefinitionVersion.page_id == page.id,
                PageDefinitionVersion.status == PageDefinitionStatus.PUBLISHED,
            )
        )
        published = result.scalar_one_or_none()
        if published is None:
            raise NotFoundError(
                f"Published version {version} not found for route {norm_route!r}"
            )
        return _version_to_response(published)

    published = await page_service.get_published(db, route=norm_route)
    if published is None:
        raise NotFoundError(
            f"No published definition for route {norm_route!r}"
        )
    return _version_to_response(published)


__all__ = ["router"]

"""Public (unauthenticated) read endpoint for published page definitions.

Serves the latest ``published`` definition for a route, optionally pinned to
a specific immutable version id.  This is the read-contract shared by the
public Web renderer and the SSG publication pipeline; it never exposes draft
or preview versions.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import NotFoundError
from ...core.features import FeatureFlagService
from ...models.page_builder import (
    PageDefinition,
    PageDefinitionStatus,
    PageDefinitionVersion,
)
from ...page_builder import service as page_service
from ...page_builder.schemas import (
    PageDefinitionStatusEnum,
    PublicPageDefinitionResponse,
    PublishedPageDefinitionRoute,
)

router = APIRouter(prefix="/page-definitions", tags=["page-definitions"])


def _version_to_public_response(
    route: str,
    v: PageDefinitionVersion,
) -> PublicPageDefinitionResponse:
    return PublicPageDefinitionResponse(
        route=route,
        version=v.version,
        status=PageDefinitionStatusEnum(v.status),
        definition=v.definition,
    )


_SSG_ROUTE_RE = re.compile(r"^/(?:[A-Za-z0-9][A-Za-z0-9-]*/)*[A-Za-z0-9][A-Za-z0-9-]*$")


def _is_ssg_route(route: str) -> bool:
    """Match exactly the route grammar accepted by the Web SSG writer."""
    return route == "/" or bool(_SSG_ROUTE_RE.fullmatch(route))


@router.get("/published-routes", response_model=list[PublishedPageDefinitionRoute])
async def get_published_routes(
    db: AsyncSession = Depends(get_db),
) -> list[PublishedPageDefinitionRoute]:
    """Return only published, SSG-safe routes with their minimal public payload."""
    if not await FeatureFlagService.is_enabled(db, "page_builder"):
        raise NotFoundError("Published page definitions are currently disabled")

    result = await db.execute(
        select(PageDefinition, PageDefinitionVersion)
        .join(PageDefinitionVersion, PageDefinitionVersion.page_id == PageDefinition.id)
        .where(PageDefinitionVersion.status == PageDefinitionStatus.PUBLISHED)
        .order_by(PageDefinition.route.asc(), PageDefinitionVersion.version.desc())
    )
    routes: list[PublishedPageDefinitionRoute] = []
    seen_routes: set[str] = set()
    for page, version in result.all():
        # A page may retain historical published versions; expose its newest only.
        if page.route in seen_routes or not _is_ssg_route(page.route):
            continue
        seen_routes.add(page.route)
        routes.append(
            PublishedPageDefinitionRoute(
                route=page.route,
                version=version.version,
                status=PageDefinitionStatusEnum.PUBLISHED,
                definition=version.definition,
            )
        )
    return routes


@router.get("/{route:path}", response_model=PublicPageDefinitionResponse)
async def get_page_definition(
    route: str,
    version: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> PublicPageDefinitionResponse:
    """Return a published definition for *route* (optionally pinned version)."""
    # Normalise the leading slash (APIRouter strips it for ``{route:path}``).
    norm_route = route if route.startswith("/") else f"/{route}"
    if not await FeatureFlagService.is_enabled(db, "page_builder"):
        raise NotFoundError("Published page definitions are currently disabled")

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
        return _version_to_public_response(norm_route, published)

    published = await page_service.get_published(db, route=norm_route)
    if published is None:
        raise NotFoundError(
            f"No published definition for route {norm_route!r}"
        )
    return _version_to_public_response(norm_route, published)


__all__ = ["router"]

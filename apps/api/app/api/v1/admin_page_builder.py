"""Admin Page Builder endpoints (administrator-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.plugins import get_plugin_registry
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.page_builder import PageDefinitionVersion
from ...page_builder import COMPONENT_REGISTRY
from ...page_builder import service as page_service
from ...page_builder.schemas import (
    ComponentDescriptor,
    PageDefinitionCreate,
    PageDefinitionListResponse,
    PageDefinitionResponse,
    PageDefinitionStatusEnum,
    PageDefinitionSummary,
    PageDefinitionUpdate,
    PageDefinitionVersionResponse,
    PreviewRequest,
    PreviewResponse,
    PublishRequest,
    PublishRequestResponse,
    RegistryResponse,
)
from ...services.plugin_service import PluginService
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/page-builder", tags=["admin-page-builder"])


def _require_admin(user: User) -> None:
    """Raise unless the user holds the administrator role."""
    if not has_role(get_user_roles(user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _version_to_response(v: PageDefinitionVersion) -> PageDefinitionVersionResponse:
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


def _summary(page, version: PageDefinitionVersion | None) -> PageDefinitionSummary:
    return PageDefinitionSummary(
        id=page.id,
        route=page.route,
        title_key=page.title_key,
        latest_version=version.version if version else 0,
        latest_status=(
            PageDefinitionStatusEnum(version.status) if version else PageDefinitionStatusEnum.DRAFT
        ),
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.get("/registry", response_model=RegistryResponse)
async def get_registry(
    current_user: User = Depends(get_current_user),
) -> RegistryResponse:
    """Expose the server-owned component registry to the Admin editor."""
    _require_admin(current_user)
    components = [
        ComponentDescriptor(
            renderer_key=entry.renderer_key,
            label=entry.label,
            config_schema=entry.config_schema,
            allowed_children=sorted(entry.allowed_children),
        )
        for entry in COMPONENT_REGISTRY.values()
    ]
    return RegistryResponse(components=components)


@router.get("/pages", response_model=PageDefinitionListResponse)
async def list_pages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    route: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageDefinitionListResponse:
    _require_admin(current_user)

    pages, total = await page_service.list_pages(
        db, page=page, page_size=page_size, route=route
    )
    items: list[PageDefinitionSummary] = []
    for p in pages:
        versions = await page_service.get_versions(db, p.id)
        latest = versions[0] if versions else None
        items.append(_summary(p, latest))
    return PageDefinitionListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.post(
    "/pages",
    response_model=PageDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_page(
    payload: PageDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageDefinitionResponse:
    _require_admin(current_user)
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())

    page, version = await page_service.create_page(
        db,
        route=payload.route,
        title_key=payload.title_key,
        definition=payload.definition,
        edited_by=current_user.id,
        plugin_states=plugin_states,
    )
    return PageDefinitionResponse(
        id=page.id,
        route=page.route,
        title_key=page.title_key,
        versions=[_version_to_response(version)],
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.get("/pages/{page_id}", response_model=PageDefinitionResponse)
async def get_page(
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageDefinitionResponse:
    _require_admin(current_user)

    page = await page_service.get_page(db, page_id)
    versions = await page_service.get_versions(db, page_id)
    return PageDefinitionResponse(
        id=page.id,
        route=page.route,
        title_key=page.title_key,
        versions=[_version_to_response(v) for v in versions],
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.put("/pages/{page_id}/draft", response_model=PageDefinitionVersionResponse)
async def update_draft(
    page_id: uuid.UUID,
    payload: PageDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageDefinitionVersionResponse:
    _require_admin(current_user)
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())

    _page, version = await page_service.update_draft(
        db,
        page_id=page_id,
        base_version=payload.base_version,
        definition=payload.definition,
        edit_comment=payload.edit_comment,
        edited_by=current_user.id,
        plugin_states=plugin_states,
    )
    return _version_to_response(version)


@router.post("/pages/{page_id}/preview", response_model=PreviewResponse)
async def preview_page(
    page_id: uuid.UUID,
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PreviewResponse:
    _require_admin(current_user)
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())

    result = await page_service.preview(
        db,
        page_id=page_id,
        route=None,
        definition=payload.definition,
        plugin_states=plugin_states,
    )
    return PreviewResponse(
        definition=result["definition"], version_preview=result["version_preview"]
    )


@router.get(
    "/pages/{page_id}/versions",
    response_model=list[PageDefinitionVersionResponse],
)
async def list_versions(
    page_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PageDefinitionVersionResponse]:
    _require_admin(current_user)

    versions = await page_service.get_versions(db, page_id)
    return [_version_to_response(v) for v in versions]


@router.post(
    "/pages/{page_id}/publish-request",
    response_model=PublishRequestResponse,
)
async def publish_request(
    page_id: uuid.UUID,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishRequestResponse:
    _require_admin(current_user)
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())

    _page, version, event = await page_service.publish_request(
        db,
        page_id=page_id,
        version_id=payload.version_id,
        reason=payload.reason,
        edited_by=current_user.id,
        plugin_states=plugin_states,
    )
    return PublishRequestResponse(
        page_id=page_id,
        version_id=version.id,
        version=version.version,
        status=PageDefinitionStatusEnum(version.status),
        event_id=str(event.event_id) if event else None,
    )


__all__ = ["router"]

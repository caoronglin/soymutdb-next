"""Admin Page Builder endpoints (administrator-only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.plugins import get_plugin_registry
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.page_builder import PageDefinitionVersion, PageTemplate
from ...page_builder import COMPONENT_REGISTRY
from ...page_builder import service as page_service
from ...page_builder.registry import _LAYOUT_CONTAINERS, validate_definition
from ...page_builder.schemas import (
    ComponentDescriptor,
    PageDefinitionCreate,
    PageDefinitionListResponse,
    PageDefinitionResponse,
    PageDefinitionStatusEnum,
    PageDefinitionSummary,
    PageDefinitionUpdate,
    PageDefinitionVersionResponse,
    PageTemplateCreate,
    PageTemplateListResponse,
    PageTemplateResponse,
    PageTemplateUpdate,
    PageTemplateValidationResponse,
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
            is_layout_container=entry.renderer_key in _LAYOUT_CONTAINERS,
        )
        for entry in COMPONENT_REGISTRY.values()
    ]
    return RegistryResponse(components=components)


def _template_response(template: PageTemplate) -> PageTemplateResponse:
    return PageTemplateResponse(
        id=template.id,
        key=template.key,
        label=template.label,
        description=template.description,
        category=template.category,
        definition=template.definition,
        preview_image_id=template.preview_image_id,
        builtin=template.builtin,
        sort_order=template.sort_order,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


async def _get_template(db: AsyncSession, key: str) -> PageTemplate:
    template = await db.scalar(select(PageTemplate).where(PageTemplate.key == key))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.get("/templates", response_model=PageTemplateListResponse)
async def list_templates(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> PageTemplateListResponse:
    _require_admin(current_user)
    items = (
        await db.scalars(
            select(PageTemplate).order_by(
                PageTemplate.category, PageTemplate.sort_order, PageTemplate.key
            )
        )
    ).all()
    return PageTemplateListResponse(
        items=[_template_response(item) for item in items], total=len(items)
    )


@router.get("/templates/{key}", response_model=PageTemplateResponse)
async def get_template(
    key: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> PageTemplateResponse:
    _require_admin(current_user)
    return _template_response(await _get_template(db, key))


@router.post("/templates", response_model=PageTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: PageTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageTemplateResponse:
    _require_admin(current_user)
    if await db.scalar(select(PageTemplate.id).where(PageTemplate.key == payload.key)):
        raise HTTPException(status_code=409, detail="Template key already exists")
    template = PageTemplate(
        **payload.model_dump(exclude={"definition"}),
        definition=validate_definition(payload.definition),
    )
    db.add(template)
    await db.flush()
    return _template_response(template)


@router.put("/templates/{key}", response_model=PageTemplateResponse)
async def update_template(
    key: str,
    payload: PageTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageTemplateResponse:
    _require_admin(current_user)
    template = await _get_template(db, key)
    if template.builtin:
        raise HTTPException(status_code=403, detail="Builtin templates are read-only")
    values = payload.model_dump(exclude_unset=True)
    if "definition" in values and values["definition"] is not None:
        values["definition"] = validate_definition(values["definition"])
    for field, value in values.items():
        setattr(template, field, value)
    await db.flush()
    await db.refresh(template)
    return _template_response(template)


@router.delete("/templates/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    key: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> None:
    _require_admin(current_user)
    template = await _get_template(db, key)
    if template.builtin:
        raise HTTPException(status_code=403, detail="Builtin templates cannot be deleted")
    await db.delete(template)


@router.post("/templates/{key}/validate", response_model=PageTemplateValidationResponse)
async def validate_template(
    key: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> PageTemplateValidationResponse:
    _require_admin(current_user)
    template = await _get_template(db, key)
    cleaned = validate_definition(template.definition)
    return PageTemplateValidationResponse(definition=cleaned)


@router.get("/pages", response_model=PageDefinitionListResponse)
async def list_pages(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    route: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PageDefinitionListResponse:
    _require_admin(current_user)

    pages, total = await page_service.list_pages(db, page=page, page_size=page_size, route=route)
    latest_by_page = await page_service.get_latest_versions(db, [p.id for p in pages])
    items = [_summary(p, latest_by_page.get(p.id)) for p in pages]
    return PageDefinitionListResponse(items=items, total=total, page=page, page_size=page_size)


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


@router.post("/pages/{page_id}/publish", response_model=PublishRequestResponse)
async def publish_now(
    page_id: uuid.UUID,
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishRequestResponse:
    """Publish a version immediately without the asynchronous task round-trip."""
    _require_admin(current_user)
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())
    _page, version = await page_service.publish_now(
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
        event_id=None,
    )


__all__ = ["router"]

"""Admin CRUD for table-view templates and the species instance registry.

Two operators' needs, one console:

* **Table templates** — author the ordered column set a portal table renders.
  A template is scoped by species, site variant and (optionally) release, so a
  multi-species, multi-server deployment keeps each instance's layout apart
  while a single admin console edits all of them.
* **Species instances** — the registry of deployed species databases (their
  API/JBrowse/portal origins). Exactly one row is the local instance; the rest
  are the peers the console may point at.

Every mutation writes an audit log; nothing here can alter biological records.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.table_views import SpeciesInstance, TableViewTemplate
from ...schemas.table_views import (
    ConnectionState,
    SpeciesInstanceCreate,
    SpeciesInstanceHealthResponse,
    SpeciesInstanceListResponse,
    SpeciesInstanceResponse,
    SpeciesInstanceUpdate,
    TableActions,
    TableViewTemplateCreate,
    TableViewTemplateListResponse,
    TableViewTemplateResponse,
    TableViewTemplateUpdate,
)
from ...services import table_views_service as service
from ...services.species_instance_health_service import (
    check_species_instance_health,
    is_instance_health_stale,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/table-views", tags=["admin-table-views"])

#: The literal members `ConnectionState` admits. Enumerated here so the row's
#: free-form text column can be validated before it reaches the response model:
#: `ConnectionState` is a `Literal` alias and therefore not callable.
_CONNECTION_STATES: frozenset[str] = frozenset(
    {"unknown", "healthy", "unhealthy", "disabled", "unconfigured"}
)


def _connection_state(value: str) -> ConnectionState:
    """Narrow a stored connection-state string to the published vocabulary."""
    if value not in _CONNECTION_STATES:
        raise ValueError(f"unknown species-instance connection state: {value!r}")
    return cast(ConnectionState, value)




def _require_admin(user: User) -> None:
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _to_response(template: TableViewTemplate) -> TableViewTemplateResponse:
    return TableViewTemplateResponse(
        id=template.id,
        kind=template.kind,
        name=template.name,
        species=template.species,
        site_variant=template.site_variant,  # type: ignore[arg-type]
        release_id=template.release_id,
        is_default=template.is_default,
        columns=template.columns or [],
        # `actions` is stored as free-form JSON, so validate it into the
        # response model rather than passing a bare mapping through.
        actions=TableActions.model_validate(template.actions or {}),
        notes=template.notes,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.get("", response_model=TableViewTemplateListResponse)
async def list_table_view_templates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    kind: str | None = Query(default=None),
    species: str | None = Query(default=None),
) -> TableViewTemplateListResponse:
    _require_admin(current_user)
    items = await service.list_templates(db, kind=kind, species=species)  # type: ignore[arg-type]
    return TableViewTemplateListResponse(
        items=[_to_response(item) for item in items], total=len(items)
    )


@router.post(
    "", response_model=TableViewTemplateResponse, status_code=status.HTTP_201_CREATED
)
async def create_table_view_template(
    payload: TableViewTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TableViewTemplateResponse:
    _require_admin(current_user)
    template = await service.create_template(db, payload)
    return _to_response(template)


@router.put("/{template_id}", response_model=TableViewTemplateResponse)
async def update_table_view_template(
    template_id: int,
    payload: TableViewTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TableViewTemplateResponse:
    _require_admin(current_user)
    template = await service.update_template(db, template_id, payload)
    return _to_response(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table_view_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _require_admin(current_user)
    await service.delete_template(db, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


species_router = APIRouter(
    prefix="/admin/species-instances", tags=["admin-species-instances"]
)


def _to_instance_response(instance: SpeciesInstance) -> SpeciesInstanceResponse:
    return SpeciesInstanceResponse(
        id=instance.id,
        code=instance.code,
        name=instance.name,
        species=instance.species,
        api_base_url=instance.api_base_url,
        jbrowse_base_url=instance.jbrowse_base_url,
        portal_base_url=instance.portal_base_url,
        site_url=instance.portal_base_url,
        is_enabled=instance.is_enabled,
        is_local=instance.is_local,
        notes=instance.notes,
        connection_state=_connection_state(
            "disabled" if not instance.is_enabled else instance.connection_state
        ),
        last_checked_at=instance.last_checked_at,
        last_error_at=instance.last_error_at,
        is_stale=is_instance_health_stale(instance),
        remote_management="local" if instance.is_local else "registration_only",
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


@species_router.get("", response_model=SpeciesInstanceListResponse)
async def list_species_instances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpeciesInstanceListResponse:
    _require_admin(current_user)
    items = await service.list_species_instances(db)
    return SpeciesInstanceListResponse(
        items=[_to_instance_response(item) for item in items], total=len(items)
    )


@species_router.post(
    "", response_model=SpeciesInstanceResponse, status_code=status.HTTP_201_CREATED
)
async def create_species_instance(
    payload: SpeciesInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpeciesInstanceResponse:
    _require_admin(current_user)
    instance = await service.create_species_instance(db, payload)
    return _to_instance_response(instance)


@species_router.put("/{instance_id}", response_model=SpeciesInstanceResponse)
async def update_species_instance(
    instance_id: int,
    payload: SpeciesInstanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpeciesInstanceResponse:
    _require_admin(current_user)
    instance = await service.update_species_instance(db, instance_id, payload)
    return _to_instance_response(instance)


@species_router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_species_instance(
    instance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _require_admin(current_user)
    await service.delete_species_instance(db, instance_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@species_router.get("/{instance_id}/health", response_model=SpeciesInstanceHealthResponse)
async def get_species_instance_health(
    instance_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpeciesInstanceHealthResponse:
    """Probe the instance liveness endpoint only when deployment trust allows it."""
    _require_admin(current_user)
    return await check_species_instance_health(
        db,
        instance_id=instance_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


__all__ = ["router", "species_router"]

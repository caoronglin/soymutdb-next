"""Administrator CRUD for saved multi-view data configurations.

The console stores how an operator wants to read one release-scoped source
(genes, variants or mutant lines). The data itself is still fetched through
the public read APIs, so these endpoints cannot expose unreleased records or
internal identifiers; they only persist presentation choices.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.data_views import AdminDataView
from ...schemas.data_views import (
    AdminDataViewCreate,
    AdminDataViewListResponse,
    AdminDataViewResponse,
    AdminDataViewUpdate,
    DataViewSource,
    DataViewSourceListResponse,
)
from ...services import data_views_service as service
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/data-views", tags=["admin-data-views"])


def _require_admin(user: User) -> None:
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _to_response(view: AdminDataView) -> AdminDataViewResponse:
    return AdminDataViewResponse(
        id=view.id,
        name=view.name,
        source=view.source,  # type: ignore[arg-type]
        view_type=view.view_type,  # type: ignore[arg-type]
        visible_fields=view.visible_fields or [],
        searchable_fields=view.searchable_fields or [],
        filters=view.filters or {},
        sort_field=view.sort_field,
        sort_dir=view.sort_dir,  # type: ignore[arg-type]
        group_field=view.group_field,
        title_field=view.title_field,
        page_size=view.page_size,
        is_default=view.is_default,
        notes=view.notes,
        visibility=view.visibility,  # type: ignore[arg-type]
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


@router.get("/sources", response_model=DataViewSourceListResponse)
async def list_data_view_sources(
    current_user: User = Depends(get_current_user),
) -> DataViewSourceListResponse:
    _require_admin(current_user)
    return DataViewSourceListResponse(items=service.source_catalog())


@router.get("", response_model=AdminDataViewListResponse)
async def list_data_views(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    source: DataViewSource | None = Query(default=None),
    include_hidden: bool = Query(
        default=False,
        description=(
            "Include views whose visibility is 'hidden'. Hidden views are kept "
            "and stay readable by id; they are only withheld from this list."
        ),
    ),
) -> AdminDataViewListResponse:
    _require_admin(current_user)
    items = await service.list_views(db, source=source, include_hidden=include_hidden)
    return AdminDataViewListResponse(items=[_to_response(item) for item in items], total=len(items))


@router.post("", response_model=AdminDataViewResponse, status_code=status.HTTP_201_CREATED)
async def create_data_view(
    payload: AdminDataViewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminDataViewResponse:
    _require_admin(current_user)
    view = await service.create_view(db, payload)
    return _to_response(view)


@router.put("/{view_id}", response_model=AdminDataViewResponse)
async def update_data_view(
    view_id: int,
    payload: AdminDataViewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminDataViewResponse:
    _require_admin(current_user)
    view = await service.update_view(db, view_id, payload)
    return _to_response(view)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_view(
    view_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    _require_admin(current_user)
    await service.delete_view(db, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]

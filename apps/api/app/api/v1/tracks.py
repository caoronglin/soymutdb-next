"""Track endpoints: list, detail, signed-URL (RBAC-enforced), JBrowse config."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.content import SignedUrlResponse
from ...services.track_service import TrackService
from .deps import get_current_user, get_optional_user, get_user_roles, require_role

router = APIRouter(prefix="/tracks", tags=["tracks"])
service = TrackService()


@router.get("", response_model=list[dict[str, Any]])
async def list_tracks(
    db: AsyncSession = Depends(get_db),
    assembly_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
) -> list[dict[str, Any]]:
    """List tracks (optionally filtered by assembly / category)."""
    return await service.list_tracks(
        db,
        assembly_id=assembly_id,
        category_id=category_id,
        user_id=current_user.id if current_user else None,
        user_roles=get_user_roles(current_user) if current_user else [],
    )


@router.get("/categories", response_model=list[dict[str, Any]])
async def list_track_categories(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List track categories."""
    return await service.list_categories(db)


@router.get("/jbrowse-config", response_model=dict[str, Any])
async def get_jbrowse_config(
    assembly: str = Query(default="Wm82v4.0", description="Assembly name"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Return JBrowse 2 configuration (assembly + tracks) for the standalone browser.

    Queries the database for tracks belonging to the requested assembly and
    converts them to JBrowse track format. If no tracks are found or the
    database is empty, an empty tracks array is returned — the frontend
    JBrowse app has built-in default tracks as a fallback.
    """
    return await service.get_jbrowse_config(
        db,
        assembly_name=assembly,
        user_id=current_user.id if current_user else None,
        user_roles=get_user_roles(current_user) if current_user else [],
    )


@router.get("/{track_id}", response_model=dict[str, Any])
async def get_track(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Get track detail."""
    return await service.get_track(
        db,
        track_id,
        user_id=current_user.id if current_user else None,
        user_roles=get_user_roles(current_user) if current_user else [],
    )


@router.get(
    "/{track_id}/signed-url",
    response_model=SignedUrlResponse,
    dependencies=[Depends(require_role(RoleName.VIEWER))],
)
async def get_signed_url(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SignedUrlResponse:
    """Get a signed URL for a track file (RBAC-enforced).

    Public tracks are accessible to any authenticated user.
    Private/project tracks require ownership, ``track_manager``, or
    ``administrator`` role.
    """
    user_roles = get_user_roles(current_user)
    return await service.get_signed_url(
        db,
        track_id=track_id,
        user_id=current_user.id,
        user_roles=user_roles,
    )

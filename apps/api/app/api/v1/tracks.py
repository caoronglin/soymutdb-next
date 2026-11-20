"""Track endpoints: list, detail, signed-URL (RBAC-enforced), JBrowse config."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.content import SignedUrlResponse
from ...services.release_context import ReleaseContext, get_release_context
from ...services.track_service import TrackService
from .deps import get_current_user, get_optional_user, get_user_roles, require_role

router = APIRouter(prefix="/tracks", tags=["tracks"])
service = TrackService()


def _cache_policy(response: Response, *, authenticated: bool) -> None:
    """Apply the cache boundary for an Authorization-varying track response.

    Track payloads include owner/visibility metadata and (in the signed-URL
    case) bearer-equivalent pre-signed object URLs. A shared cache must never
    serve one caller's projection to another, so the response always varies on
    Authorization; only the anonymous public projection may be shared.
    """
    response.headers["Vary"] = "Authorization"
    response.headers["Cache-Control"] = (
        "private, no-store"
        if authenticated
        else "public, max-age=60, stale-while-revalidate=300"
    )


@router.get("", response_model=list[dict[str, Any]])
async def list_tracks(
    response: Response,
    db: AsyncSession = Depends(get_db),
    assembly_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User | None = Depends(get_optional_user),
) -> list[dict[str, Any]]:
    """List the selected release's tracks (optionally filtered by assembly/category)."""
    _cache_policy(response, authenticated=current_user is not None)
    return await service.list_tracks(
        db,
        assembly_id=assembly_id,
        category_id=category_id,
        release_id=release_context.release_id,
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
    response: Response,
    assembly_id: int = Query(
        ...,
        ge=1,
        description="Explicit assembly identity scoped to the selected release",
    ),
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Return a release- and assembly-scoped JBrowse 2 configuration.

    The release dependency accepts only a published release (or the active
    published pointer).  ``assembly_id`` is intentionally required: an
    assembly name is not a stable identity across release namespaces and must
    never be used to select tracks.  Anonymous responses contain public tracks
    only and may be shared; authenticated responses can include project/private
    tracks and are therefore marked private and non-cacheable.
    """
    config = await service.get_jbrowse_config(
        db,
        assembly_id=assembly_id,
        release_context=release_context,
        user_id=current_user.id if current_user else None,
        user_roles=get_user_roles(current_user) if current_user else [],
    )

    _cache_policy(response, authenticated=current_user is not None)
    return config


@router.get("/{track_id}", response_model=dict[str, Any])
async def get_track(
    track_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Get track detail scoped to the selected release."""
    _cache_policy(response, authenticated=current_user is not None)
    return await service.get_track(
        db,
        track_id,
        release_id=release_context.release_id,
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
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SignedUrlResponse:
    """Get a signed URL for a track file (RBAC-enforced).

    Public tracks are accessible to any authenticated user.
    Private/project tracks require ownership, ``track_manager``, or
    ``administrator`` role.

    The URL is a capability: it is always returned ``private, no-store`` so no
    browser or proxy retains it.
    """
    _cache_policy(response, authenticated=True)
    user_roles = get_user_roles(current_user)
    return await service.get_signed_url(
        db,
        track_id=track_id,
        user_id=current_user.id,
        user_roles=user_roles,
    )

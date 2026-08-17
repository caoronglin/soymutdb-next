"""Admin endpoints for immutable static publication (Phase 3).

- list configured targets (redacted; no credentials)
- request a publication (allocates target-scoped monotonic id, enqueues build)
- inspect publication evidence
- request rollback

Credentials are NEVER returned here — see
``app.services.publication_targets.redacted_targets``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.features import FeatureFlagService
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.publication import StaticPublication
from ...schemas.publication import (
    PublicationListResponse,
    PublicationRequest,
    PublicationResponse,
    PublicationRollbackRequest,
    PublicationTargetListResponse,
    PublicationTargetResponse,
)
from ...services.publication_service import (
    PublicationError,
    request_publication,
    rollback,
)
from ...services.publication_targets import redacted_targets
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/publication", tags=["admin-publication"])


def _require_admin(user: User) -> None:
    if not has_role(get_user_roles(user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


@router.get("/targets", response_model=PublicationTargetListResponse)
async def list_targets(
    current_user: User = Depends(get_current_user),
) -> PublicationTargetListResponse:
    """List configured publication targets (credentials redacted)."""
    _require_admin(current_user)
    return PublicationTargetListResponse(
        items=[
            PublicationTargetResponse(**t) for t in redacted_targets()
        ]
    )


@router.post(
    "/request",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request(
    payload: PublicationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationResponse:
    """Allocate a publication request for a target and enqueue the build."""
    _require_admin(current_user)
    target_key = getattr(payload.target, "value", payload.target)
    if target_key == "github_pages" and not await FeatureFlagService.is_enabled(db, "publication.github_pages"):
        raise HTTPException(status_code=503, detail="GitHub Pages publication is disabled")
    if target_key == "cloudflare_pages" and not await FeatureFlagService.is_enabled(db, "publication.cloudflare_pages"):
        raise HTTPException(status_code=503, detail="Cloudflare Pages publication is disabled")
    try:
        pub = await request_publication(
            db,
            target=payload.target,
            release_id=payload.release_id,
            actor_id=str(current_user.id),
            page_definition_version=payload.page_definition_version,
        )
    except PublicationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(pub)
    return PublicationResponse.model_validate(pub)


@router.get("", response_model=PublicationListResponse)
async def list_publications_admin(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    target: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> PublicationListResponse:
    """List publications (most recent first), optionally filtered by target."""
    _require_admin(current_user)
    conditions = []
    if target:
        conditions.append(StaticPublication.target == target)
    count_stmt = select(func.count()).select_from(StaticPublication)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(await db.scalar(count_stmt) or 0)

    stmt = select(StaticPublication).order_by(StaticPublication.publication_id.desc())
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return PublicationListResponse(
        items=[PublicationResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{publication_id}", response_model=PublicationResponse)
async def get_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationResponse:
    """Inspect a single publication's evidence."""
    _require_admin(current_user)
    pub = (
        await db.execute(
            select(StaticPublication).where(StaticPublication.id == publication_id)
        )
    ).scalar_one_or_none()
    if pub is None:
        raise HTTPException(status_code=404, detail="publication not found")
    return PublicationResponse.model_validate(pub)


@router.post("/{publication_id}/rollback", response_model=PublicationResponse)
async def rollback_publication(
    publication_id: int,
    payload: PublicationRollbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationResponse:
    """Roll back a published publication, restoring the previous one."""
    _require_admin(current_user)
    try:
        pub = await rollback(
            db,
            publication_id,
            actor_id=str(current_user.id),
            reason=payload.reason,
        )
    except PublicationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(pub)
    return PublicationResponse.model_validate(pub)

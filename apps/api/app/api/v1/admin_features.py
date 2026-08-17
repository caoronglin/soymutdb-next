"""Admin feature flag management."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.features import FEATURES, FeatureFlagService
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...schemas.features import (
    AdminFeaturesResponse,
    FeatureDefinitionResponse,
    FeatureUpdateRequest,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/features", tags=["admin-features"])


def _require_admin(user: User) -> None:
    from ...core.exceptions import AuthorizationError

    if not has_role(get_user_roles(user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


@router.get("", response_model=AdminFeaturesResponse)
async def list_features(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminFeaturesResponse:
    _require_admin(current_user)
    enabled = await FeatureFlagService.snapshot(db)
    return AdminFeaturesResponse(
        features=[
            FeatureDefinitionResponse(
                key=definition.key,
                enabled=enabled[definition.key],
                default=definition.default,
                public=definition.public,
                description=definition.description,
                disable_behavior=definition.disable_behavior,
            )
            for definition in FEATURES.values()
        ]
    )


@router.put("", response_model=AdminFeaturesResponse)
async def update_features(
    body: FeatureUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminFeaturesResponse:
    _require_admin(current_user)
    enabled = await FeatureFlagService.update(
        db, updates=body.features, actor_id=current_user.id
    )
    await db.commit()
    return AdminFeaturesResponse(
        features=[
            FeatureDefinitionResponse(
                key=definition.key,
                enabled=enabled[definition.key],
                default=definition.default,
                public=definition.public,
                description=definition.description,
                disable_behavior=definition.disable_behavior,
            )
            for definition in FEATURES.values()
        ]
    )

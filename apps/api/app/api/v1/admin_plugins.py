"""Administrator plugin inventory and enabled-state management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.plugins import BUILTIN_PLUGINS, PluginRegistry, PluginState, get_plugin_registry
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...schemas.features import PluginCapabilityResponse
from ...schemas.plugins import (
    AdminPluginResponse,
    AdminPluginsResponse,
    PluginManifestMetadata,
    PluginStateUpdateRequest,
)
from ...services.plugin_service import PluginService
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/plugins", tags=["admin-plugins"])


def _require_admin(user: User) -> None:
    if not has_role(get_user_roles(user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _status_response(state: PluginState) -> PluginCapabilityResponse:
    return PluginCapabilityResponse(
        version=state.version,
        installed=state.installed,
        enabled=state.enabled,
        configured=state.configured,
        healthy=state.healthy,
        public_url=state.public_url,
        assemblies=list(state.assemblies),
        reason=state.reason,
    )


def _admin_response(
    key: str, state: PluginState, registry: PluginRegistry
) -> AdminPluginResponse:
    manifest = registry.verified_manifest(key)
    return AdminPluginResponse(
        key=key,
        status=_status_response(state),
        manifest=(
            PluginManifestMetadata.from_manifest(manifest)
            if manifest is not None
            else None
        ),
    )


@router.get("", response_model=AdminPluginsResponse)
async def list_plugins(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminPluginsResponse:
    _require_admin(current_user)
    registry = get_plugin_registry()
    states = await PluginService.snapshot(db, registry)
    return AdminPluginsResponse(
        plugins={
            key: _admin_response(key, states[key], registry)
            for key in BUILTIN_PLUGINS
        }
    )


@router.get("/{key}", response_model=AdminPluginResponse)
async def get_plugin(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminPluginResponse:
    _require_admin(current_user)
    registry = get_plugin_registry()
    if registry.verified_manifest(key) is None:
        raise NotFoundError(f"Plugin '{key}' not found")
    state = await PluginService.status(db, registry, key)
    return _admin_response(key, state, registry)


@router.patch("/{key}/state", response_model=AdminPluginResponse)
async def update_plugin_state(
    key: str,
    body: PluginStateUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AdminPluginResponse:
    _require_admin(current_user)
    registry = get_plugin_registry()
    state = await PluginService.update_enabled(
        db,
        registry,
        key=key,
        enabled=body.enabled,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return _admin_response(key, state, registry)

__all__ = ["router"]

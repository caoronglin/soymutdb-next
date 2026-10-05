"""Admin settings endpoints — dynamic key-value configuration via SystemSetting.

Provides generic ``GET /admin/settings/{section}`` and
``PUT /admin/settings/{section}`` endpoints for the admin settings UI
(``apps/admin/src/routes/settings.tsx``).  Each section maps to
``SystemSetting`` rows whose keys start with ``{section}.``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.security import RoleName, has_role
from ...core.settings_registry import (
    SETTINGS_REGISTRY,
    SettingKind,
    registered_keys_for_section,
    validate_setting_update,
)
from ...core.site_variant import SiteVariant, legacy_section_for_variant
from ...models.auth import User
from ...models.system_settings import SystemSetting
from ...schemas.error import ErrorResponse
from ...schemas.settings import (
    SettingFieldSchema,
    SettingsDocumentResponse,
    SettingsHistoryResponse,
    SettingsPatchRequest,
    SettingsRollbackRequest,
    SettingsSchemaResponse,
    SettingsSectionSchema,
    SettingsValidateRequest,
    SettingsValidateResponse,
)
from ...schemas.site import AdminSiteBrandResponse, SiteBrandPatchRequest
from ...services import settings_service
from ...services.site_brand_service import get_site_brand_document, patch_site_brand
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


@router.get("/schema", response_model=SettingsSchemaResponse)
async def get_settings_schema(
    current_user: User = Depends(get_current_user),
) -> SettingsSchemaResponse:
    """Return the server-owned, non-secret runtime settings contract."""
    _require_admin(current_user)
    sections: dict[str, SettingsSectionSchema] = {}
    for definition in SETTINGS_REGISTRY.values():
        if definition.kind is SettingKind.SECRET:
            continue
        section = sections.setdefault(definition.section, SettingsSectionSchema(fields={}))
        section.fields[definition.key] = SettingFieldSchema(
            kind=definition.kind.value,  # type: ignore[arg-type]
            default=definition.default,
            permission=definition.permission.value,  # type: ignore[arg-type]
            scope=definition.scope.value,  # type: ignore[arg-type]
            hot_reload=definition.hot_reload,
            redaction=definition.redaction.value,  # type: ignore[arg-type]
            requires_approval=definition.requires_approval,
            allowed_values=sorted(definition.allowed_values),
            allowed_url_hosts=sorted(definition.allowed_url_hosts),
            minimum=definition.minimum,
            maximum=definition.maximum,
            max_length=definition.max_length,
        )
    return SettingsSchemaResponse(sections=sections)


@router.post("/validate", response_model=SettingsValidateResponse)
async def validate_settings(
    body: SettingsValidateRequest,
    current_user: User = Depends(get_current_user),
) -> SettingsValidateResponse:
    """Validate and normalize a partial settings document without persisting it."""
    _require_admin(current_user)
    return SettingsValidateResponse(
        section=body.section,
        values=settings_service.validate_settings_values(body.section, body.values),
    )


@router.get("/site-brand", response_model=AdminSiteBrandResponse)
async def get_admin_site_brand(
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSiteBrandResponse:
    """Return the versioned, UI-facing brand values for one site variant."""
    _require_admin(current_user)
    return await get_site_brand_document(db, variant=variant)


@router.patch(
    "/site-brand",
    response_model=AdminSiteBrandResponse,
    responses={409: {"model": ErrorResponse, "description": "Settings version conflict"}},
)
async def patch_admin_site_brand(
    body: SiteBrandPatchRequest,
    request: Request,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminSiteBrandResponse:
    """Apply an audited brand patch with optimistic version checking."""
    _require_admin(current_user)
    return await patch_site_brand(
        db,
        variant=variant,
        expected_version=body.expected_version,
        values=body.values,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


@router.get("/{section}/document", response_model=SettingsDocumentResponse)
async def get_settings_document(
    section: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsDocumentResponse:
    """Return typed live values with the version required by PATCH."""
    _require_admin(current_user)
    return await settings_service.get_settings_document(db, section=section)


@router.get("/{section}", deprecated=True)
async def get_settings(
    section: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return all settings under *section* as a ``{key: value}`` dict.

    Only registered non-secret keys are queried, and the section prefix is
    stripped from returned keys.
    """
    _require_admin(current_user)

    allowed_keys = registered_keys_for_section(section)
    if not allowed_keys:
        raise NotFoundError(f"Settings section '{section}' not found")
    prefix = f"{section}."
    full_keys = [f"{prefix}{key}" for key in allowed_keys]
    legacy_section = legacy_section_for_variant(section)
    legacy_prefix = f"{legacy_section}." if legacy_section else None
    if legacy_prefix:
        full_keys.extend(
            f"{legacy_prefix}{key}"
            for key in allowed_keys
            if f"{legacy_prefix}{key}" not in full_keys
        )
    stmt = select(SystemSetting).where(SystemSetting.key.in_(full_keys))
    result = await db.execute(stmt)
    rows = result.scalars().all()

    settings: dict[str, Any] = {}
    for row in rows:
        if row.key.startswith(prefix):
            short_key = row.key[len(prefix) :]
        elif legacy_prefix and row.key.startswith(legacy_prefix):
            short_key = row.key[len(legacy_prefix) :]
            if short_key in settings:
                continue
        else:
            continue
        if short_key in allowed_keys:
            settings[short_key] = row.value

    return settings


@router.patch(
    "/{section}",
    response_model=SettingsDocumentResponse,
    responses={409: {"model": ErrorResponse, "description": "Settings version conflict"}},
)
async def patch_settings(
    section: str,
    body: SettingsPatchRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsDocumentResponse:
    """Apply an optimistic, versioned partial update to one section."""
    _require_admin(current_user)
    return await settings_service.patch_settings(
        db,
        section=section,
        expected_version=body.expected_version,
        values=body.values,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


@router.get("/{section}/history", response_model=SettingsHistoryResponse)
async def get_settings_history(
    section: str,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsHistoryResponse:
    """Return bounded revision and audit metadata for one section."""
    _require_admin(current_user)
    return await settings_service.settings_history(db, section=section, limit=limit)


@router.post(
    "/{section}/rollback",
    response_model=SettingsDocumentResponse,
    responses={409: {"model": ErrorResponse, "description": "Settings version conflict"}},
)
async def rollback_settings(
    section: str,
    body: SettingsRollbackRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsDocumentResponse:
    """Restore a historical snapshot as a new linear version."""
    _require_admin(current_user)
    return await settings_service.rollback_settings(
        db,
        section=section,
        expected_version=body.expected_version,
        target_version=body.target_version,
        reason=body.reason,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


@router.put("/{section}", deprecated=True)
async def update_settings(
    section: str,
    payload: dict[str, Any],
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upsert settings under *section*.

    This deprecated compatibility layer accepts the historical flat
    ``{key: value}`` body and string-valued response, while delegating to the
    same fail-closed registry, revision history, and audit transaction as the
    typed contract.
    """
    _require_admin(current_user)

    document = await settings_service.put_settings_compat(
        db,
        section=section,
        values=payload,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    return {
        key: validate_setting_update(section, key, value) for key, value in document.values.items()
    }

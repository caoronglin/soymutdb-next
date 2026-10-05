"""Versioned bilingual branding backed by system settings and verified media."""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import ValidationError
from ..core.settings_registry import get_setting_definition
from ..core.site_variant import SiteVariant
from ..models.media import MediaAsset, MediaAssetStatus
from ..models.system_settings import SystemSetting
from ..schemas.settings import SettingValue
from ..schemas.site import AdminSiteBrandResponse, SiteBrandPatchValues, SiteBrandValues
from . import settings_service

_SAFE_ICON_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_MAX_ICON_BYTES = 2 * 1024 * 1024
_MAX_ICON_DIMENSION = 1024


def brand_settings_section(variant: SiteVariant) -> str:
    return f"brand_{variant.value}"


def _media_is_safe_site_icon(asset: MediaAsset) -> bool:
    """Only expose completed raster uploads from the configured media origin."""
    if (
        asset.status != MediaAssetStatus.READY.value
        or asset.content_type not in _SAFE_ICON_TYPES
        or asset.size_bytes < 1
        or asset.size_bytes > _MAX_ICON_BYTES
        or asset.width is None
        or asset.height is None
        or not (1 <= asset.width <= _MAX_ICON_DIMENSION)
        or not (1 <= asset.height <= _MAX_ICON_DIMENSION)
        or not asset.object_key.startswith("uploads/")
    ):
        return False

    expected_url = (
        f"{get_settings().s3_public_url.rstrip('/')}/{asset.object_key.lstrip('/')}"
    )
    if asset.public_url != expected_url:
        return False
    try:
        parsed = urlsplit(asset.public_url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


async def _icon_url_for_id(db: AsyncSession, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        asset_id = uuid.UUID(value)
    except ValueError:
        return None
    asset = await db.get(MediaAsset, asset_id)
    if asset is None or not _media_is_safe_site_icon(asset):
        return None
    return asset.public_url


async def _icon_asset_id_for_url(db: AsyncSession, icon_url: str) -> str:
    asset = await db.scalar(
        select(MediaAsset).where(
            MediaAsset.public_url == icon_url,
            MediaAsset.status == MediaAssetStatus.READY.value,
        )
    )
    if asset is None or not _media_is_safe_site_icon(asset):
        raise ValidationError(
            "icon_url must reference a ready, verified PNG, JPEG or WebP media asset"
        )
    return str(asset.id)


async def get_site_brand_document(
    db: AsyncSession, *, variant: SiteVariant
) -> AdminSiteBrandResponse:
    """Return the settings version and UI-facing values for one site variant."""
    section = brand_settings_section(variant)
    document = await settings_service.get_settings_document(db, section=section)

    legacy_name = await db.scalar(
        select(SystemSetting.value).where(SystemSetting.key == "general.siteName")
    )
    if isinstance(legacy_name, str) and ("<" in legacy_name or ">" in legacy_name):
        legacy_name = None
    name_zh = document.values.get("name_zh") or legacy_name
    name_en = document.values.get("name_en") or legacy_name
    default_zh = get_setting_definition(section, "name_zh").default
    default_en = get_setting_definition(section, "name_en").default
    stored_icon_id = document.values.get("icon_asset_id")

    return AdminSiteBrandResponse(
        variant=variant.value,
        version=document.version,
        values=SiteBrandValues(
            name_zh=str(name_zh or default_zh),
            name_en=str(name_en or default_en),
            icon_url=await _icon_url_for_id(db, stored_icon_id),
        ),
    )


async def patch_site_brand(
    db: AsyncSession,
    *,
    variant: SiteVariant,
    expected_version: int,
    values: SiteBrandPatchValues,
    actor_id: uuid.UUID,
    ip_address: str | None,
) -> AdminSiteBrandResponse:
    """Map the safe media URL API to a media UUID, then use audited settings."""
    update_values: dict[str, SettingValue] = {}
    provided = values.model_fields_set
    if "name_zh" in provided and values.name_zh is not None:
        update_values["name_zh"] = values.name_zh
    if "name_en" in provided and values.name_en is not None:
        update_values["name_en"] = values.name_en
    if "icon_url" in provided:
        update_values["icon_asset_id"] = (
            "" if values.icon_url is None else await _icon_asset_id_for_url(db, values.icon_url)
        )
    if not update_values:
        raise ValidationError("At least one site-brand field must be provided")

    await settings_service.patch_settings(
        db,
        section=brand_settings_section(variant),
        expected_version=expected_version,
        values=update_values,
        actor_id=actor_id,
        ip_address=ip_address,
    )
    return await get_site_brand_document(db, variant=variant)


__all__ = ["brand_settings_section", "get_site_brand_document", "patch_site_brand"]

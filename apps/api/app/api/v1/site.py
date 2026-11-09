"""Explicit-variant site content endpoints.

The build/deployment selects external or internal explicitly.  The server does
not infer a site from a hostname, header, IP address, cookie, or user-agent.
External content remains cacheable and public; internal content requires an
authenticated viewer and is never cacheable by shared proxies.

All values are stored in the existing versioned system_settings store. Variant
sections are isolated namespaces (for example content_external.* and
content_internal.*) and fall back to legacy non-variant rows only during
migration compatibility.

Contract:
- GET /api/v1/site/about?variant=external|internal
- GET /api/v1/site/home?variant=external|internal
- GET /api/v1/site/footer?variant=external|internal
- GET /api/v1/site/content?variant=external|internal

variant=internal requires a bearer token for a user who has the viewer role
(or a role that grants it).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthenticationError, AuthorizationError
from ...core.footer_content import (
    DEFAULT_FOOTER_NAVIGATION_JSON,
    FooterContentValidationError,
    parse_footer_navigation,
    visible_footer_navigation,
)
from ...core.features import FeatureFlagService
from ...core.header_navigation import (
    DEFAULT_HEADER_NAVIGATION_JSON,
    HeaderContentValidationError,
    parse_header_navigation,
    visible_header_navigation,
)
from ...core.sanitize import sanitize_rich_html
from ...core.security import RoleName, has_role
from ...core.settings_registry import (
    SETTINGS_REGISTRY,
    SettingKind,
    get_setting_definition,
)
from ...core.site_variant import SiteVariant, variant_section
from ...models.auth import User
from ...models.system_settings import SystemSetting
from ...schemas.site import (
    AboutContentResponse,
    FooterContentResponse,
    HomeContentResponse,
    SiteBrandResponse,
    SiteNavigationResponse,
    SiteProfileResponse,
)
from ...services.site_brand_service import get_site_brand_document
from .deps import get_optional_user, get_user_roles

router = APIRouter(prefix="/site", tags=["site"])
logger = logging.getLogger(__name__)


# Keys served by the specialized endpoints (without their section prefix).
_ABOUT_KEYS = (
    "title_en",
    "title_zh",
    "summary_en",
    "summary_zh",
    "content_en",
    "content_zh",
)
_HOME_KEYS = ("welcome_en", "welcome_zh")
_FOOTER_KEYS = (
    "contact_person",
    "contact_phone",
    "contact_email",
    "copyright",
    "address",
    "contact_person_en",
    "contact_person_zh",
    "contact_phone_value",
    "contact_email_value",
    "address_en",
    "address_zh",
    "copyright_en",
    "copyright_zh",
    "navigation_json",
)
_RICH_ABOUT_KEYS = frozenset({"content_en", "content_zh"})
_RICH_HOME_KEYS = frozenset({"welcome_en", "welcome_zh"})

#: Registered content.* keys served by GET /site/content.
_CONTENT_DEFINITIONS = tuple(
    definition
    for definition in SETTINGS_REGISTRY.values()
    if definition.section == "content" and definition.kind is not SettingKind.SECRET
)


def _ensure_variant_access(variant: SiteVariant, current_user: User | None) -> None:
    """Enforce the private read boundary for the internal artifact."""
    if variant is SiteVariant.EXTERNAL:
        return
    if current_user is None:
        raise AuthenticationError("Internal site content requires authentication")
    if not has_role(get_user_roles(current_user), RoleName.VIEWER):
        raise AuthorizationError("Viewer role required for internal site content")


def _set_cache_policy(response: Response, variant: SiteVariant) -> None:
    """Prevent internal content from entering a shared/browser cache."""
    if variant is SiteVariant.INTERNAL:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization"
    else:
        response.headers["Cache-Control"] = (
            "public, max-age=60, stale-while-revalidate=300"
        )


async def _variant_values(
    db: AsyncSession,
    *,
    base_section: str,
    variant: SiteVariant,
    keys: Iterable[str],
) -> dict[str, str]:
    """Load a variant namespace with a bounded legacy fallback.

    Legacy fallback lets existing deployments switch to the new build without
    losing content before an administrator saves the first variant revision.
    It is read-only compatibility; all new writes use the variant section.
    """
    selected_section = variant_section(base_section, variant)
    selected_prefix = f"{selected_section}."
    legacy_prefix = f"{base_section}."
    key_list = tuple(keys)
    full_keys = [f"{selected_prefix}{key}" for key in key_list]
    full_keys.extend(
        f"{legacy_prefix}{key}"
        for key in key_list
        if f"{legacy_prefix}{key}" not in full_keys
    )
    rows = (
        await db.execute(select(SystemSetting).where(SystemSetting.key.in_(full_keys)))
    ).scalars().all()
    stored = {row.key: row.value for row in rows}
    values: dict[str, str] = {}
    for key in key_list:
        selected_key = f"{selected_prefix}{key}"
        legacy_key = f"{legacy_prefix}{key}"
        if selected_key in stored:
            values[key] = stored[selected_key]
        elif legacy_key in stored:
            values[key] = stored[legacy_key]
    return values


def _sanitize_values(values: dict[str, str], rich_keys: frozenset[str]) -> dict[str, str]:
    return {
        key: sanitize_rich_html(value) if key in rich_keys else value
        for key, value in values.items()
    }


@router.get("/branding", response_model=SiteBrandResponse)
async def get_site_branding(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SiteBrandResponse:
    """Return a bilingual brand snapshot for one explicit site artifact."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    document = await get_site_brand_document(db, variant=variant)
    return SiteBrandResponse(variant=variant.value, **document.values.model_dump())


@router.get("/navigation", response_model=SiteNavigationResponse)
async def get_site_navigation(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SiteNavigationResponse:
    """Return the editable primary navigation, filtered by feature flags."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    values = await _variant_values(
        db, base_section="header", variant=variant, keys=("navigation_json",)
    )
    selected_section = variant_section("header", variant)
    navigation_json = values.get(
        "navigation_json",
        str(get_setting_definition(selected_section, "navigation_json").default),
    )
    enabled_features = {
        key
        for key, enabled in (await FeatureFlagService.snapshot(db)).items()
        if enabled
    }
    try:
        groups = visible_header_navigation(
            parse_header_navigation(navigation_json), enabled_features
        )
    except HeaderContentValidationError:
        logger.warning(
            "Invalid header navigation configuration for variant=%s; using defaults",
            variant.value,
        )
        groups = visible_header_navigation(
            parse_header_navigation(DEFAULT_HEADER_NAVIGATION_JSON), enabled_features
        )
    return SiteNavigationResponse(variant=variant.value, groups=groups)


@router.get("/profile", response_model=SiteProfileResponse)
async def get_site_profile(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> SiteProfileResponse:
    """Return the configured database kind and public feature availability."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    stored = await db.scalar(
        select(SystemSetting).where(SystemSetting.key == "general.databaseKind")
    )
    default_kind = str(get_setting_definition("general", "databaseKind").default)
    kind = stored.value if stored is not None else default_kind
    if kind not in {"genome", "gene_ontology", "transcription_factor"}:
        kind = default_kind
    features = await FeatureFlagService.snapshot(db, public_only=True)
    return SiteProfileResponse(
        variant=variant.value,
        database_kind=kind,  # type: ignore[arg-type]
        features=features,
    )


@router.get("/about", response_model=AboutContentResponse)
async def get_about_content(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> AboutContentResponse:
    """Return bilingual About content for the explicitly selected site."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    values = await _variant_values(
        db, base_section="about", variant=variant, keys=_ABOUT_KEYS
    )
    values = _sanitize_values(values, _RICH_ABOUT_KEYS)
    return AboutContentResponse(**{key: values.get(key) for key in _ABOUT_KEYS})


@router.get("/home", response_model=HomeContentResponse)
async def get_home_content(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> HomeContentResponse:
    """Return the variant-specific homepage welcome block."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    values = await _variant_values(
        db, base_section="home", variant=variant, keys=_HOME_KEYS
    )
    values = _sanitize_values(values, _RICH_HOME_KEYS)
    return HomeContentResponse(**{key: values.get(key) for key in _HOME_KEYS})


@router.get("/footer", response_model=FooterContentResponse)
async def get_footer_content(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> FooterContentResponse:
    """Return the variant-specific footer, with registered defaults."""
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    values = await _variant_values(
        db, base_section="footer", variant=variant, keys=_FOOTER_KEYS
    )
    selected_section = variant_section("footer", variant)
    footer_values = {
        key: values[key]
        if key in values
        else str(get_setting_definition(selected_section, key).default)
        for key in _FOOTER_KEYS
        if key != "navigation_json"
    }
    default_navigation = DEFAULT_FOOTER_NAVIGATION_JSON
    navigation_json = values.get(
        "navigation_json",
        str(get_setting_definition(selected_section, "navigation_json").default),
    )
    try:
        navigation = visible_footer_navigation(
            parse_footer_navigation(navigation_json)
        )
    except FooterContentValidationError:
        # Never log stored contact or navigation values; the variant is enough
        # context to diagnose the fallback without exposing user content.
        logger.warning(
            "Invalid footer navigation configuration for variant=%s; using defaults",
            variant.value,
        )
        navigation = visible_footer_navigation(
            parse_footer_navigation(default_navigation)
        )
    return FooterContentResponse(**footer_values, navigation=navigation)


@router.get("/content", response_model=dict[str, str])
async def get_site_content(
    response: Response,
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    only_overrides: bool = Query(
        default=False,
        description=(
            "Return only the keys this variant has a stored value for, instead of "
            "every registered key filled with its (English) registered default. A "
            "bilingual portal needs the distinction: without it, consuming the "
            "endpoint would replace a locale-specific string with the English "
            "default on every page load."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
) -> dict[str, str]:
    """Return the editable frontend labels for one explicit site variant.

    The response is intentionally flat for compatibility with the existing
    useSiteContent contract. The namespace and authorization boundary remain
    server-side, so variant=internal cannot be enumerated anonymously.

    ``only_overrides=true`` returns just the stored rows: a caller then renders
    ``value ?? its own locale-aware default`` and an unedited deployment keeps
    looking exactly as it does today. The default (``false``) keeps the original
    "every registered key, default-filled" shape for existing consumers.
    """
    _ensure_variant_access(variant, current_user)
    _set_cache_policy(response, variant)
    selected_section = variant_section("content", variant)
    values = await _variant_values(
        db,
        base_section="content",
        variant=variant,
        keys=(definition.key for definition in _CONTENT_DEFINITIONS),
    )
    if only_overrides:
        # ``_variant_values`` only ever returns keys that have a stored row
        # (variant namespace, or the legacy non-variant row during migration).
        return dict(values)
    return {
        definition.key: values.get(
            definition.key,
            str(get_setting_definition(selected_section, definition.key).default),
        )
        for definition in _CONTENT_DEFINITIONS
    }

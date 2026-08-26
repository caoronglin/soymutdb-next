"""Public site-information endpoints (D4): editable "About us" / home / footer.

Serves the ``about.*``, ``home.*`` and ``footer.*`` rows from
``system_settings`` (the same key-value store the admin Settings UI edits
via ``PUT /admin/settings/{section}`` — see
``apps/admin/src/routes/settings.tsx``).  No authentication required;
missing about/home keys degrade to ``None`` and missing footer keys fall
back to their registered defaults so a fresh deployment renders gracefully.

Contract:
- ``GET /api/v1/site/about`` -> AboutContentResponse
- ``GET /api/v1/site/home``  -> HomeContentResponse
- ``GET /api/v1/site/footer`` -> FooterContentResponse
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.sanitize import sanitize_rich_html
from ...core.settings_registry import SETTINGS_REGISTRY, SettingKind, get_setting_definition
from ...models.system_settings import SystemSetting
from ...schemas.site import AboutContentResponse, FooterContentResponse, HomeContentResponse

router = APIRouter(prefix="/site", tags=["site"])

#: Keys served by this endpoint (without the ``about.`` prefix).
_ABOUT_KEYS = (
    "title_en",
    "title_zh",
    "summary_en",
    "summary_zh",
    "content_en",
    "content_zh",
)


@router.get("/about", response_model=AboutContentResponse)
async def get_about_content(
    db: AsyncSession = Depends(get_db),
) -> AboutContentResponse:
    """Return the editable "About us" content (bilingual, optional)."""
    prefix = "about."
    stmt = select(SystemSetting).where(
        SystemSetting.key.in_([f"{prefix}{k}" for k in _ABOUT_KEYS])
    )
    rows = (await db.execute(stmt)).scalars().all()
    values: dict[str, str] = {row.key[len(prefix):]: row.value for row in rows}

    return AboutContentResponse(
        **{
            key: values.get(key)
            for key in _ABOUT_KEYS
        }
    )


#: Keys served by ``GET /site/home`` (without the ``home.`` prefix).
_HOME_KEYS = (
    "welcome_en",
    "welcome_zh",
)


@router.get("/home", response_model=HomeContentResponse)
async def get_home_content(
    db: AsyncSession = Depends(get_db),
) -> HomeContentResponse:
    """Return the editable homepage welcome block (bilingual, optional).

    Values are rich HTML authored by administrators.  The generic
    ``PUT /admin/settings/{section}`` endpoint only sanitizes its
    ``content_*`` keys, so every value is re-sanitized here on read —
    defence in depth against rows written by any other path.
    """
    prefix = "home."
    stmt = select(SystemSetting).where(
        SystemSetting.key.in_([f"{prefix}{k}" for k in _HOME_KEYS])
    )
    rows = (await db.execute(stmt)).scalars().all()
    values: dict[str, str] = {
        row.key[len(prefix):]: sanitize_rich_html(row.value) for row in rows
    }

    return HomeContentResponse(
        **{
            key: values.get(key)
            for key in _HOME_KEYS
        }
    )


#: Keys served by ``GET /site/footer`` (without the ``footer.`` prefix).
_FOOTER_KEYS = (
    "contact_person",
    "contact_phone",
    "contact_email",
    "copyright",
    "address",
)


@router.get("/footer", response_model=FooterContentResponse)
async def get_footer_content(
    db: AsyncSession = Depends(get_db),
) -> FooterContentResponse:
    """Return the editable footer contact block backed by ``system_settings``.

    Missing rows fall back to the registered defaults so a fresh deployment
    renders the current placeholder contact info without an extra client
    fallback.
    """
    prefix = "footer."
    stmt = select(SystemSetting).where(
        SystemSetting.key.in_([f"{prefix}{k}" for k in _FOOTER_KEYS])
    )
    rows = (await db.execute(stmt)).scalars().all()
    values: dict[str, str] = {row.key[len(prefix):]: row.value for row in rows}
    return FooterContentResponse(
        **{
            key: values[key] if key in values else str(get_setting_definition("footer", key).default)
            for key in _FOOTER_KEYS
        }
    )


#: Registered content.* keys served by GET /site/content (short key,
#: i.e. the part after the content. prefix). The endpoint falls back to the
#: registered default for keys without a stored row, so a fresh deployment
#: renders identically until an administrator edits them via the Settings UI.
_CONTENT_DEFINITIONS = tuple(
    definition
    for definition in SETTINGS_REGISTRY.values()
    if definition.section == "content" and definition.kind is not SettingKind.SECRET
)


@router.get("/content", response_model=dict[str, str])
async def get_site_content(
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Return all editable site-content keys as a flat {short_key: value} map.

    Short keys are the registered content.* keys without the content. prefix
    (e.g. hero.title). Missing rows fall back to their registered defaults so
    the public frontend always receives a complete object.
    """
    full_keys = [definition.full_key for definition in _CONTENT_DEFINITIONS]
    rows = (
        (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(full_keys))))
        .scalars()
        .all()
    )
    stored = {row.key: row.value for row in rows}
    return {
        definition.key: stored.get(definition.full_key, str(definition.default))
        for definition in _CONTENT_DEFINITIONS
    }


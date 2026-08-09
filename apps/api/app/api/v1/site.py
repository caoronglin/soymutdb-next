"""Public site-information endpoints (D4): editable "About us" / home content.

Serves the ``about.*`` and ``home.*`` rows from ``system_settings`` (the
same key-value store the admin Settings UI edits via
``PUT /admin/settings/{section}`` — see
``apps/admin/src/routes/settings.tsx``).  No authentication required;
missing keys degrade to ``None`` so a fresh deployment renders gracefully.

Contract:
- ``GET /api/v1/site/about`` -> AboutContentResponse
- ``GET /api/v1/site/home``  -> HomeContentResponse
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.sanitize import sanitize_rich_html
from ...models.system_settings import SystemSetting
from ...schemas.site import AboutContentResponse, HomeContentResponse

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

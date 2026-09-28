"""``GET /api/v1/site/content`` must expose an override-only mode.

The portal is bilingual: the registered defaults of every ``content.*`` key are
English, and the endpoint historically fills *every* registered key with its
default. A consumer that lets the server value win would therefore replace a
Chinese page's copy with the English default on the first page load.

``only_overrides=true`` returns just the stored rows, so a caller can render
``value ?? its own locale-aware default`` and an unedited deployment keeps
rendering exactly as it does today. These tests pin:

* the legacy shape (every registered key, default-filled) is unchanged;
* the override-only shape is empty until an administrator stores a row, then
  contains exactly that key;
* the two variants stay isolated (an internal override never leaks to external);
* the existing cache policy survives the new parameter.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.core.settings_registry import SETTINGS_REGISTRY, SettingKind
from app.models.system_settings import SystemSetting

_CONTENT_KEYS = [
    definition.key
    for definition in SETTINGS_REGISTRY.values()
    if definition.section == "content" and definition.kind is not SettingKind.SECRET
]


@pytest.fixture(autouse=True)
async def _clean_content_rows(db_session):
    """Keep every case independent of rows another test may have written."""
    await db_session.execute(
        delete(SystemSetting).where(SystemSetting.key.like("content%"))
    )
    await db_session.commit()
    yield
    await db_session.execute(
        delete(SystemSetting).where(SystemSetting.key.like("content%"))
    )
    await db_session.commit()


async def _store(db_session, key: str, value: str) -> None:
    db_session.add(SystemSetting(key=key, value=value))
    await db_session.commit()


@pytest.mark.asyncio
async def test_default_shape_still_fills_every_registered_key(client) -> None:
    """No parameter -> the original contract, unchanged, for existing consumers."""
    response = await client.get("/api/v1/site/content", params={"variant": "external"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(_CONTENT_KEYS)
    assert body["hero.title"]  # filled with the registered default
    assert response.headers["cache-control"].startswith("public")


@pytest.mark.asyncio
async def test_only_overrides_is_empty_until_an_operator_stores_a_row(client) -> None:
    response = await client.get(
        "/api/v1/site/content",
        params={"variant": "external", "only_overrides": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {}


@pytest.mark.asyncio
async def test_only_overrides_returns_exactly_the_stored_keys(
    client, db_session
) -> None:
    await _store(db_session, "content_external.hero.title", "自定义标题")
    await _store(db_session, "content_external.tool.gene.label", "基因检索")

    response = await client.get(
        "/api/v1/site/content",
        params={"variant": "external", "only_overrides": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "hero.title": "自定义标题",
        "tool.gene.label": "基因检索",
    }


@pytest.mark.asyncio
async def test_variant_overrides_stay_isolated(client, db_session) -> None:
    """An internal override must never appear in the external variant."""
    await _store(db_session, "content_internal.hero.title", "内网标题")
    await _store(db_session, "content_external.hero.title", "外网标题")

    external = await client.get(
        "/api/v1/site/content",
        params={"variant": "external", "only_overrides": "true"},
    )
    internal = await client.get(
        "/api/v1/site/content",
        params={"variant": "internal", "only_overrides": "true"},
    )

    assert external.json() == {"hero.title": "外网标题"}
    # Anonymous internal reads stay forbidden regardless of the new parameter.
    assert internal.status_code in (401, 403)


@pytest.mark.asyncio
async def test_internal_variant_keeps_its_private_cache_policy(client) -> None:
    response = await client.get(
        "/api/v1/site/content",
        params={"variant": "internal", "only_overrides": "true"},
    )

    # Whether the anonymous read is rejected or answered by an authenticated
    # viewer, an internal response must never become shareable cache state.
    assert response.headers.get("cache-control") in (None, "private, no-store")
    if response.status_code == 200:
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Authorization"

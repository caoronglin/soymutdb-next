"""Variant, compatibility, and cache tests for GET /api/v1/site/footer."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db


def _session(rows: list[MagicMock] | None = None) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows or []
    session.execute = AsyncMock(return_value=result)
    return session


def _row(key: str, value: str) -> MagicMock:
    row = MagicMock()
    row.key = key
    row.value = value
    return row


def _navigation(href: str, *, label: str = "Help") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "groups": [
                {
                    "id": "resources",
                    "title_en": "Resources",
                    "title_zh": "资源",
                    "enabled": True,
                    "order": 0,
                    "links": [
                        {
                            "id": "help",
                            "label_en": label,
                            "label_zh": "帮助",
                            "target": "internal",
                            "href": href,
                            "enabled": True,
                            "order": 0,
                        }
                    ],
                }
            ],
        }
    )


def _client(session: MagicMock, user: object | None = None) -> AsyncClient:
    from app.api.v1.deps import get_optional_user
    from app.api.v1.site import router
    from app.core.exceptions import SoyMutDBError, soy_mut_db_exception_handler

    app = FastAPI()
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.include_router(router, prefix="/api/v1")

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    if user is not None:
        app.dependency_overrides[get_optional_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_footer_returns_synthetic_legacy_values_and_structured_navigation() -> None:
    session = _session(
        [
            _row("footer.contact_person", "联系人: Synthetic Curator"),
            _row("footer.contact_phone", "电话: +1 555-0100"),
            _row("footer.contact_email", "电子邮件: curator@example.org"),
            _row("footer.address", "地址: Synthetic Street"),
            _row("footer.copyright", "© {{year}} Synthetic SoyMutDB"),
        ]
    )

    async with _client(session) as client:
        response = await client.get("/api/v1/site/footer?variant=external")

    assert response.status_code == 200
    body = response.json()
    assert body["contact_person"] == "联系人: Synthetic Curator"
    assert body["contact_phone"] == "电话: +1 555-0100"
    assert body["contact_person_en"] == ""
    assert body["contact_person_zh"] == ""
    assert [group["id"] for group in body["navigation"]] == [
        "explore",
        "tools",
        "downloads",
        "resources",
    ]
    assert "navigation_json" not in body
    assert response.headers["cache-control"] == (
        "public, max-age=60, stale-while-revalidate=300"
    )


@pytest.mark.asyncio
async def test_footer_keeps_external_and_internal_values_isolated() -> None:
    session = _session(
        [
            _row("footer_external.contact_person_en", "Public Contact"),
            _row("footer_internal.contact_person_en", "Private Contact"),
            _row("footer_external.navigation_json", _navigation("/external-only")),
            _row("footer_internal.navigation_json", _navigation("/internal-only")),
        ]
    )
    viewer = SimpleNamespace(
        role_rel=SimpleNamespace(name="viewer"),
        is_superuser=False,
    )

    async with _client(session) as external_client:
        external_response = await external_client.get(
            "/api/v1/site/footer?variant=external"
        )
    async with _client(session, viewer) as internal_client:
        internal_response = await internal_client.get(
            "/api/v1/site/footer?variant=internal"
        )

    assert external_response.status_code == 200
    external_body = external_response.json()
    assert external_body["contact_person_en"] == "Public Contact"
    assert external_body["navigation"][0]["links"][0]["href"] == "/external-only"
    assert "Private Contact" not in external_response.text
    assert "/internal-only" not in external_response.text

    assert internal_response.status_code == 200
    internal_body = internal_response.json()
    assert internal_body["contact_person_en"] == "Private Contact"
    assert internal_body["navigation"][0]["links"][0]["href"] == "/internal-only"
    assert "Public Contact" not in internal_response.text
    assert "/external-only" not in internal_response.text
    assert internal_response.headers["cache-control"] == "private, no-store"
    assert internal_response.headers["vary"] == "Authorization"


@pytest.mark.asyncio
async def test_internal_footer_requires_authentication() -> None:
    async with _client(_session()) as client:
        response = await client.get("/api/v1/site/footer?variant=internal")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


@pytest.mark.asyncio
async def test_invalid_navigation_fails_closed_and_logs_no_stored_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_value = '{"schema_version":1,"groups":[],"private":"do-not-log"}'
    session = _session([_row("footer_external.navigation_json", secret_value)])
    caplog.set_level(logging.WARNING, logger="app.api.v1.site")

    async with _client(session) as client:
        response = await client.get("/api/v1/site/footer?variant=external")

    assert response.status_code == 200
    assert [group["id"] for group in response.json()["navigation"]] == [
        "explore",
        "tools",
        "downloads",
        "resources",
    ]
    assert secret_value not in response.text
    assert "do-not-log" not in caplog.text
    assert "variant=external" in caplog.text

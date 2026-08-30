"""Tests for the public homepage content endpoint (``GET /api/v1/site/home``).

The endpoint serves the ``home.*`` rows from ``system_settings`` (bilingual
rich-HTML welcome block).  Uses a mocked DB session — no PostgreSQL required
(same pattern as ``TestPublicAbout`` in ``test_admin_settings.py``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db


def _make_mock_session():
    """Return a mock DB session whose ``execute`` is awaitable."""
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _make_client(mock_session, current_user=None):
    """Build an ASGI test client for the site router with overridden dependencies."""
    from app.api.v1.deps import get_optional_user
    from app.api.v1.site import router

    app = FastAPI()
    from app.core.exceptions import SoyMutDBError, soy_mut_db_exception_handler

    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.include_router(router, prefix="/api/v1")

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    if current_user is not None:
        app.dependency_overrides[get_optional_user] = lambda: current_user
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _setting_row(key: str, value: str) -> MagicMock:
    row = MagicMock()
    row.key = key
    row.value = value
    return row


@pytest.mark.asyncio
class TestSiteHome:
    """``GET /site/home`` serves the ``home.*`` system settings publicly."""

    async def test_home_returns_welcome_when_set(self):
        """Existing ``home.*`` rows are returned (sanitized on read)."""
        mock_session = _make_mock_session()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [
            _setting_row(
                "home.welcome_en",
                '<p>Welcome to <strong>SoyMutDB</strong>!</p>'
                '<script>alert("xss")</script>',
            ),
            _setting_row("home.welcome_zh", "<p>欢迎访问 SoyMutDB！</p>"),
        ]

        async with _make_client(mock_session) as client:
            response = await client.get("/api/v1/site/home")

        assert response.status_code == 200
        body = response.json()
        # Sanitizer strips <script> but keeps allowlisted markup.
        assert "<script>" not in body["welcome_en"]
        assert "<p>Welcome to <strong>SoyMutDB</strong>!</p>" in body["welcome_en"]
        assert body["welcome_zh"] == "<p>欢迎访问 SoyMutDB！</p>"

    async def test_home_empty_db_returns_nulls(self):
        """A fresh deployment without ``home.*`` rows returns null fields."""
        mock_session = _make_mock_session()
        # Default mock result already returns an empty row list.

        async with _make_client(mock_session) as client:
            response = await client.get("/api/v1/site/home")

        assert response.status_code == 200
        body = response.json()
        assert body == {"welcome_en": None, "welcome_zh": None}

    async def test_internal_variant_requires_authentication(self):
        """Internal content cannot be read by an anonymous request."""
        mock_session = _make_mock_session()

        async with _make_client(mock_session) as client:
            response = await client.get("/api/v1/site/home?variant=internal")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_failed"

    async def test_external_variant_sets_public_cache_policy(self):
        mock_session = _make_mock_session()

        async with _make_client(mock_session) as client:
            response = await client.get("/api/v1/site/home?variant=external")

        assert response.status_code == 200
        assert response.headers["cache-control"] == (
            "public, max-age=60, stale-while-revalidate=300"
        )


    async def test_internal_variant_is_private_and_not_shared_cacheable(self):
        mock_session = _make_mock_session()
        viewer = SimpleNamespace(
            role_rel=SimpleNamespace(name="viewer"),
            is_superuser=False,
        )

        async with _make_client(mock_session, viewer) as client:
            response = await client.get("/api/v1/site/home?variant=internal")

        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Authorization"

def test_internal_variant_accepts_viewer_role():
    from app.api.v1.site import _ensure_variant_access
    from app.core.site_variant import SiteVariant

    viewer = SimpleNamespace(
        role_rel=SimpleNamespace(name="viewer"),
        is_superuser=False,
    )

    _ensure_variant_access(SiteVariant.INTERNAL, viewer)

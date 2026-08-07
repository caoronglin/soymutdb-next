"""Tests for admin settings API endpoints (``/api/v1/admin/settings/*``).

Covers: GET and PUT for settings sections, with RBAC enforcement.
Uses mocked DB session and authentication — no PostgreSQL required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock DB session with ``AsyncMock`` query methods."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    default_result = MagicMock()
    default_result.scalars.return_value.all.return_value = []
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


def _admin_user():
    """Return a mock User object with administrator privileges."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = True
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "administrator"
    return user


def _viewer_user():
    """Return a mock User object with viewer role (non-admin)."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = False
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "viewer"
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Return a clean mock DB session for admin settings endpoints."""
    return _make_mock_session()


@pytest.fixture
def admin_user():
    """Return a mock admin user."""
    return _admin_user()


@pytest.fixture
def viewer_user():
    """Return a mock viewer user (non-admin)."""
    return _viewer_user()


@pytest.fixture
async def client(mock_session, admin_user):
    """Create a test client with mocked DB session and admin auth.

    By default the current user is an administrator.  Override the
    ``get_current_user`` dependency to test non-admin scenarios.
    """
    from app.api.v1.admin_settings import router
    from app.api.v1.deps import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Register exception handlers so AuthorizationError returns 403 JSON
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    async def override_get_db():
        yield mock_session

    async def override_get_current_user():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/admin/settings/{section}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSettings:
    """Tests for ``GET /api/v1/admin/settings/{section}``."""

    async def test_get_settings_returns_dict(self, client, mock_session):
        """Settings are returned as a key-value dict."""
        setting = MagicMock()
        setting.key = "cdn.url"
        setting.value = "https://cdn.example.com"

        result = MagicMock()
        result.scalars.return_value.all.return_value = [setting]
        mock_session.execute.return_value = result

        response = await client.get("/api/v1/admin/settings/cdn")
        assert response.status_code == 200
        data = response.json()
        assert data == {"url": "https://cdn.example.com"}

    async def test_get_settings_empty_section(self, client, mock_session):
        """A section with no settings returns empty dict."""
        response = await client.get("/api/v1/admin/settings/empty_section")
        assert response.status_code == 200
        data = response.json()
        assert data == {}

    async def test_get_settings_multiple_keys(self, client, mock_session):
        """Multiple keys under the same section are all returned."""
        s1 = MagicMock()
        s1.key = "blast.max_sequences"
        s1.value = "100"
        s2 = MagicMock()
        s2.key = "blast.default_db"
        s2.value = "williams82_cds"

        result = MagicMock()
        result.scalars.return_value.all.return_value = [s1, s2]
        mock_session.execute.return_value = result

        response = await client.get("/api/v1/admin/settings/blast")
        assert response.status_code == 200
        data = response.json()
        assert data["max_sequences"] == "100"
        assert data["default_db"] == "williams82_cds"

    async def test_get_settings_requires_admin(
        self, client, mock_session, viewer_user
    ):
        """Non-admin user receives 403."""
        from app.api.v1.deps import get_current_user

        async def override_get_current_user():
            return viewer_user

        client._transport.app.dependency_overrides[
            get_current_user
        ] = override_get_current_user

        response = await client.get("/api/v1/admin/settings/cdn")
        assert response.status_code == 403
        data = response.json()
        assert "error" in data


# ---------------------------------------------------------------------------
# Tests: PUT /api/v1/admin/settings/{section}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateSettings:
    """Tests for ``PUT /api/v1/admin/settings/{section}``."""

    async def test_update_settings_new_key(self, client, mock_session):
        """New key-value pairs are created."""
        # First execute call: no existing row found -> None
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        # Second execute call: get_settings after upsert returns the new setting
        setting = MagicMock()
        setting.key = "cdn.url"
        setting.value = "https://cdn.example.com"
        settings_result = MagicMock()
        settings_result.scalars.return_value.all.return_value = [setting]

        mock_session.execute.side_effect = [not_found, settings_result]

        with patch(
            "app.api.v1.admin_settings.log_action", new_callable=AsyncMock
        ) as mock_log:
            response = await client.put(
                "/api/v1/admin/settings/cdn",
                json={"url": "https://cdn.example.com"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://cdn.example.com"

        # Verify SystemSetting was added to the session
        assert mock_session.add.called
        added_setting = mock_session.add.call_args[0][0]
        assert added_setting.key == "cdn.url"
        assert added_setting.value == "https://cdn.example.com"

        # Verify audit log was recorded
        mock_log.assert_awaited_once()
        assert mock_log.call_args[1]["action"] == "settings_update:cdn"

    async def test_update_settings_existing_key(self, client, mock_session):
        """Existing key-value pairs are updated."""
        # The endpoint batch-fetches existing rows via `.scalars().all()`.
        existing_row = MagicMock()
        existing_row.key = "cdn.url"
        existing = MagicMock()
        existing.scalars.return_value.all.return_value = [existing_row]

        # Second execute: get_settings return
        setting = MagicMock()
        setting.key = "cdn.url"
        setting.value = "https://cdn-new.example.com"
        settings_result = MagicMock()
        settings_result.scalars.return_value.all.return_value = [setting]

        mock_session.execute.side_effect = [existing, settings_result]

        with patch(
            "app.api.v1.admin_settings.log_action", new_callable=AsyncMock
        ):
            response = await client.put(
                "/api/v1/admin/settings/cdn",
                json={"url": "https://cdn-new.example.com"},
            )

        assert response.status_code == 200
        # The existing row's value should have been updated
        assert existing_row.value == "https://cdn-new.example.com"
        assert existing_row.updated_by is not None

    async def test_update_settings_multiple_keys(self, client, mock_session):
        """Multiple keys are upserted in a single request."""
        # One batch-fetch for existing rows under the section (none exist).
        not_found = MagicMock()
        not_found.scalars.return_value.all.return_value = []

        # Final: get_settings return
        s1 = MagicMock()
        s1.key = "blast.max_sequences"
        s1.value = "200"
        s2 = MagicMock()
        s2.key = "blast.default_db"
        s2.value = "williams82_cds"
        settings_result = MagicMock()
        settings_result.scalars.return_value.all.return_value = [s1, s2]

        mock_session.execute.side_effect = [
            not_found,  # batch existing lookup
            settings_result,  # get_settings return
        ]

        with patch(
            "app.api.v1.admin_settings.log_action", new_callable=AsyncMock
        ):
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"max_sequences": "200", "default_db": "williams82_cds"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["max_sequences"] == "200"
        assert data["default_db"] == "williams82_cds"

    async def test_update_settings_requires_admin(
        self, client, mock_session, viewer_user
    ):
        """Non-admin user receives 403 on PUT."""
        from app.api.v1.deps import get_current_user

        async def override_get_current_user():
            return viewer_user

        client._transport.app.dependency_overrides[
            get_current_user
        ] = override_get_current_user

        response = await client.put(
            "/api/v1/admin/settings/cdn",
            json={"url": "https://cdn.example.com"},
        )
        assert response.status_code == 403

    async def test_update_settings_boolean_value(self, client, mock_session):
        """Boolean values are stored as lowercase strings."""
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        setting = MagicMock()
        setting.key = "features.registration"
        setting.value = "true"
        settings_result = MagicMock()
        settings_result.scalars.return_value.all.return_value = [setting]

        mock_session.execute.side_effect = [not_found, settings_result]

        with patch(
            "app.api.v1.admin_settings.log_action", new_callable=AsyncMock
        ):
            response = await client.put(
                "/api/v1/admin/settings/features",
                json={"registration": True},
            )

        assert response.status_code == 200
        assert mock_session.add.called
        added = mock_session.add.call_args[0][0]
        assert added.value == "true"

    async def test_update_settings_numeric_value(self, client, mock_session):
        """Numeric values are JSON-encoded for storage."""
        not_found = MagicMock()
        not_found.scalar_one_or_none.return_value = None

        setting = MagicMock()
        setting.key = "blast.max_sequences"
        setting.value = "200"
        settings_result = MagicMock()
        settings_result.scalars.return_value.all.return_value = [setting]

        mock_session.execute.side_effect = [not_found, settings_result]

        with patch(
            "app.api.v1.admin_settings.log_action", new_callable=AsyncMock
        ):
            response = await client.put(
                "/api/v1/admin/settings/blast",
                json={"max_sequences": 200},
            )

        assert response.status_code == 200
        assert mock_session.add.called
        added = mock_session.add.call_args[0][0]
        assert added.value == "200"

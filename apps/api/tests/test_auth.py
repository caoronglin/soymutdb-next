"""Tests for auth API endpoints (/api/v1/auth/*).

Covers: register, login, refresh, change-password, logout — including
error scenarios (duplicate email, wrong password, invalid token, etc.).

All routes use the ``/api/v1/`` prefix.
All password fields use ``password_hash`` (not ``hashed_password``).

Refresh-token contract (server-side sessions):
- The refresh token is delivered **only** via the HttpOnly cookie
  (``soymutdb_refresh``, Path=/api/v1/auth) — never in JSON.
- ``refresh`` rotates the token server-side; reusing a rotated token
  revokes the whole session family (401).
- ``refresh`` and ``logout`` require a trusted Origin/Referer header.

.. note:: these tests need a real PostgreSQL (testcontainers) — the
   docker-free equivalents live in ``tests/test_auth_sessions.py``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

AUTH_PREFIX = "/api/v1/auth"
REFRESH_COOKIE = "soymutdb_refresh"
COOKIE_PATH = "/api/v1/auth"
# httpx appends ".local" to dotless hosts in its cookie jar, so cookie
# round-trips need a host with a dot.
BASE_URL = "http://test.local"
SAME_ORIGIN = "http://test.local"


@pytest_asyncio.fixture
async def cookie_client(app) -> AsyncGenerator[AsyncClient]:
    """Client whose host matches the cookie domain (for refresh-cookie flows)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as ac:
        yield ac


@pytest.mark.asyncio
class TestRegister:
    """Tests for POST /api/v1/auth/register."""

    async def test_register_success(self, client, user_factory):
        """Successful registration returns 201 and user data."""
        payload = user_factory.make_payload(
            email="newuser@example.com",
            username="newuser",
        )
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["username"] == "newuser"
        assert "id" in data
        # Password should never be in the response
        assert "password" not in data
        assert "password_hash" not in data
        assert "hashed_password" not in data

    async def test_register_duplicate_email(self, client, user_factory):
        """Duplicate email returns 409."""
        payload = user_factory.make_payload(email="dup@example.com", username="user1")
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 201

        payload2 = user_factory.make_payload(email="dup@example.com", username="user2")
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload2)
        assert response.status_code == 409

    async def test_register_duplicate_username(self, client, user_factory):
        """Duplicate username returns 409."""
        payload = user_factory.make_payload(email="u1@example.com", username="sameuser")
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 201

        payload2 = user_factory.make_payload(email="u2@example.com", username="sameuser")
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload2)
        assert response.status_code == 409

    async def test_register_weak_password(self, client, user_factory):
        """Password without uppercase or digit returns 422."""
        payload = user_factory.make_payload(
            email="weak@example.com",
            username="weakuser",
            password="alllowercase",  # no uppercase, no digit
        )
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 422

    async def test_register_short_password(self, client, user_factory):
        """Password shorter than 8 chars returns 422."""
        payload = user_factory.make_payload(
            email="short@example.com",
            username="shortuser",
            password="Ab1!",  # too short
        )
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 422

    async def test_register_invalid_email(self, client, user_factory):
        """Invalid email format returns 422."""
        payload = user_factory.make_payload(
            email="not-an-email",
            username="bademail",
        )
        response = await client.post(f"{AUTH_PREFIX}/register", json=payload)
        assert response.status_code == 422


@pytest.mark.asyncio
class TestLogin:
    """Tests for POST /api/v1/auth/login."""

    async def test_login_success(self, client, user_factory):
        """Successful login returns access token + HttpOnly refresh cookie.

        The refresh token must never appear in the JSON body.
        """
        # Register first
        payload = user_factory.make_payload(
            email="login@example.com",
            username="loginuser",
        )
        await client.post(f"{AUTH_PREFIX}/register", json=payload)

        # Login
        response = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "login@example.com", "password": "TestPass123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

        # Refresh token travels only in the HttpOnly, path-scoped cookie.
        set_cookie = response.headers.get("set-cookie", "")
        assert REFRESH_COOKIE in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert f"Path={COOKIE_PATH}" in set_cookie
        assert response.cookies.get(REFRESH_COOKIE) is not None

    async def test_login_wrong_password(self, client, user_factory):
        """Wrong password returns 401."""
        payload = user_factory.make_payload(
            email="wrongpw@example.com",
            username="wrongpwuser",
        )
        await client.post(f"{AUTH_PREFIX}/register", json=payload)

        response = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "wrongpw@example.com", "password": "WrongPass456!"},
        )
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client):
        """Login with non-existent email returns 401."""
        response = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "nobody@example.com", "password": "TestPass123!"},
        )
        assert response.status_code == 401

    async def test_login_missing_fields(self, client):
        """Login with missing fields returns 422."""
        response = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "test@example.com"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
class TestRefresh:
    """Tests for POST /api/v1/auth/refresh (cookie + Origin required)."""

    async def _login(
        self, cookie_client, user_factory, email="refresh@example.com",
        username="refreshuser",
    ):
        payload = user_factory.make_payload(email=email, username=username)
        await cookie_client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await cookie_client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": email, "password": "TestPass123!"},
        )
        assert login_resp.status_code == 200
        return login_resp

    async def test_refresh_success(self, cookie_client, user_factory):
        """Valid refresh cookie returns a new access token + rotated cookie."""
        login_resp = await self._login(cookie_client, user_factory)
        old_refresh = login_resp.cookies.get(REFRESH_COOKIE)
        assert old_refresh is not None

        response = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        # Rotation: the cookie is replaced with a new token.
        new_refresh = response.cookies.get(REFRESH_COOKIE)
        assert new_refresh is not None
        assert new_refresh != old_refresh

    async def test_refresh_rotated_token_reuse_revokes_family(self, cookie_client, user_factory):
        """Reusing an already-rotated refresh token returns 401 and revokes the family."""
        login_resp = await self._login(cookie_client, user_factory)
        old_refresh = login_resp.cookies.get(REFRESH_COOKIE)

        first = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert first.status_code == 200
        new_refresh = first.cookies.get(REFRESH_COOKIE)

        # Replay the rotated (old) token — reuse detection.
        cookie_client.cookies.set(
            REFRESH_COOKIE, old_refresh, domain="test.local", path=COOKIE_PATH
        )
        replay = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert replay.status_code == 401

        # The whole family is revoked — the newest token is dead too.
        cookie_client.cookies.set(
            REFRESH_COOKIE, new_refresh, domain="test.local", path=COOKIE_PATH
        )
        latest = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert latest.status_code == 401

    async def test_refresh_invalid_token(self, cookie_client):
        """Refresh without a cookie (or with an unknown one) returns 401."""
        response = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 401

    async def test_refresh_without_origin_rejected(self, cookie_client, user_factory):
        """Refresh with no Origin/Referer header is rejected (CSRF defence)."""
        await self._login(cookie_client, user_factory)
        response = await cookie_client.post(f"{AUTH_PREFIX}/refresh")
        assert response.status_code == 401

    async def test_refresh_cross_origin_rejected(self, cookie_client, user_factory):
        """Refresh from a foreign origin is rejected."""
        await self._login(cookie_client, user_factory)
        response = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 401

    async def test_refresh_legacy_token_without_server_record_rejected(
        self, cookie_client, user_factory
    ):
        """Pre-session-table refresh tokens (no server record) are refused."""
        from app.core.security import create_refresh_token

        await self._login(cookie_client, user_factory)
        legacy = create_refresh_token(subject="00000000-0000-0000-0000-000000000000")
        cookie_client.cookies.set(
            REFRESH_COOKIE, legacy, domain="test.local", path=COOKIE_PATH
        )
        response = await cookie_client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 401


@pytest.mark.asyncio
class TestMe:
    """Tests for GET /api/v1/auth/me."""

    async def test_me_requires_auth(self, client):
        """Me endpoint without token returns 401."""
        response = await client.get(f"{AUTH_PREFIX}/me")
        assert response.status_code in (401, 403)

    async def test_me_with_valid_token(self, client, user_factory):
        """Me endpoint with valid token returns user profile."""
        payload = user_factory.make_payload(
            email="me@example.com",
            username="meuser",
        )
        await client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "me@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]

        response = await client.get(
            f"{AUTH_PREFIX}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "me@example.com"
        assert data["username"] == "meuser"


@pytest.mark.asyncio
class TestChangePassword:
    """Tests for POST /api/v1/auth/change-password."""

    async def test_change_password_success(self, client, user_factory):
        """Successful password change returns 204."""
        payload = user_factory.make_payload(
            email="changepw@example.com",
            username="changepwuser",
        )
        await client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "changepw@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]

        response = await client.post(
            f"{AUTH_PREFIX}/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 204

    async def test_change_password_wrong_current(self, client, user_factory):
        """Wrong current password returns 401."""
        payload = user_factory.make_payload(
            email="wrongcur@example.com",
            username="wrongcuruser",
        )
        await client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "wrongcur@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]

        response = await client.post(
            f"{AUTH_PREFIX}/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "current_password": "WrongPass999!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 401

    async def test_change_password_requires_auth(self, client):
        """Change password without token returns 401."""
        response = await client.post(
            f"{AUTH_PREFIX}/change-password",
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code in (401, 403)


@pytest.mark.asyncio
class TestLogout:
    """Tests for POST /api/v1/auth/logout (Bearer + Origin required)."""

    async def test_logout_success(self, cookie_client, user_factory):
        """Logout with valid token returns 204 and clears the refresh cookie."""
        payload = user_factory.make_payload(
            email="logout@example.com",
            username="logoutuser",
        )
        await cookie_client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await cookie_client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "logout@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]
        assert login_resp.cookies.get(REFRESH_COOKIE) is not None

        response = await cookie_client.post(
            f"{AUTH_PREFIX}/logout",
            headers={"Authorization": f"Bearer {token}", "Origin": SAME_ORIGIN},
        )
        assert response.status_code == 204
        set_cookie = response.headers.get("set-cookie", "")
        assert REFRESH_COOKIE in set_cookie
        assert "Max-Age=0" in set_cookie

    async def test_logout_requires_auth(self, client):
        """Logout without token returns 401."""
        response = await client.post(f"{AUTH_PREFIX}/logout")
        assert response.status_code in (401, 403)

    async def test_logout_without_origin_rejected(self, cookie_client, user_factory):
        """Logout without a trusted Origin/Referer is rejected."""
        payload = user_factory.make_payload(
            email="logoutorigin@example.com",
            username="logoutoriginuser",
        )
        await cookie_client.post(f"{AUTH_PREFIX}/register", json=payload)
        login_resp = await cookie_client.post(
            f"{AUTH_PREFIX}/login",
            json={"username": "logoutorigin@example.com", "password": "TestPass123!"},
        )
        token = login_resp.json()["access_token"]
        response = await cookie_client.post(
            f"{AUTH_PREFIX}/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401

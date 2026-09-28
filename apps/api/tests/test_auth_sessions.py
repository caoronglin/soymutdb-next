"""Docker-free unit tests for server-side refresh-token sessions.

These tests exercise the real production code path (endpoints + service)
against an in-memory fake session, following the existing unit-test style
(``tests/test_ratelimit.py``'s FakeRedis doubles).  They do **not** require
PostgreSQL/Docker, so they run in environments without Docker.

The fake session serialises ``SELECT ... FOR UPDATE`` on the refresh-token
row with an asyncio lock, which makes the concurrent-refresh test
deterministic: exactly one of two concurrent refreshes with the same token
succeeds and the loser triggers family-wide reuse revocation.

Cookie / Origin behaviour is asserted at the HTTP layer with httpx.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import Select, Update
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList
from starlette.requests import Request

os.environ.setdefault("SOYMUTDB_APP_ENV", "dev")
os.environ.setdefault("SOYMUTDB_JWT_SECRET", "test_jwt_secret_for_testing_only")
os.environ.setdefault("SOYMUTDB_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("SOYMUTDB_REFRESH_TOKEN_EXPIRE_DAYS", "1")

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.csrf import validate_request_origin  # noqa: E402
from app.core.exceptions import AuthenticationError  # noqa: E402
from app.core.security import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.models.auth import RefreshToken, User  # noqa: E402
from app.services.auth_service import auth_service  # noqa: E402

AUTH_PREFIX = "/api/v1/auth"
REFRESH_COOKIE = get_settings().refresh_cookie_name
COOKIE_PATH = "/api/v1/auth"
# httpx appends ".local" to dotless hosts in its cookie jar, so the test
# host needs a dot for cookies to round-trip.
BASE_URL = "http://test.local"
SAME_ORIGIN = "http://test.local"


# ---------------------------------------------------------------------------
# Fake session
# ---------------------------------------------------------------------------


class _ReentrantAsyncLock:
    """Reentrant asyncio lock so update statements can nest inside a held lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._depth = 0

    async def acquire(self) -> None:
        if self._depth == 0:
            await self._lock.acquire()
        self._depth += 1

    def release(self) -> None:
        if self._depth <= 0:
            return  # commit/rollback without a held row lock is legal
        self._depth -= 1
        if self._depth == 0:
            self._lock.release()


class _FakeResult:
    def __init__(self, row: object | None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object | None:
        return self._row

    def scalars(self) -> _FakeResult:
        return self

    def first(self) -> object | None:
        return self._row


def _value(node: object) -> object:
    """Resolve a BindParameter (or literal) to its Python value."""
    if isinstance(node, BindParameter):
        return node.value
    return node


def _collect(node: object, pairs: dict[str, object]) -> None:
    """Extract ``column_name -> value`` pairs from a WHERE clause tree."""
    if isinstance(node, BooleanClauseList):
        for clause in node.clauses:
            _collect(clause, pairs)
    elif isinstance(node, BinaryExpression):
        left = node.left
        name = getattr(left, "name", None)
        if name:
            pairs[name] = _value(node.right)


def _criteria_pairs(query: object) -> dict[str, object]:
    pairs: dict[str, object] = {}
    for clause in getattr(query, "_where_criteria", None) or []:
        _collect(clause, pairs)
    return pairs


def _update_values(query: Update) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in dict(getattr(query, "_values", {}) or {}).items():
        name = getattr(key, "name", None) or str(key)
        out[name] = _value(value)
    return out


class FakeAuthDB:
    """In-memory AsyncSession double backed by a dict of RefreshToken rows.

    ``SELECT ... FOR UPDATE`` on a refresh token acquires the transaction
    lock and holds it until commit/rollback, mirroring PostgreSQL row locks
    closely enough to make concurrent refresh behaviour deterministic.
    """

    def __init__(self, user: User) -> None:
        self.user = user
        self.tokens: dict[str, RefreshToken] = {}
        self.added: list[object] = []
        self.execute_calls = 0
        self.commits = 0
        self.rollbacks = 0
        self._lock = _ReentrantAsyncLock()

    # -- session API -------------------------------------------------------

    async def execute(self, query: object) -> _FakeResult:
        self.execute_calls += 1
        if isinstance(query, Select):
            entity = query.column_descriptions[0]["entity"]
            pairs = _criteria_pairs(query)
            if entity is RefreshToken:
                locked = getattr(query, "_for_update_arg", None) is not None
                if locked:
                    await self._lock.acquire()
                token_hash = pairs.get("token_hash")
                if token_hash is not None:
                    return _FakeResult(self.tokens.get(str(token_hash)))
                return _FakeResult(None)
            if entity is User:
                user_id = pairs.get("id")
                if user_id is not None:
                    if self.user is not None and str(self.user.id) == str(user_id):
                        return _FakeResult(self.user)
                    return _FakeResult(None)
                email = pairs.get("email")
                username = pairs.get("username")
                if self.user is not None and (
                    (email is not None and self.user.email == email)
                    or (username is not None and self.user.username == username)
                ):
                    return _FakeResult(self.user)
                return _FakeResult(None)
            return _FakeResult(None)

        if isinstance(query, Update):
            await self._lock.acquire()
            pairs = _criteria_pairs(query)
            values = _update_values(query)
            now = cast(datetime, values.get("revoked_at"))
            family_id = pairs.get("family_id")
            user_id = pairs.get("user_id")
            updated = 0
            for record in self.tokens.values():
                if record.revoked_at is not None:
                    continue
                if family_id is not None and str(record.family_id) == str(family_id):
                    record.revoked_at = now
                    updated += 1
                elif user_id is not None and str(record.user_id) == str(user_id):
                    record.revoked_at = now
                    updated += 1
            return _FakeResult(None, rowcount=updated)

        return _FakeResult(None)

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, RefreshToken):
            self.tokens[obj.token_hash] = obj

    async def commit(self) -> None:
        self.commits += 1
        self._lock.release()

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._lock.release()

    # -- helpers -----------------------------------------------------------

    def records(self) -> list[RefreshToken]:
        return list(self.tokens.values())


def make_user(
    username: str | None = None,
    email: str | None = None,
    password: str = "TestPass123!",
) -> User:
    """Build a usable (non-persisted) User with an explicit, unique id.

    Usernames default to a random suffix so the process-local login rate
    limiter fallback never accumulates across tests.
    """
    suffix = uuid.uuid4().hex[:8]
    username = username or f"tester_{suffix}"
    email = email or f"tester_{suffix}@example.com"
    return User(
        id=uuid.uuid4(),
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        joined_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Fixtures (docker-free app with overridden get_db)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def auth_env() -> AsyncGenerator[tuple[AsyncClient, FakeAuthDB]]:
    """Minimal app + fake session for exercising the real auth endpoints."""
    from app.core.database import get_db
    from app.main import create_app

    fake_db = FakeAuthDB(user=make_user())
    application = create_app()

    async def override_get_db() -> AsyncGenerator[FakeAuthDB]:
        yield fake_db

    application.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client, fake_db

    application.dependency_overrides.clear()


async def login(client: AsyncClient, user: User) -> Response:
    response = await client.post(
        f"{AUTH_PREFIX}/login",
        headers={"Origin": SAME_ORIGIN},
        json={"username": user.email, "password": "TestPass123!"},
    )
    assert response.status_code == 200
    return response


# ---------------------------------------------------------------------------
# Registration feature gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegistration:
    async def test_registration_disabled_before_database_work(self, auth_env, monkeypatch):
        client, db = auth_env
        from app.api.v1 import auth as auth_routes

        monkeypatch.setattr(auth_routes.settings, "feature_registration_enabled", False)
        response = await client.post(
            f"{AUTH_PREFIX}/register",
            json={
                "username": "disableduser",
                "email": "disabled@example.com",
                "password": "TestPass123!",
                "full_name": "Disabled User",
            },
        )

        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "service_unavailable"
        assert data["error"]["message"] == "Registration is currently disabled"
        assert db.execute_calls == 0


# ---------------------------------------------------------------------------
# Login cookie contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLoginCookie:
    async def test_login_returns_access_json_and_http_only_cookie(self, auth_env):
        client, _db = auth_env
        user = _db.user
        response = await login(client, user)

        data = response.json()
        assert "access_token" in data
        assert "refresh_token" not in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == get_settings().access_token_expire_minutes * 60

        set_cookie = response.headers.get("set-cookie", "")
        assert REFRESH_COOKIE in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert f"Path={COOKIE_PATH}" in set_cookie
        # dev mode: Secure is relaxed so plain-http localhost works.
        assert "Secure" not in set_cookie
        assert response.cookies.get(REFRESH_COOKIE) is not None

        # The server stored only the hash — never the plaintext.
        plaintext = response.cookies.get(REFRESH_COOKIE)
        assert plaintext is not None
        assert plaintext not in [r.token_hash for r in _db.records()]
        assert hash_refresh_token(plaintext) in _db.tokens

    async def test_login_wrong_password(self, auth_env):
        client, _db = auth_env
        response = await client.post(
            f"{AUTH_PREFIX}/login",
            headers={"Origin": SAME_ORIGIN},
            json={"username": _db.user.email, "password": "WrongPass456!"},
        )
        assert response.status_code == 401

    async def test_login_cross_origin_rejected_before_database_work(self, auth_env):
        client, db = auth_env
        response = await client.post(
            f"{AUTH_PREFIX}/login",
            headers={"Origin": "https://evil.example"},
            json={"username": db.user.email, "password": "TestPass123!"},
        )

        assert response.status_code == 401
        assert db.execute_calls == 0
        assert db.commits == 0
        assert db.records() == []


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRefreshRotation:
    async def test_refresh_rotates_token_and_revokes_old(self, auth_env):
        client, db = auth_env
        old_token = (await login(client, db.user)).cookies.get(REFRESH_COOKIE)
        assert old_token is not None

        response = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" not in data

        new_token = response.cookies.get(REFRESH_COOKIE)
        assert new_token is not None
        assert new_token != old_token

        old_rec = db.tokens[hash_refresh_token(old_token)]
        new_rec = db.tokens[hash_refresh_token(new_token)]
        assert old_rec.revoked_at is not None
        assert old_rec.replaced_by == new_rec.id
        assert new_rec.revoked_at is None
        assert new_rec.family_id == old_rec.family_id

    async def test_reuse_of_rotated_token_revokes_family(self, auth_env):
        client, db = auth_env
        old_token = (await login(client, db.user)).cookies.get(REFRESH_COOKIE)

        first = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert first.status_code == 200
        new_token = first.cookies.get(REFRESH_COOKIE)

        # Replay the rotated token — reuse detection.
        client.cookies.set(REFRESH_COOKIE, old_token, domain="test.local", path=COOKIE_PATH)
        replay = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert replay.status_code == 401
        assert all(record.revoked_at is not None for record in db.records())

        # The newest token of the family is dead as well.
        client.cookies.set(REFRESH_COOKIE, new_token, domain="test.local", path=COOKIE_PATH)
        latest = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert latest.status_code == 401

    async def test_concurrent_refresh_single_success(self, auth_env):
        """Two concurrent refreshes with the same token: exactly one succeeds."""
        client, db = auth_env
        await login(client, db.user)

        async def do_refresh() -> int:
            response = await client.post(
                f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
            )
            return response.status_code

        statuses = await asyncio.gather(do_refresh(), do_refresh())
        assert sorted(statuses) == [200, 401]
        # The losing request revoked the family as part of reuse detection.
        assert all(record.revoked_at is not None for record in db.records())

    async def test_legacy_token_without_server_record_rejected(self, auth_env):
        """A validly signed refresh token with no server record is refused."""
        client, db = auth_env
        user = db.user
        legacy = create_refresh_token(subject=str(user.id))
        client.cookies.set(REFRESH_COOKIE, legacy, domain="test.local", path=COOKIE_PATH)

        response = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 401

    async def test_missing_cookie_rejected(self, auth_env):
        client, _db = auth_env
        response = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert response.status_code == 401

    async def test_refresh_after_logout_rejected(self, auth_env):
        client, db = auth_env
        login_resp = await login(client, db.user)
        token = login_resp.json()["access_token"]

        logout_resp = await client.post(
            f"{AUTH_PREFIX}/logout",
            headers={"Authorization": f"Bearer {token}", "Origin": SAME_ORIGIN},
        )
        assert logout_resp.status_code == 204
        assert all(record.revoked_at is not None for record in db.records())

        refresh_resp = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": SAME_ORIGIN}
        )
        assert refresh_resp.status_code == 401


# ---------------------------------------------------------------------------
# Origin / Referer validation (CSRF)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOriginValidation:
    async def test_refresh_without_origin_rejected(self, auth_env):
        client, db = auth_env
        await login(client, db.user)
        response = await client.post(f"{AUTH_PREFIX}/refresh")
        assert response.status_code == 401

    async def test_refresh_cross_origin_rejected(self, auth_env):
        client, db = auth_env
        await login(client, db.user)
        response = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 401

    async def test_refresh_with_referer_allowed(self, auth_env):
        client, db = auth_env
        await login(client, db.user)
        response = await client.post(
            f"{AUTH_PREFIX}/refresh", headers={"Referer": f"{SAME_ORIGIN}/app"}
        )
        assert response.status_code == 200

    async def test_logout_without_origin_rejected_and_family_intact(self, auth_env):
        client, db = auth_env
        login_resp = await login(client, db.user)
        token = login_resp.json()["access_token"]
        response = await client.post(
            f"{AUTH_PREFIX}/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401
        assert all(record.revoked_at is None for record in db.records())

    async def test_logout_cross_origin_rejected(self, auth_env):
        client, db = auth_env
        login_resp = await login(client, db.user)
        token = login_resp.json()["access_token"]
        response = await client.post(
            f"{AUTH_PREFIX}/logout",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://evil.example",
            },
        )
        assert response.status_code == 401


# -- pure unit checks for the CSRF helper (no app needed) --------------------


class TestOriginValidationUnit:
    @staticmethod
    def _request(headers: dict[str, str]) -> Request:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/refresh",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ],
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "server": ("test", 80),
        }
        return Request(scope)

    def test_unit_missing_origin_rejected(self):
        settings = Settings(app_env="dev")
        with pytest.raises(AuthenticationError):
            validate_request_origin(self._request({}), settings)

    def test_unit_same_origin_allowed(self):
        settings = Settings(app_env="dev")
        validate_request_origin(self._request({"Origin": "http://test"}), settings)

    def test_unit_cors_origin_allowed(self):
        settings = Settings(
            app_env="dev", cors_origins=["https://app.example.com"]
        )
        validate_request_origin(
            self._request({"Origin": "https://app.example.com"}), settings
        )

    def test_unit_evil_origin_rejected(self):
        settings = Settings(app_env="dev")
        with pytest.raises(AuthenticationError):
            validate_request_origin(
                self._request({"Origin": "https://evil.example"}), settings
            )

    def test_unit_referer_allowed(self):
        settings = Settings(app_env="dev")
        validate_request_origin(
            self._request({"Referer": "http://test/some/page"}), settings
        )

    def test_unit_malformed_referer_rejected(self):
        settings = Settings(app_env="dev")
        with pytest.raises(AuthenticationError):
            validate_request_origin(
                self._request({"Referer": "not-a-url"}), settings
            )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLogout:
    async def test_logout_revokes_family_and_clears_cookie(self, auth_env):
        client, db = auth_env
        login_resp = await login(client, db.user)
        token = login_resp.json()["access_token"]

        response = await client.post(
            f"{AUTH_PREFIX}/logout",
            headers={"Authorization": f"Bearer {token}", "Origin": SAME_ORIGIN},
        )
        assert response.status_code == 204
        assert all(record.revoked_at is not None for record in db.records())
        set_cookie = response.headers.get("set-cookie", "")
        assert REFRESH_COOKIE in set_cookie
        assert "Max-Age=0" in set_cookie

    async def test_logout_without_refresh_cookie_still_clears(self, auth_env):
        client, db = auth_env
        user = db.user
        token = create_access_token(subject=str(user.id))
        response = await client.post(
            f"{AUTH_PREFIX}/logout",
            headers={"Authorization": f"Bearer {token}", "Origin": SAME_ORIGIN},
        )
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# Password change revokes every family
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPasswordChange:
    async def test_change_password_revokes_all_families(self, auth_env):
        client, db = auth_env
        user = db.user
        await auth_service.issue_refresh_token(db, user.id)
        await auth_service.issue_refresh_token(db, user.id)
        await db.commit()
        assert len(db.records()) == 2

        access = create_access_token(subject=str(user.id))
        response = await client.post(
            f"{AUTH_PREFIX}/change-password",
            headers={"Authorization": f"Bearer {access}"},
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 204
        assert all(record.revoked_at is not None for record in db.records())


# ---------------------------------------------------------------------------
# Service-level behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAuthService:
    async def test_revoke_all_user_tokens_counts_and_idempotent(self, auth_env):
        _client, db = auth_env
        user = db.user
        for _ in range(3):
            await auth_service.issue_refresh_token(db, user.id)
        await db.commit()

        revoked = await auth_service.revoke_all_user_tokens(db, user.id)
        assert revoked == 3
        assert all(record.revoked_at is not None for record in db.records())

        again = await auth_service.revoke_all_user_tokens(db, user.id)
        assert again == 0

    async def test_revoke_token_family_by_token_scoped_to_family(self, auth_env):
        _client, db = auth_env
        user = db.user
        token_a = await auth_service.issue_refresh_token(db, user.id)
        token_b = await auth_service.issue_refresh_token(db, user.id)
        await db.commit()

        family = await auth_service.revoke_token_family_by_token(db, token_a)
        assert family is not None
        assert family == db.tokens[hash_refresh_token(token_a)].family_id
        assert db.tokens[hash_refresh_token(token_a)].revoked_at is not None
        # Different family stays alive.
        assert db.tokens[hash_refresh_token(token_b)].revoked_at is None

    async def test_revoke_unknown_token_returns_none(self, auth_env):
        _client, db = auth_env
        assert await auth_service.revoke_token_family_by_token(db, "garbage") is None


# ---------------------------------------------------------------------------
# Cookie configuration
# ---------------------------------------------------------------------------


class TestRefreshCookieConfig:
    def test_defaults(self):
        settings = Settings(app_env="dev")
        assert settings.refresh_cookie_name == "soymutdb_refresh"
        assert settings.refresh_cookie_path == "/api/v1/auth"
        assert settings.refresh_cookie_samesite == "lax"

    def test_dev_secure_relaxed(self):
        settings = Settings(app_env="dev")
        assert settings.refresh_cookie_secure_effective is False

    def test_prod_secure_enforced(self):
        settings = Settings(
            app_env="prod",
            database_url="postgresql+asyncpg://u:p@db.example.com/soymutdb",
            redis_url="redis://redis.example.com:6379/0",
            s3_endpoint="https://s3.example.com",
            s3_access_key="test-access-key",
            s3_secret_key="test-secret-key",
            jwt_secret="prod-jwt-secret-that-is-longer-than-32-characters",
            analytics_ip_salt="production-analytics-ip-salt-at-least-32-characters",
            cors_origins=["https://app.example.com"],
        )
        assert settings.refresh_cookie_secure_effective is True

    def test_explicit_override_wins(self):
        settings = Settings(app_env="dev", refresh_cookie_secure=True)
        assert settings.refresh_cookie_secure_effective is True

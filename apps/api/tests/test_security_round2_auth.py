"""Security regression tests, round 2 — AuthN/AuthZ negative cases.

Every test here is a *negative* case: the assertion is that a request which
must fail does fail.  Together they pin the fail-closed contract of
``app/core/security.py``, ``app/api/v1/deps.py``, ``app/api/v1/auth.py`` and
``app/services/auth_service.py``:

- a soft-deleted, disabled or unknown account can never complete a login and
  can never keep an already-issued access token working;
- JWTs are rejected when expired, tampered with, signed with another key,
  minted with ``alg: none``, or of the wrong token type (refresh <-> access
  confusion);
- RBAC denies anonymous callers with 401 and authenticated non-owners with 403,
  and admin routes never fail open;
- rejected credential routes are marked ``private, no-store`` so an
  existence oracle can never be cached by a shared proxy.

Database-backed tests need ``SOYMUTDB_TEST_DATABASE_URL`` (see
``tests/conftest.py``); the token/CSRF tests that use a fake session do not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core import security as security_module
from app.core.security import RoleName, create_access_token, hash_password
from app.models.auth import Role, User

AUTH_PREFIX = "/api/v1/auth"
ANALYTICS_SUMMARY_PATH = "/api/v1/admin/analytics/summary"
TRUSTED_ORIGIN = "http://test"
EVIL_ORIGIN = "https://evil.example.com"


class _Result:
    """Minimal ``AsyncSession.execute`` result stand-in."""

    def __init__(self, rows: list[User]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> User | None:
        return self._rows[0] if self._rows else None


class SingleUserDbSession:
    """AsyncSession stand-in that resolves exactly one user, by login key.

    The real :class:`~app.models.auth.User` row is returned for both the email
    and the username lookup, which is all ``POST /auth/login`` needs.
    """

    def __init__(self, user: User) -> None:
        self.user = user
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        text = str(stmt)
        if "FROM users" in text:
            return _Result([self.user])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _make_user(
    *,
    role: RoleName = RoleName.RESEARCHER,
    is_active: bool = True,
    is_deleted: bool = False,
    is_superuser: bool = False,
    password: str = "Sup3rSecret!x",
) -> User:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return User(
        id=uuid.uuid4(),
        username="sec2-tester",
        email="sec2-tester@soymutdb.local",
        password_hash=hash_password(password),
        is_active=is_active,
        is_deleted=is_deleted,
        is_superuser=is_superuser,
        role_rel=Role(id=1, name=role.value),
        joined_at=now,
        created_at=now,
        updated_at=now,
    )


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _auth_app(user: User | None) -> FastAPI:
    """Minimal app: full v1 router, one canned user, real security handlers."""
    from app.api.v1.router import api_router
    from app.core.database import get_db
    from app.core.exceptions import (
        HTTPException,
        SoyMutDBError,
        http_exception_handler,
        soy_mut_db_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )

    application = FastAPI(title="SoyMutDB security round-2 probe")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)

    async def override_get_db():
        yield SingleUserDbSession(user) if user is not None else SingleUserDbSession(
            _make_user()
        )

    application.dependency_overrides[get_db] = override_get_db
    return application


async def _login(client: AsyncClient, **overrides: object):
    body: dict[str, object] = {
        "username": "sec2-tester@soymutdb.local",
        "password": "Sup3rSecret!x",
    }
    body.update(overrides)
    return await client.post(
        f"{AUTH_PREFIX}/login",
        json=body,
        headers={"Origin": TRUSTED_ORIGIN},
    )


# ---------------------------------------------------------------------------
# Login must fail closed for disabled / soft-deleted accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_deleted_account_cannot_log_in() -> None:
    """A soft-deleted row is still a live password hash; login must refuse it.

    ``get_current_user`` and ``rotate_refresh_token`` both reject
    ``is_deleted`` rows, so accepting the credential here would still mint a
    session that every subsequent request refuses — and would record a
    successful ``login`` audit entry for an account the operator deleted.
    """
    deleted = _make_user(is_deleted=True)
    transport = ASGITransport(app=_auth_app(deleted))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _login(client)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert "access_token" not in response.json()


@pytest.mark.asyncio
async def test_disabled_account_cannot_log_in() -> None:
    """``is_active=False`` is refused before a token is minted."""
    disabled = _make_user(is_active=False)
    transport = ASGITransport(app=_auth_app(disabled))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _login(client)

    assert response.status_code == 401
    assert "access_token" not in response.json()


@pytest.mark.asyncio
async def test_login_response_never_carries_the_refresh_token() -> None:
    """The refresh session stays in the HttpOnly cookie, never in JSON."""
    user = _make_user()
    transport = ASGITransport(app=_auth_app(user))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _login(client)

    assert response.status_code == 200
    body = response.json()
    assert "refresh_token" not in body
    # Only the cookie carries it, and it is HttpOnly + path-scoped.
    assert "soymutdb_refresh" in response.cookies
    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "Path=/api/v1/auth" in set_cookie


# ---------------------------------------------------------------------------
# JWT verification negative cases (no database required)
# ---------------------------------------------------------------------------


def _settings_secret() -> str:
    from app.core.config import get_settings

    return get_settings().jwt_secret


def _algorithm() -> str:
    from app.core.config import get_settings

    return get_settings().jwt_algorithm


def test_expired_access_token_is_rejected() -> None:
    expired = create_access_token(
        subject=str(uuid.uuid4()), expires_delta=timedelta(minutes=-1)
    )
    with pytest.raises(ValueError):
        security_module.decode_token(expired)


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "a-completely-different-signing-secret",
        algorithm="HS256",
    )
    with pytest.raises(ValueError):
        security_module.decode_token(forged)


def test_unsigned_alg_none_token_is_rejected() -> None:
    """``alg: none`` is the classic JWT downgrade; PyJWT must refuse it."""
    unsigned = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(ValueError):
        security_module.decode_token(unsigned)


def test_tampered_role_claim_invalidates_the_signature() -> None:
    """Escalating ``roles`` in place breaks verification, not just parsing."""
    import base64
    import json as json_

    token = create_access_token(
        subject=str(uuid.uuid4()),
        extra={"roles": [RoleName.VIEWER.value]},
    )
    _header, payload, signature = token.split(".")

    def decode(segment: str) -> dict:
        padding = "=" * (-len(segment) % 4)
        return json_.loads(base64.urlsafe_b64decode(segment + padding))

    def encode(claims: dict) -> str:
        raw = json_.dumps(claims, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    claims = decode(payload)
    claims["roles"] = [RoleName.ADMINISTRATOR.value]
    forged_body = encode(claims)

    assert forged_body != payload
    assert decode(forged_body)["roles"] == [RoleName.ADMINISTRATOR.value]
    # Same signing key, so only the HMAC stands between the two payloads.
    with pytest.raises(ValueError):
        security_module.decode_token(f"{_header}.{forged_body}.{signature}")
    # The untampered token still verifies.
    assert security_module.decode_token(token)["sub"]


@pytest.mark.asyncio
async def test_refresh_token_cannot_be_used_as_an_access_token() -> None:
    """Token-type confusion: the ``type`` claim is enforced at the boundary."""
    refresh = security_module.create_refresh_token(subject=str(uuid.uuid4()))
    transport = ASGITransport(app=_auth_app(_make_user()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"{AUTH_PREFIX}/me",
            headers={"Authorization": f"Bearer {refresh}"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_token_is_not_accepted_as_a_refresh_session() -> None:
    """An access JWT carries no refresh-token row, so rotation must fail."""
    access = create_access_token(subject=str(uuid.uuid4()))
    transport = ASGITransport(app=_auth_app(_make_user()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{AUTH_PREFIX}/refresh",
            headers={"Origin": TRUSTED_ORIGIN},
            cookies={"soymutdb_refresh": access},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_and_malformed_authorization_headers_are_rejected() -> None:
    transport = ASGITransport(app=_auth_app(_make_user()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        absent = await client.get(f"{AUTH_PREFIX}/me")
        wrong_scheme = await client.get(
            f"{AUTH_PREFIX}/me", headers={"Authorization": "Basic abc123"}
        )
        garbage = await client.get(
            f"{AUTH_PREFIX}/me", headers={"Authorization": "Bearer not-a-jwt"}
        )

    for response in (absent, wrong_scheme, garbage):
        assert response.status_code == 401
        # A credentialed rejection must never be cached by a shared proxy.
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_disabled_account_loses_access_to_an_already_issued_token() -> None:
    """AuthN is re-checked against the row on every request, not just login."""
    user = _make_user()
    transport = ASGITransport(app=_auth_app(user))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get(f"{AUTH_PREFIX}/me", headers=_bearer(user))
        user.is_active = False
        refused = await client.get(f"{AUTH_PREFIX}/me", headers=_bearer(user))

    assert allowed.status_code == 200
    assert refused.status_code == 401


@pytest.mark.asyncio
async def test_soft_deleted_account_loses_access_to_an_already_issued_token() -> None:
    user = _make_user()
    transport = ASGITransport(app=_auth_app(user))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get(f"{AUTH_PREFIX}/me", headers=_bearer(user))
        user.is_deleted = True
        refused = await client.get(f"{AUTH_PREFIX}/me", headers=_bearer(user))

    assert allowed.status_code == 200
    assert refused.status_code == 401


# ---------------------------------------------------------------------------
# RBAC: admin routes fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/v1/admin/audit-logs", None),
        ("get", "/api/v1/admin/dashboard-stats", None),
        ("get", "/api/v1/admin/settings/site-brand", None),
        ("get", "/api/v1/admin/news", None),
        (
            "post",
            "/api/v1/admin/uploads/presign",
            {
                "filename": "cover.png",
                "purpose": "news",
                "size": 1024,
                "content_type": "image/png",
                "checksum_sha256": "ab" * 32,
            },
        ),
    ],
)
async def test_admin_routes_reject_anonymous_callers(
    method: str, path: str, payload: dict | None
) -> None:
    transport = ASGITransport(app=_auth_app(_make_user()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/api/v1/admin/audit-logs", None),
        ("get", "/api/v1/admin/dashboard-stats", None),
        ("get", "/api/v1/admin/news", None),
        ("get", ANALYTICS_SUMMARY_PATH, None),
        (
            "post",
            "/api/v1/admin/uploads/presign",
            {
                "filename": "cover.png",
                "purpose": "news",
                "size": 1024,
                "content_type": "image/png",
                "checksum_sha256": "ab" * 32,
            },
        ),
    ],
)
async def test_admin_routes_reject_authenticated_non_owners(
    method: str, path: str, payload: dict | None
) -> None:
    """A logged-in viewer must be denied, not silently allowed."""
    viewer = _make_user(role=RoleName.VIEWER)
    transport = ASGITransport(app=_auth_app(viewer))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            method, path, json=payload, headers=_bearer(viewer)
        )

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"


def test_role_grants_do_not_leak_across_domains() -> None:
    """A content editor is not implicitly a track manager, and vice versa."""
    assert security_module.has_role(
        [RoleName.CONTENT_EDITOR.value], RoleName.CONTENT_EDITOR
    )
    assert not security_module.has_role(
        [RoleName.CONTENT_EDITOR.value], RoleName.TRACK_MANAGER
    )
    assert not security_module.has_role(
        [RoleName.TRACK_MANAGER.value], RoleName.ADMINISTRATOR
    )
    # An unknown role string is ignored rather than treated as privileged.
    assert not security_module.has_role(["root"], RoleName.ADMINISTRATOR)
    assert not security_module.has_role([], RoleName.ADMINISTRATOR)


def test_require_admin_roles_raises_for_non_administrators() -> None:
    from app.core.exceptions import AuthorizationError

    with pytest.raises(AuthorizationError):
        security_module.require_admin_roles([RoleName.CURATOR.value])
    with pytest.raises(AuthorizationError):
        security_module.require_admin_roles([])
    security_module.require_admin_roles([RoleName.ADMINISTRATOR.value])


# ---------------------------------------------------------------------------
# CSRF / Origin verification on cookie-authenticated auth routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"{AUTH_PREFIX}/login"),
        ("post", f"{AUTH_PREFIX}/refresh"),
        ("post", f"{AUTH_PREFIX}/logout"),
    ],
)
async def test_cookie_auth_routes_reject_untrusted_origins(
    method: str, path: str
) -> None:
    user = _make_user()
    transport = ASGITransport(app=_auth_app(user))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await getattr(client, method)(
            path,
            headers={"Origin": EVIL_ORIGIN},
            json={"username": "sec2-tester@soymutdb.local", "password": "Sup3rSecret!x"},
            cookies={"soymutdb_refresh": "whatever"},
        )
        missing = await getattr(client, method)(
            path,
            json={"username": "sec2-tester@soymutdb.local", "password": "Sup3rSecret!x"},
            cookies={"soymutdb_refresh": "whatever"},
        )

    assert rejected.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_untrusted_referer_is_rejected_on_refresh() -> None:
    """Referer is the documented fallback, so it must be checked too."""
    user = _make_user()
    transport = ASGITransport(app=_auth_app(user))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"{AUTH_PREFIX}/refresh",
            headers={"Referer": f"{EVIL_ORIGIN}/search?q=x"},
            cookies={"soymutdb_refresh": "whatever"},
        )

    assert response.status_code == 401


def test_origin_matching_is_exact_not_suffix_based() -> None:
    """``evil-app.example.com`` must not inherit ``app.example.com``."""
    from app.core.csrf import _is_trusted_origin

    settings = SimpleNamespace(cors_origins=["https://app.example.com"])
    request = SimpleNamespace(
        url=SimpleNamespace(scheme="https", netloc="api.example.com")
    )

    assert _is_trusted_origin("https://app.example.com", request, settings)
    assert _is_trusted_origin("https://api.example.com", request, settings)
    assert not _is_trusted_origin(
        "https://evil-app.example.com", request, settings
    )
    assert not _is_trusted_origin("https://app.example.com.evil.test", request, settings)
    assert not _is_trusted_origin("http://app.example.com", request, settings)


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------


def test_password_policy_rejects_weak_passwords() -> None:
    for weak in ("short1!", "password", "alllowercase1", "ALLUPPERCASE1"):
        valid, _reason = security_module.validate_password_strength(weak)
        assert valid is False, weak
    valid, reason = security_module.validate_password_strength("Sup3rSecret!x")
    assert valid is True
    assert reason == "OK"


def test_password_verification_never_raises_on_a_corrupt_hash() -> None:
    """A malformed stored hash must fail the login, not crash the handler."""
    assert security_module.verify_password("anything", "not-an-argon2-hash") is False

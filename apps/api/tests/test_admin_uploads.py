"""Admin upload presign tests (D4) — no docker / no testcontainers.

Covers:
- object-key construction / validation / public URL helpers (pure functions)
- HTTP layer: RBAC (401 / 403 / 200) and the presign response contract

The presigned PUT URL itself is mocked (no real S3 in unit tests).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    SoyMutDBError,
    http_exception_handler,
    soy_mut_db_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User

from tests.test_news_api import FakeDbSession  # reuse the news fake session


def _make_user(role: RoleName = RoleName.RESEARCHER) -> User:
    return User(
        id=uuid.uuid4(),
        username="tester",
        email="tester@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=Role(id=1, name=role.value),
    )


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def api_app():
    """Minimal app with the full v1 router and a fake DB session."""
    from app.api.v1.router import api_router
    from app.core.database import get_db

    session = FakeDbSession(user=None)

    async def override_get_db():
        yield session

    application = FastAPI(title="Uploads Test API")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, http_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.dependency_overrides[get_db] = override_get_db
    application.state.fake_session = session
    return application


@pytest.fixture
async def api_client(api_app):
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Pure helpers (app.services.presign uploads namespace)
# ---------------------------------------------------------------------------


class TestUploadsKey:
    def test_build_uploads_key_shape(self):
        from app.services.presign import build_uploads_key

        key = build_uploads_key("news", "my-cover.jpg")
        prefix, purpose, rest = key.split("/", 2)
        assert prefix == "uploads"
        assert purpose == "news"
        # uuid-<sanitized-name>: uuid contributes hyphens, name is kept
        assert rest.endswith("-my-cover.jpg")
        assert rest.count("-") >= 2

    def test_build_uploads_key_sanitizes(self):
        from app.services.presign import build_uploads_key

        key = build_uploads_key("News!", "../evil file?.png")
        assert key.startswith("uploads/news/")
        assert "/evil" not in key
        assert key.endswith("-evil-file-.png")

    def test_validate_uploads_key_rejects_outside_namespace(self):
        from app.services.presign import validate_uploads_key

        with pytest.raises(ValueError):
            validate_uploads_key("analyses/x.jpg")
        with pytest.raises(ValueError):
            validate_uploads_key("uploads-evil/x.jpg")
        with pytest.raises(ValueError):
            validate_uploads_key("uploads/../x.jpg")

    def test_validate_uploads_key_accepts_valid(self):
        from app.services.presign import build_uploads_key, validate_uploads_key

        key = build_uploads_key("news", "a.png")
        assert validate_uploads_key(key) == key

    def test_generate_public_url(self):
        from app.services.presign import build_uploads_key, generate_public_url

        key = build_uploads_key("news", "a.png")
        url = generate_public_url(key)
        assert url == f"http://localhost:8080/files/{key}"
        # trailing slash on the base is tolerated
        assert generate_public_url("uploads/x.png").startswith(
            "http://localhost:8080/files/uploads/x.png"
        )


# ---------------------------------------------------------------------------
# HTTP layer: RBAC + response contract
# ---------------------------------------------------------------------------


class TestAdminUploadsEndpoint:
    async def test_unauthenticated_401(self, api_client):
        r = await api_client.post(
            "/api/v1/admin/uploads/presign",
            json={"filename": "a.png", "purpose": "news"},
        )
        assert r.status_code == 401

    async def test_viewer_403(self, api_client, api_app):
        user = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/admin/uploads/presign",
            json={"filename": "a.png", "purpose": "news"},
            headers=_auth_header(user),
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_researcher_presign_200(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        fake_url = "http://minio:9000/public/uploads/news/abc.png"
        with patch(
            "app.api.v1.admin_uploads.generate_upload_url",
            return_value=fake_url,
        ) as mocked:
            r = await api_client.post(
                "/api/v1/admin/uploads/presign",
                json={"filename": "cover.png", "purpose": "news"},
                headers=_auth_header(user),
            )
        assert r.status_code == 200
        body = r.json()
        assert body["upload_url"] == fake_url
        assert body["object_key"].startswith("uploads/news/")
        assert body["public_url"] == (
            f"http://localhost:8080/files/{body['object_key']}"
        )
        assert body["expires_in"] > 0
        # The upload goes to the PUBLIC bucket (news covers are public).
        kwargs = mocked.call_args.kwargs
        assert kwargs["bucket"] == "genomic-data"

    async def test_unusable_filename_rejected_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        # ".." is a traversal segment — sanitize_filename rejects it.
        r = await api_client.post(
            "/api/v1/admin/uploads/presign",
            json={"filename": "..", "purpose": "news"},
            headers=_auth_header(user),
        )
        assert r.status_code == 422

    async def test_missing_filename_422(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/admin/uploads/presign",
            json={"purpose": "news"},
            headers=_auth_header(user),
        )
        assert r.status_code == 422

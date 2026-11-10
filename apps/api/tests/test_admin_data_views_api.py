"""Authorization boundary for the saved data-view endpoints.

The persistence and vocabulary rules are covered in ``test_data_views.py``.
These tests pin the admin-only promise of the HTTP surface itself: an
unauthenticated caller is rejected before any query, and a signed-in viewer
cannot read or write saved views.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.api.v1.admin_data_views import router
from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)


def _user(role: str, *, superuser: bool = False):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = superuser
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = role
    return user


def _session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    return application


@pytest.fixture
def session() -> MagicMock:
    return _session()


@pytest.fixture
async def client(app: FastAPI, session: MagicMock):
    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _as(application: FastAPI, user) -> None:
    from app.api.v1.deps import get_current_user

    application.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.asyncio
async def test_missing_credentials_are_rejected_before_touching_the_database(
    client: AsyncClient, session: MagicMock
) -> None:
    response = await client.get("/api/v1/admin/data-views")

    assert response.status_code == 401
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_cannot_read_saved_views(
    client: AsyncClient, app: FastAPI, session: MagicMock
) -> None:
    _as(app, _user("viewer"))

    for path in ("/api/v1/admin/data-views", "/api/v1/admin/data-views/sources"):
        response = await client.get(path)
        assert response.status_code == 403, path
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_viewer_cannot_create_a_saved_view(
    client: AsyncClient, app: FastAPI, session: MagicMock
) -> None:
    _as(app, _user("viewer"))

    response = await client.post(
        "/api/v1/admin/data-views",
        json={
            "name": "Gene locus",
            "source": "genes",
            "view_type": "grid",
            "visible_fields": ["gene_id"],
        },
    )

    assert response.status_code == 403
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_administrator_can_list_sources_without_a_database_query(
    client: AsyncClient, app: FastAPI
) -> None:
    _as(app, _user("administrator"))

    response = await client.get("/api/v1/admin/data-views/sources")

    assert response.status_code == 200
    assert [item["source"] for item in response.json()["items"]] == [
        "genes",
        "variants",
        "mutant_lines",
    ]


@pytest.mark.asyncio
async def test_include_hidden_is_forwarded_to_the_service(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(app, _user("administrator"))
    seen: dict[str, object] = {}

    async def _fake_list_views(_db, *, source=None, include_hidden=False):
        seen["source"] = source
        seen["include_hidden"] = include_hidden
        return []

    monkeypatch.setattr("app.api.v1.admin_data_views.service.list_views", _fake_list_views)

    response = await client.get("/api/v1/admin/data-views?include_hidden=true")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert seen == {"source": None, "include_hidden": True}


@pytest.mark.asyncio
async def test_include_hidden_is_withheld_by_default(
    client: AsyncClient, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(app, _user("administrator"))
    seen: dict[str, object] = {}

    async def _fake_list_views(_db, *, source=None, include_hidden=False):
        seen["include_hidden"] = include_hidden
        return []

    monkeypatch.setattr("app.api.v1.admin_data_views.service.list_views", _fake_list_views)

    response = await client.get("/api/v1/admin/data-views")

    assert response.status_code == 200
    assert seen == {"include_hidden": False}


@pytest.mark.asyncio
async def test_include_hidden_must_be_a_boolean(client: AsyncClient, app: FastAPI) -> None:
    _as(app, _user("administrator"))

    response = await client.get("/api/v1/admin/data-views?include_hidden=maybe")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_source_filter_is_rejected(client: AsyncClient, app: FastAPI) -> None:
    _as(app, _user("administrator"))

    response = await client.get("/api/v1/admin/data-views?source=users")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_viewer_cannot_delete_a_saved_view(
    client: AsyncClient, app: FastAPI, session: MagicMock
) -> None:
    _as(app, _user("viewer"))

    response = await client.delete("/api/v1/admin/data-views/1")

    assert response.status_code == 403
    session.execute.assert_not_awaited()

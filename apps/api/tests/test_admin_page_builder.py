"""Tests for the Admin Page Builder service and API.

Service-level tests exercise the versioned create/edit/publish lifecycle
against the real test database (``db_session``), while API-level tests use a
mocked ``get_current_user`` dependency to assert RBAC and HTTP behaviour
without spawning a full auth handshake.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.models.page_builder import (
    PageDefinitionStatus,
)
from app.page_builder import service as page_service


def _valid_definition(content: str = "hello") -> dict:
    return {
        "root": {
            "type": "rich_text",
            "props": {"content": f"<p>{content}</p>"},
        }
    }


def _editor() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_page_creates_first_draft(db_session):
    page, version = await page_service.create_page(
        db_session,
        route="/about-us",
        title_key="nav.about",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    assert page.route == "/about-us"
    assert version.version == 1
    assert version.status == PageDefinitionStatus.DRAFT
    assert version.definition["root"]["type"] == "rich_text"


@pytest.mark.asyncio
async def test_published_versions_are_immutable(db_session):
    _page, v1 = await page_service.create_page(
        db_session,
        route="/immutable",
        title_key="nav.immutable",
        definition=_valid_definition("v1"),
        edited_by=_editor(),
    )
    # Publish v1.
    _p, published, event = await page_service.publish_request(
        db_session,
        page_id=_page.id,
        version_id=v1.id,
        reason="first publish",
        edited_by=_editor(),
    )
    assert published.status == PageDefinitionStatus.REQUESTED
    assert event.event_type == "static_publish_requested"

    # Simulate the publication pipeline marking it published.
    await page_service.publish_version(db_session, published)
    assert published.status == PageDefinitionStatus.PUBLISHED

    # A fresh edit must create a NEW draft version, leaving v1 untouched.
    _p2, v2 = await page_service.update_draft(
        db_session,
        page_id=_page.id,
        base_version=published.version,
        definition=_valid_definition("v2"),
        edit_comment=None,
        edited_by=_editor(),
    )
    assert v2.version == published.version + 1
    assert v2.status == PageDefinitionStatus.DRAFT

    # v1's definition is unchanged.
    fresh_v1 = await page_service.get_version(db_session, _page.id, v1.id)
    assert fresh_v1.definition["root"]["props"]["content"] == "<p>v1</p>"


@pytest.mark.asyncio
async def test_optimistic_conflict_returns_409(db_session):
    page, v1 = await page_service.create_page(
        db_session,
        route="/conflict",
        title_key="nav.conflict",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    with pytest.raises(ConflictError):
        # base_version 3 does not match the actual latest version 1.
        await page_service.update_draft(
            db_session,
            page_id=page.id,
            base_version=3,
            definition=_valid_definition("stale"),
            edit_comment=None,
            edited_by=_editor(),
        )


@pytest.mark.asyncio
async def test_create_page_rejects_duplicate_route_and_reserved(db_session):
    await page_service.create_page(
        db_session,
        route="/unique",
        title_key="nav.unique",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    with pytest.raises(ConflictError):
        await page_service.create_page(
            db_session,
            route="/unique",
            title_key="nav.dup",
            definition=_valid_definition(),
            edited_by=_editor(),
        )
    with pytest.raises(ValidationError):
        await page_service.create_page(
            db_session,
            route="/blast",
            title_key="nav.blast",
            definition=_valid_definition(),
            edited_by=_editor(),
        )


@pytest.mark.asyncio
async def test_preview_validates_without_persisting(db_session):
    page, v1 = await page_service.create_page(
        db_session,
        route="/preview",
        title_key="nav.preview",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    result = await page_service.preview(
        db_session,
        page_id=page.id,
        route=None,
        definition=_valid_definition("preview content"),
    )
    assert result["version_preview"] == 2  # latest is 1, preview would be 2
    assert result["definition"]["root"]["props"]["content"] == "<p>preview content</p>"

    # No new version row was created.
    versions = await page_service.get_versions(db_session, page.id)
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_publish_request_emits_outbox_event(db_session):
    page, v1 = await page_service.create_page(
        db_session,
        route="/publish-me",
        title_key="nav.publish",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    _p, version, event = await page_service.publish_request(
        db_session,
        page_id=page.id,
        version_id=v1.id,
        reason="go live",
        edited_by=_editor(),
    )
    assert event.event_type == "static_publish_requested"
    assert event.payload["route"] == "/publish-me"
    assert event.payload["version"] == 1
    assert version.status == PageDefinitionStatus.REQUESTED


@pytest.mark.asyncio
async def test_publish_request_rejects_invalid_definition(db_session):
    page, v1 = await page_service.create_page(
        db_session,
        route="/bad-def",
        title_key="nav.baddef",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    # Corrupt the stored definition then try to publish — it must be rejected.
    v1.definition = {"root": {"type": "evil", "props": {}}}
    await db_session.commit()
    with pytest.raises(ValidationError):
        await page_service.publish_request(
            db_session,
            page_id=page.id,
            version_id=v1.id,
            reason=None,
            edited_by=_editor(),
        )


# ---------------------------------------------------------------------------
# API level (mocked auth)
# ---------------------------------------------------------------------------


def _make_mock_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    default_result = MagicMock()
    default_result.scalars.return_value.all.return_value = []
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


def _admin_user():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.is_superuser = True
    user.is_active = True
    user.is_deleted = False
    user.role_rel = MagicMock()
    user.role_rel.name = "administrator"
    return user


def _build_client(app, session, user):
    from fastapi import FastAPI

    from app.api.v1.router import api_router
    from app.core.database import get_db
    from app.core.exceptions import SoyMutDBError, soy_mut_db_exception_handler

    application = FastAPI()
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.include_router(api_router, prefix="/api/v1")

    async def override_db():
        yield session

    async def override_user():
        return user

    application.dependency_overrides[get_db] = override_db
    from app.api.v1.deps import get_current_user

    application.dependency_overrides[get_current_user] = override_user
    return application


@pytest.mark.asyncio
async def test_registry_endpoint_is_admin_only_and_lists_components(app, client):
    # Without a user (dependency override not set), the endpoint requires auth.
    from httpx import ASGITransport, AsyncClient

    session = _make_mock_session()
    application = _build_client(app, session, _admin_user())
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/admin/page-builder/registry")
    assert resp.status_code == 200
    data = resp.json()["components"]
    assert len(data) >= 16


@pytest.mark.asyncio
async def test_admin_endpoints_deny_non_admin(db_session):
    # A viewer user must be rejected (403) on admin page-builder endpoints.
    from httpx import ASGITransport, AsyncClient

    viewer = MagicMock()
    viewer.id = uuid.uuid4()
    viewer.is_superuser = False
    viewer.is_active = True
    viewer.is_deleted = False
    viewer.role_rel = MagicMock()
    viewer.role_rel.name = "viewer"

    application = _build_client(None, db_session, viewer)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/admin/page-builder/pages")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Seed data integrity (DB-free)
# ---------------------------------------------------------------------------


def test_seed_has_five_navigation_items_and_seven_pages():
    from app.page_builder.registry import validate_definition
    from app.scripts.seed_page_builder import NAV_ITEMS, SEED_PAGES

    assert len(NAV_ITEMS) == 5
    labels = [i["label"] for i in NAV_ITEMS]
    assert labels == ["Home", "Search", "Tools", "Latest News", "Contact"]

    assert len(SEED_PAGES) == 7
    routes = [r for r, _t, _d in SEED_PAGES]
    # BLAST and JBrowse routes are reserved, never seeded as generic pages.
    assert "/blast" not in routes
    assert "/browser" not in routes

    # Every seed definition must pass the registry.
    for route, title_key, definition in SEED_PAGES:
        validate_definition({**definition, "title_key": title_key})

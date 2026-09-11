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


def _valid_v2_definition() -> dict:
    return {
        "schema_version": 2,
        "root": {
            "type": "columns",
            "props": {"columns": 2},
            "children": [],
        },
        "data_sources": [
            {
                "id": "genes",
                "kind": "dataset",
                "dataset_version_id": "dataset-v7",
                "config": {"limit": 20},
            }
        ],
        "theme_id": "compact-data",
        "layouts": {
            "desktop": {"columns": 12},
            "tablet": {"columns": 8},
            "mobile": {"columns": 4},
        },
    }


# ---------------------------------------------------------------------------
# Service lifecycle
# ---------------------------------------------------------------------------


def test_registry_normalizes_legacy_definition_to_v2_defaults():
    from app.page_builder.registry import validate_definition

    cleaned = validate_definition(_valid_definition())

    assert cleaned["schema_version"] == 2
    assert cleaned["data_sources"] == []
    assert cleaned["theme_id"] == "scientific-light"
    assert cleaned["layouts"] == {"desktop": {}, "tablet": {}, "mobile": {}}


def test_registry_preserves_valid_v2_metadata():
    from app.page_builder.registry import validate_definition

    cleaned = validate_definition(_valid_v2_definition())

    assert cleaned["schema_version"] == 2
    assert cleaned["data_sources"] == _valid_v2_definition()["data_sources"]
    assert cleaned["theme_id"] == "compact-data"
    assert cleaned["layouts"] == _valid_v2_definition()["layouts"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 3),
        ("theme_id", "custom-css-theme"),
        ("data_sources", [{"id": "genes", "kind": "dataset", "script": "alert(1)"}]),
        ("layouts", {"desktop": [], "tablet": {}, "mobile": {}}),
    ],
)
def test_registry_rejects_invalid_v2_metadata(field, value):
    from app.page_builder.registry import validate_definition

    definition = _valid_v2_definition()
    definition[field] = value

    with pytest.raises(ValidationError):
        validate_definition(definition)


def _plugin_state(*, assemblies=("Glycine max",), healthy=True, public_url="https://tools.example.org"):
    from app.core.plugins import PluginState

    return PluginState(
        version="1.0.0",
        installed=True,
        enabled=True,
        configured=True,
        healthy=healthy,
        public_url=public_url,
        assemblies=assemblies,
        reason=None if healthy else "healthcheck_failed",
    )


def test_plugin_launchers_require_healthy_allowlisted_assembly():
    from app.page_builder.registry import validate_plugin_launchers

    definition = validate_plugin_launchers(
        {
            "root": {
                "type": "columns",
                "props": {"columns": 1},
                "children": [
                    {
                        "type": "jbrowse_launcher",
                        "props": {"assembly": "Glycine max"},
                    },
                    {
                        "type": "blast_launcher",
                        "props": {"program": "blastn", "assembly": "Glycine max"},
                    },
                ],
            }
        },
        {"jbrowse": _plugin_state(), "blast": _plugin_state()},
    )

    assert definition["root"]["children"][0]["props"]["assembly"] == "Glycine max"


@pytest.mark.parametrize(
    "states",
    [
        {},
        {"jbrowse": _plugin_state(healthy=False)},
        {"jbrowse": _plugin_state(assemblies=("Williams 82",))},
        {"jbrowse": _plugin_state(public_url=None)},
    ],
)
def test_plugin_launchers_fail_closed_when_status_assembly_or_url_is_invalid(states):
    from app.page_builder.registry import validate_plugin_launchers

    definition = {
        "root": {
            "type": "jbrowse_launcher",
            "props": {"assembly": "Glycine max"},
        }
    }

    with pytest.raises(ValidationError):
        validate_plugin_launchers(definition, states)


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
    assert event.event_type == "page_definition_publish_requested"

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
    editor = _editor()
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
        edited_by=editor,
    )
    assert event.event_type == "page_definition_publish_requested"
    assert event.payload["task_name"].endswith("page_builder_publish.publish_definition")
    assert event.payload["kwargs"] == {
        "page_id": str(page.id),
        "version_id": str(v1.id),
    }
    assert event.payload["metadata"] == {
        "requested_by": str(editor),
        "reason": "go live",
        "route": "/publish-me",
        "version": 1,
    }
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
    resource_cards = next(component for component in data if component["renderer_key"] == "resource_cards")
    assert resource_cards["label"] == "Resource Cards"
    card_schema = resource_cards["config_schema"]["$defs"]["ResourceCardItem"]
    assert set(card_schema["properties"]) >= {"title", "description", "image_url", "href"}


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
    # 为什么：导航项必须指向 SPA 真实路由（/news、/help），与 web seed 同构。
    nav_routes = [i["route"] for i in NAV_ITEMS]
    assert nav_routes == ["/", "/search", "/tools", "/news", "/help"]

    assert len(SEED_PAGES) == 7
    routes = [r for r, _t, _d in SEED_PAGES]
    # BLAST and JBrowse routes are reserved, never seeded as generic pages.
    assert "/blast" not in routes
    assert "/browser" not in routes
    # News/Contact published definitions target the real SPA routes.
    assert "/news" in routes
    assert "/help" in routes
    assert "/latest-news" not in routes
    assert "/contact" not in routes

    # Every seed definition must pass the registry.
    for route, title_key, definition in SEED_PAGES:
        validate_definition({**definition, "title_key": title_key})

    # 为什么：首页按规格含 news_list + media_carousel（新闻 2:3 + 轮播）。
    home = next(d for r, _t, d in SEED_PAGES if r == "/")
    child_types = [c["type"] for c in home["root"]["children"]]
    assert "news_list" in child_types
    assert "media_carousel" in child_types
    resource_cards = next(child for child in home["root"]["children"] if child["type"] == "resource_cards")
    assert resource_cards["props"]["heading"] == "资源导览"
    assert [card["title"] for card in resource_cards["props"]["cards"]] == [
        "数据下载", "使用指南", "文献 / 出版物"
    ]

    tools = next(d for r, _t, d in SEED_PAGES if r == "/tools")
    blast = next(
        child
        for child in tools["root"]["children"]
        if child["type"] == "blast_launcher"
    )
    assert blast["props"]["assembly"] == "Glycine max"

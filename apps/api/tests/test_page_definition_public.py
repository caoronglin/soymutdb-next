"""Tests for the public page-definition read endpoint and service.

The public contract only ever exposes ``published`` definitions; draft and
preview versions must never be visible to unauthenticated readers.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.models.page_builder import PageDefinitionStatus
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


@pytest.mark.asyncio
async def test_unpublished_page_is_not_served(db_session):
    page, version = await page_service.create_page(
        db_session,
        route="/not-yet-published",
        title_key="nav.nope",
        definition=_valid_definition(),
        edited_by=_editor(),
    )
    published = await page_service.get_published(db_session, page_id=page.id)
    assert published is None


@pytest.mark.asyncio
async def test_published_page_is_served_immutably(db_session):
    page, v1 = await page_service.create_page(
        db_session,
        route="/served",
        title_key="nav.served",
        definition=_valid_definition("public content"),
        edited_by=_editor(),
    )
    _p, requested, _event = await page_service.publish_request(
        db_session,
        page_id=page.id,
        version_id=v1.id,
        reason=None,
        edited_by=_editor(),
    )
    await page_service.publish_version(db_session, requested)

    published = await page_service.get_published(db_session, route="/served")
    assert published is not None
    assert published.status == PageDefinitionStatus.PUBLISHED
    assert published.definition["root"]["props"]["content"] == "<p>public content</p>"


@pytest.mark.asyncio
async def test_public_http_endpoint_returns_published_version(app, db_session):
    # Build a fresh app that overrides only the DB (no auth) and register the
    # domain exception handlers so NotFoundError maps to 404.
    from fastapi import FastAPI

    from app.api.v1.page_definitions import router
    from app.core.database import get_db
    from app.core.exceptions import (
        SoyMutDBError,
        soy_mut_db_exception_handler,
    )

    application = FastAPI()
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.include_router(router, prefix="/api/v1")

    session_factory = db_session
    async def override_db():
        yield session_factory

    application.dependency_overrides[get_db] = override_db

    # Unpublished route -> 404.
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        before = await ac.get("/api/v1/page-definitions/missing")
        assert before.status_code == 404

        # Publish a page then read it back.
        page, v1 = await page_service.create_page(
            db_session,
            route="/public-page",
            title_key="nav.public",
            definition=_valid_definition("public page"),
            edited_by=_editor(),
        )
        _p, req, _e = await page_service.publish_request(
            db_session,
            page_id=page.id,
            version_id=v1.id,
            reason=None,
            edited_by=_editor(),
        )
        await page_service.publish_version(db_session, req)

        after = await ac.get("/api/v1/page-definitions/public-page")
        assert after.status_code == 200
        body = after.json()
        assert body["status"] == "published"
        assert body["definition"]["root"]["props"]["content"] == "<p>public page</p>"

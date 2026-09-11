"""PostgreSQL-backed safety checks for the StaticPage draft migration."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.content import StaticPage
from app.models.page_builder import PageDefinition, PageDefinitionStatus, PageDefinitionVersion
from app.services.static_page_migration_service import migrate_static_pages


@pytest.mark.asyncio
async def test_static_page_migration_is_dry_run_safe_and_draft_only(db_session):
    source = StaticPage(
        slug="legacy-about",
        title_en="About",
        title_zh="关于",
        content_en="<p>English source</p>",
        content_zh="<p>中文来源</p>",
        status="published",
    )
    db_session.add(source)
    await db_session.flush()
    source_id = source.id

    preview = await migrate_static_pages(db_session, dry_run=True)
    assert preview.dry_run is True
    assert preview.created == 1
    assert await db_session.scalar(
        select(PageDefinition).where(PageDefinition.route == "/pages/legacy-about")
    ) is None

    applied = await migrate_static_pages(db_session, dry_run=False)
    assert applied.dry_run is False
    assert applied.created == 1

    target = await db_session.scalar(
        select(PageDefinition).where(PageDefinition.route == "/pages/legacy-about")
    )
    assert target is not None
    version = await db_session.scalar(
        select(PageDefinitionVersion).where(PageDefinitionVersion.page_id == target.id)
    )
    assert version is not None
    assert version.status == PageDefinitionStatus.DRAFT
    assert version.definition["root"]["children"][0]["props"]["content"] == "<p>English source</p>"
    assert version.definition["root"]["children"][1]["props"]["content"] == "<p>中文来源</p>"

    reloaded_source = await db_session.get(StaticPage, source_id)
    assert reloaded_source is not None
    assert reloaded_source.status == "published"
    assert reloaded_source.content_en == "<p>English source</p>"
    assert reloaded_source.content_zh == "<p>中文来源</p>"

    retry = await migrate_static_pages(db_session, dry_run=False)
    assert retry.created == 0
    assert retry.skipped == 1
    assert await db_session.scalar(
        select(PageDefinition).where(PageDefinition.route == "/pages/legacy-about")
    ) == target

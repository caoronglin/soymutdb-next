from __future__ import annotations

import pytest

from app.models.content import StaticPage
from app.models.page_builder import PageDefinition, PageDefinitionStatus, PageDefinitionVersion
from app.services.static_page_migration_service import (
    convert_to_definition,
    migrate_static_pages,
    route_for_static_page,
)


def legacy_page(slug: str = "legacy-about") -> StaticPage:
    return StaticPage(
        id=7,
        slug=slug,
        title_en="Legacy about",
        content_en="<p>English</p>",
        content_zh="<p>中文</p>",
        status="published",
    )


class ScalarResult:
    def __init__(self, pages: list[StaticPage]):
        self._pages = pages

    def scalars(self):
        return self

    def all(self):
        return self._pages


class FakeSession:
    def __init__(self, pages: list[StaticPage], existing: list[object | None] | None = None):
        self.pages = pages
        self.existing = list(existing or [])
        self.added: list[object] = []
        self.flushes = 0
        self.commits = 0

    async def execute(self, _statement):
        return ScalarResult(self.pages)

    async def scalar(self, _statement):
        return self.existing.pop(0) if self.existing else None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            if isinstance(value, PageDefinition) and value.id is None:
                value.id = "page-id"

    async def commit(self):
        self.commits += 1


def test_convert_preserves_bilingual_body_as_rich_text_nodes():
    source = legacy_page()
    definition = convert_to_definition(source)
    children = definition["root"]["children"]
    assert definition["schema_version"] == 2
    assert definition["title_key"] == "page.legacy-about.title"
    assert [child["props"]["content"] for child in children] == ["<p>English</p>", "<p>中文</p>"]
    assert source.content_en == "<p>English</p>"
    assert source.content_zh == "<p>中文</p>"


def test_route_for_static_page_uses_existing_pages_namespace():
    assert route_for_static_page(legacy_page("lab-notes")) == "/pages/lab-notes"


@pytest.mark.asyncio
async def test_dry_run_is_non_mutating_and_reports_creation():
    source = legacy_page()
    db = FakeSession([source])
    report = await migrate_static_pages(db, dry_run=True)
    assert report.created == 1
    assert report.items[0].route == "/pages/legacy-about"
    assert db.added == []
    assert db.flushes == 0
    assert db.commits == 0
    assert source.status == "published"


@pytest.mark.asyncio
async def test_apply_creates_only_draft_and_is_idempotent():
    source = legacy_page()
    db = FakeSession([source])
    report = await migrate_static_pages(db, dry_run=False)
    assert report.created == 1
    assert db.commits == 1
    assert isinstance(db.added[0], PageDefinition)
    version = next(value for value in db.added if isinstance(value, PageDefinitionVersion))
    assert version.status == PageDefinitionStatus.DRAFT
    assert version.published_at is None
    assert source.status == "published"
    retry = FakeSession([source], existing=["existing-page-id"])
    retry_report = await migrate_static_pages(retry, dry_run=False)
    assert retry_report.skipped == 1
    assert retry.added == []
    assert retry.commits == 0

@pytest.mark.asyncio
async def test_invalid_page_report_uses_stable_safe_error(monkeypatch):
    source = legacy_page("bad_slug")
    db = FakeSession([source])
    monkeypatch.setattr(
        "app.services.static_page_migration_service.validate_route",
        lambda _route: (_ for _ in ()).throw(ValueError("internal route detail")),
    )
    report = await migrate_static_pages(db, dry_run=True)
    item = report.items[0]
    assert item.outcome == "invalid"
    assert item.error_code == "invalid_static_page"
    assert item.message == "The legacy page cannot be converted to a Page Builder draft."
    assert "internal route detail" not in item.message
    assert db.added == []
    assert db.commits == 0

"""Regression coverage for post-commit public news cache invalidation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.content import NewsArticle
from app.schemas.news import NewsCreate, NewsReorderItem, NewsReorderRequest, NewsUpdate
from app.services import news_service
from app.services.news_service import NewsService


class _Result:
    def __init__(self, rows: list[NewsArticle]):
        self._rows = rows

    def scalar_one_or_none(self) -> NewsArticle | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[NewsArticle]:
        return self._rows


class _Session:
    def __init__(self, articles: list[NewsArticle] | None = None, *, fail_commit: bool = False):
        self.articles = articles or []
        self.fail_commit = fail_commit
        self.commit_count = 0

    async def scalar(self, _statement):
        return None

    async def execute(self, _statement):
        return _Result(self.articles)

    def add(self, obj) -> None:
        if isinstance(obj, NewsArticle):
            obj.id = len(self.articles) + 1
            obj.created_at = datetime.now(UTC)
            obj.updated_at = obj.created_at
            self.articles.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("database unavailable")

    async def refresh(self, _article: NewsArticle) -> None:
        return None

    async def delete(self, article: NewsArticle) -> None:
        self.articles.remove(article)


def _article() -> NewsArticle:
    now = datetime.now(UTC)
    return NewsArticle(
        id=1,
        title_en="Existing article",
        content_en="<p>Body</p>",
        slug="existing-article",
        status="draft",
        is_published=False,
        featured_sort=0,
        carousel_sort=0,
        created_at=now,
        updated_at=now,
    )


async def test_successful_news_mutations_invalidate_public_cache_after_commit(monkeypatch) -> None:
    events: list[str] = []

    async def invalidate() -> None:
        events.append("invalidate")

    monkeypatch.setattr(news_service, "_invalidate_public_news_caches", invalidate)
    service = NewsService()

    create_session = _Session()
    original_create_commit = create_session.commit

    async def create_commit() -> None:
        events.append("commit:create")
        await original_create_commit()

    create_session.commit = create_commit
    await service.create_article(
        create_session,
        NewsCreate(title_en="Created", content_en="<p>Body</p>", slug="created"),
        uuid.uuid4(),
    )

    update_session = _Session([_article()])
    await service.update_article(
        update_session, 1, NewsUpdate(title_en="Updated"), uuid.uuid4()
    )

    delete_session = _Session([_article()])
    await service.delete_article(delete_session, 1, actor_id=uuid.uuid4())

    reorder_session = _Session([_article()])
    await service.reorder(
        reorder_session,
        NewsReorderRequest(items=[NewsReorderItem(id=1, featured_sort=2)]),
    )

    assert events[0:2] == ["commit:create", "invalidate"]
    assert events.count("invalidate") == 4


async def test_failed_news_commit_does_not_invalidate_public_cache(monkeypatch) -> None:
    invalidations: list[str] = []

    async def invalidate() -> None:
        invalidations.append("invalidate")

    monkeypatch.setattr(news_service, "_invalidate_public_news_caches", invalidate)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await NewsService().create_article(
            _Session(fail_commit=True),
            NewsCreate(title_en="Created", content_en="<p>Body</p>", slug="created"),
            uuid.uuid4(),
        )

    assert invalidations == []

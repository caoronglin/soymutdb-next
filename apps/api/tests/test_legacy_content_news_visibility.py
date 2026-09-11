"""Query-contract tests for legacy public news visibility routes.

The historic content-news routes retain their response shape, but they must use
the same status and visibility-window predicates as the current public news
API. These tests intentionally inspect the generated SQL because this focused
unit suite does not require a PostgreSQL container.
"""

from __future__ import annotations

import re

import pytest

from app.api.v1 import content
from app.core.exceptions import NotFoundError


class _Rows:
    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return []

    def scalar_one_or_none(self) -> None:
        return None


class _RecordingSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Rows()


def _assert_public_visibility_predicates(sql: str) -> None:
    normalized = sql.lower()
    where_parts = re.split(r"\s+where\s+", normalized, maxsplit=1)
    assert len(where_parts) == 2
    where_clause = where_parts[1]
    assert "news_articles.deleted_at is null" in where_clause
    assert "news_articles.status =" in where_clause
    assert "news_articles.is_published is true" in where_clause
    assert "news_articles.visible_from" in where_clause
    assert "news_articles.visible_to" in where_clause


async def test_legacy_content_news_list_uses_current_public_visibility_predicates() -> None:
    session = _RecordingSession()

    assert await content.list_news(session, limit=20) == []
    assert session.statement is not None
    _assert_public_visibility_predicates(str(session.statement))


async def test_legacy_content_news_detail_uses_current_public_visibility_predicates() -> None:
    session = _RecordingSession()

    with pytest.raises(NotFoundError):
        await content.get_news("scheduled-article", session)
    assert session.statement is not None
    _assert_public_visibility_predicates(str(session.statement))

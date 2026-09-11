"""News operations API tests (B1) – no docker / no testcontainers.

Covers with a fake database session:
- HMAC preview token sign/verify (pure functions: roundtrip, tamper, expiry,
  future-exp rejection, wrong slug)
- service layer: list (published + visibility window + category filter),
  featured (5 + carousel grouping), detail (published / hidden / preview),
  admin CRUD (is_published <-> status double-write), reorder
- HTTP layer: RBAC (401 unauthenticated / 403 non-editor / 200 content editor),
  endpoint wiring for every news route
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import FastAPI
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
from app.models.content import NewsArticle

# ---------------------------------------------------------------------------
# Fake database session (unit-level, no docker)
# ---------------------------------------------------------------------------


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in: returns fake news rows for any news query."""

    def __init__(self, articles: list[NewsArticle] | None = None, user: User | None = None):
        self.articles = list(articles or [])
        self.user = user
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0
        self.flushes = 0
        self.rollbacks = 0
        self.last_stmt = None
        self.statements: list[Any] = []

    async def execute(self, stmt, params=None):
        self.last_stmt = stmt
        self.statements.append(stmt)
        text = str(stmt)
        if "FROM news_articles" in text:
            rows = list(self.articles)
            if "news_articles.deleted_at IS NULL" in text:
                rows = [article for article in rows if article.deleted_at is None]
            elif "news_articles.deleted_at IS NOT NULL" in text:
                rows = [article for article in rows if article.deleted_at is not None]
            return _Result(rows)
        if "FROM users" in text:
            return _Result([self.user] if self.user else [])
        return _Result([])

    async def scalar(self, stmt):
        self.last_stmt = stmt
        self.statements.append(stmt)
        if "FROM news_articles" in str(stmt):
            rows = list(self.articles)
            if "news_articles.deleted_at IS NULL" in str(stmt):
                rows = [article for article in rows if article.deleted_at is None]
            elif "news_articles.deleted_at IS NOT NULL" in str(stmt):
                rows = [article for article in rows if article.deleted_at is not None]
            return len(rows)
        return None

    def add(self, obj) -> None:
        # Emulate the DB: autoincrement id + server-side timestamps.
        if isinstance(obj, NewsArticle):
            now = datetime.now(UTC)
            if obj.id is None:
                obj.id = max([a.id for a in self.articles] + [0]) + 1
            obj.created_at = obj.created_at or now
            obj.updated_at = obj.updated_at or now
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        pass

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def rollback(self) -> None:
        self.rollbacks += 1


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


def _make_article(
    *,
    article_id: int = 1,
    slug: str = "hello-soymutdb",
    status: str = "published",
    is_published: bool | None = None,
    category: str | None = "news",
    featured_sort: int = 0,
    carousel_group: str | None = None,
    carousel_sort: int = 0,
    visible_from=None,
    visible_to=None,
    published_at: datetime | None = None,
) -> NewsArticle:
    now = datetime.now(UTC)
    return NewsArticle(
        id=article_id,
        title_en="Test Title",
        title_zh=None,
        content_en="Test body",
        content_zh=None,
        slug=slug,
        category=category,
        cover_url=None,
        featured_sort=featured_sort,
        carousel_group=carousel_group,
        carousel_sort=carousel_sort,
        status=status,
        visible_from=visible_from,
        visible_to=visible_to,
        is_published=(status == "published" if is_published is None else is_published),
        published_at=published_at or now,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# HMAC preview tokens (pure functions)
# ---------------------------------------------------------------------------


class TestPreviewToken:
    def test_roundtrip_ok(self):
        from app.services.news_service import (
            sign_preview_token,
            verify_preview_token,
        )

        token, exp = sign_preview_token("my-article")
        assert verify_preview_token("my-article", token, exp) is True

    def test_tampered_token_rejected(self):
        from app.services.news_service import (
            sign_preview_token,
            verify_preview_token,
        )

        token, exp = sign_preview_token("my-article")
        assert verify_preview_token("my-article", token + "x", exp) is False

    def test_wrong_slug_rejected(self):
        from app.services.news_service import (
            sign_preview_token,
            verify_preview_token,
        )

        token, exp = sign_preview_token("my-article")
        assert verify_preview_token("other-article", token, exp) is False

    def test_expired_token_rejected(self):
        import hashlib
        import hmac
        import time as _time

        from app.core.config import get_settings
        from app.services.news_service import verify_preview_token

        past = int(_time.time()) - 60
        # recompute a token for the past timestamp

        secret = get_settings().jwt_secret.encode("utf-8")
        token = hmac.new(secret, f"my-article{past}".encode(), hashlib.sha256).hexdigest()
        assert verify_preview_token("my-article", token, past) is False

    def test_future_exp_rejected(self):
        from app.services.news_service import (
            PREVIEW_TTL_SECONDS,
            sign_preview_token,
            verify_preview_token,
        )

        token, exp = sign_preview_token("my-article", ttl=PREVIEW_TTL_SECONDS)
        # an attacker-supplied exp far in the future must be rejected even
        # though the signature check would fail anyway
        assert verify_preview_token("my-article", token, exp + 10_000) is False

    def test_missing_token_or_exp_rejected(self):
        from app.services.news_service import verify_preview_token

        assert verify_preview_token("my-article", None, 123) is False
        assert verify_preview_token("my-article", "abc", None) is False
        bad_exp = cast(Any, "not-an-int")
        assert verify_preview_token("my-article", "abc", bad_exp) is False


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class TestListArticles:
    async def test_list_returns_paginated_response(self):
        from app.schemas.news import NewsSummaryResponse
        from app.services.news_service import NewsService

        session = FakeDbSession(
            articles=[_make_article(article_id=1), _make_article(article_id=2, slug="two")]
        )
        response = await NewsService().list_articles(session, page=1, page_size=20)
        assert response.total == 2
        assert response.page == 1
        assert response.page_size == 20
        assert all(isinstance(i, NewsSummaryResponse) for i in response.items)

    async def test_list_filters_visibility_window_in_sql(self):
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[_make_article()])
        await NewsService().list_articles(session, page=1, page_size=20)
        sql = str(session.last_stmt)
        assert "news_articles.status" in sql
        assert "news_articles.visible_from" in sql
        assert "news_articles.visible_to" in sql
        assert "news_articles.is_published" in sql
        assert "news_articles.deleted_at IS NULL" in sql

    async def test_list_category_filter_adds_where_clause(self):
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[_make_article()])
        await NewsService().list_articles(session, category="announcement", page=1, page_size=20)
        assert "news_articles.category" in str(session.last_stmt)

    async def test_deleted_admin_list_includes_only_deleted_metadata(self):
        from app.services.news_service import NewsService

        active = _make_article(article_id=1, slug="active")
        deleted = _make_article(article_id=2, slug="deleted")
        deleted.deleted_at = datetime(2025, 1, 2, tzinfo=UTC)
        session = FakeDbSession(articles=[active, deleted])

        response = await NewsService().list_deleted_articles_admin(session)

        assert response.total == 1
        assert response.items[0].id == "2"
        assert response.items[0].deleted_at == deleted.deleted_at
        assert "news_articles.deleted_at IS NOT NULL" in str(session.last_stmt)

    async def test_admin_list_excludes_deleted_rows(self):
        from app.services.news_service import NewsService

        active = _make_article(article_id=1, slug="active")
        deleted = _make_article(article_id=2, slug="deleted")
        deleted.deleted_at = datetime.now(UTC)
        session = FakeDbSession(articles=[active, deleted])

        response = await NewsService().list_articles_admin(session)

        assert response.total == 1
        assert [item.slug for item in response.items] == ["active"]
        assert "news_articles.deleted_at IS NULL" in str(session.last_stmt)


class TestFeatured:
    async def test_featured_limits_to_five_in_sql(self):
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[_make_article(article_id=i) for i in range(1, 8)])
        await NewsService().featured(session)
        sqls = [str(s) for s in session.statements]
        assert any("featured_sort" in s for s in sqls)
        assert any("LIMIT" in s for s in sqls)

    async def test_carousel_groups_are_grouped(self):
        from app.services.news_service import NewsService

        session = FakeDbSession(
            articles=[
                _make_article(article_id=1, slug="a", carousel_group="home", carousel_sort=1),
                _make_article(article_id=2, slug="b", carousel_group="home", carousel_sort=2),
                _make_article(article_id=3, slug="c", carousel_group="events", carousel_sort=1),
            ]
        )
        response = await NewsService().featured(session)
        groups = {g.group: g.items for g in response.carousel}
        assert set(groups) == {"home", "events"}
        assert [i.slug for i in groups["home"]] == ["a", "b"]
        assert [i.slug for i in groups["events"]] == ["c"]


class TestGetBySlug:
    async def test_published_visible_returns_article(self):
        from app.services.news_service import NewsService

        article = _make_article(slug="public-post")
        session = FakeDbSession(articles=[article])
        got = await NewsService().get_by_slug(session, "public-post")
        assert got is article

    async def test_hidden_without_token_404(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService

        article = _make_article(slug="draft-post", status="draft")
        session = FakeDbSession(articles=[article])
        with pytest.raises(NotFoundError):
            await NewsService().get_by_slug(session, "draft-post")

    async def test_hidden_with_valid_preview_returns(self):
        from app.services.news_service import NewsService, sign_preview_token

        article = _make_article(slug="draft-post", status="draft")
        session = FakeDbSession(articles=[article])
        token, exp = sign_preview_token("draft-post")
        got = await NewsService().get_by_slug(session, "draft-post", preview=token, exp=exp)
        assert got is article

    async def test_deleted_article_is_hidden_even_with_valid_preview(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService, sign_preview_token

        article = _make_article(slug="deleted-post")
        article.deleted_at = datetime.now(UTC)
        session = FakeDbSession(articles=[article])
        token, exp = sign_preview_token("deleted-post")

        with pytest.raises(NotFoundError):
            await NewsService().get_by_slug(session, "deleted-post", preview=token, exp=exp)

    async def test_hidden_with_tampered_preview_404(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService, sign_preview_token

        article = _make_article(slug="draft-post", status="draft")
        session = FakeDbSession(articles=[article])
        token, exp = sign_preview_token("draft-post")
        with pytest.raises(NotFoundError):
            await NewsService().get_by_slug(session, "draft-post", preview=token + "zz", exp=exp)

    async def test_missing_slug_404(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[])
        with pytest.raises(NotFoundError):
            await NewsService().get_by_slug(session, "nope")


class TestAdminCrud:
    async def test_create_published_syncs_is_published(self):
        from app.schemas.news import NewsCreate, NewsStatus
        from app.services.news_service import NewsService

        session = FakeDbSession(user=_make_user())
        payload = NewsCreate(
            title_en="Hello",
            content_en="Body",
            slug="hello",
            status=NewsStatus.PUBLISHED,
        )
        article = await NewsService().create_article(session, payload, uuid.uuid4())
        assert article.status == "published"
        assert article.is_published is True
        assert article.published_at is not None
        assert session.commits == 1

    async def test_create_integrity_conflict_rolls_back_session(self):
        from sqlalchemy.exc import IntegrityError

        from app.core.exceptions import ConflictError
        from app.schemas.news import NewsCreate
        from app.services.news_service import NewsService

        class CommitConflictSession(FakeDbSession):
            async def commit(self) -> None:
                raise IntegrityError("INSERT", {}, Exception("duplicate"))

        session = CommitConflictSession(user=_make_user())
        payload = NewsCreate(title_en="Hello", content_en="Body", slug="hello")

        with pytest.raises(ConflictError, match="slug or external source URL"):
            await NewsService().create_article(session, payload, uuid.uuid4())

        assert session.rollbacks == 1

    async def test_create_draft_default_unpublished(self):
        from app.schemas.news import NewsCreate
        from app.services.news_service import NewsService

        session = FakeDbSession(user=_make_user())
        payload = NewsCreate(title_en="Draft", content_en="Body", slug="draft")
        article = await NewsService().create_article(session, payload, uuid.uuid4())
        assert article.status == "draft"
        assert article.is_published is False
        assert article.published_at is None

    async def test_update_status_to_published_double_write(self):
        from app.schemas.news import NewsStatus, NewsUpdate
        from app.services.news_service import NewsService

        article = _make_article(article_id=7, slug="old", status="draft")
        session = FakeDbSession(articles=[article], user=_make_user())
        updated = await NewsService().update_article(
            session,
            7,
            NewsUpdate(title_en="New Title", status=NewsStatus.PUBLISHED),
            uuid.uuid4(),
        )
        assert updated.title_en == "New Title"
        assert updated.status == "published"
        assert updated.is_published is True
        assert updated.published_at is not None
        assert session.commits == 1

    async def test_update_integrity_conflict_rolls_back_session(self):
        from sqlalchemy.exc import IntegrityError

        from app.core.exceptions import ConflictError
        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        class CommitConflictSession(FakeDbSession):
            async def commit(self) -> None:
                raise IntegrityError("UPDATE", {}, Exception("duplicate"))

        article = _make_article(article_id=7, slug="old")
        session = CommitConflictSession(articles=[article], user=_make_user())

        with pytest.raises(ConflictError, match="slug or external source URL"):
            await NewsService().update_article(
                session, 7, NewsUpdate(slug="duplicate"), uuid.uuid4()
            )

        assert session.rollbacks == 1

    async def test_update_is_published_false_flips_status(self):
        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        article = _make_article(article_id=7, slug="old", status="published")
        session = FakeDbSession(articles=[article], user=_make_user())
        updated = await NewsService().update_article(
            session, 7, NewsUpdate(is_published=False), uuid.uuid4()
        )
        assert updated.status == "draft"
        assert updated.is_published is False

    async def test_update_explicit_null_clears_optional_fields(self):
        """D4 null semantics: explicit ``null`` CLEARS nullable fields."""
        from datetime import UTC, datetime

        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        window = datetime(2026, 1, 1, tzinfo=UTC)
        article = _make_article(
            article_id=7,
            slug="old",
            category="news",
            carousel_group="homepage",
            visible_from=window,
            visible_to=window,
        )
        article.cover_url = "https://cdn.example/x.jpg"
        article.title_zh = "旧标题"
        article.content_zh = "旧正文"
        session = FakeDbSession(articles=[article], user=_make_user())
        updated = await NewsService().update_article(
            session,
            7,
            NewsUpdate(
                category=None,
                cover_url=None,
                carousel_group=None,
                visible_from=None,
                visible_to=None,
                title_zh=None,
                content_zh=None,
            ),
            uuid.uuid4(),
        )
        assert updated.category is None
        assert updated.cover_url is None
        assert updated.carousel_group is None
        assert updated.visible_from is None
        assert updated.visible_to is None
        assert updated.title_zh is None
        assert updated.content_zh is None
        # Non-nullable fields stay untouched.
        assert updated.slug == "old"
        assert updated.title_en == "Test Title"

    async def test_update_missing_fields_are_kept(self):
        """D4 null semantics: absent fields are left untouched."""
        from datetime import UTC, datetime

        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        window = datetime(2026, 1, 1, tzinfo=UTC)
        article = _make_article(
            article_id=7,
            slug="old",
            category="news",
            carousel_group="homepage",
            visible_from=window,
            visible_to=window,
        )
        article.cover_url = "https://cdn.example/x.jpg"
        session = FakeDbSession(articles=[article], user=_make_user())
        updated = await NewsService().update_article(
            session, 7, NewsUpdate(title_en="Only Title"), uuid.uuid4()
        )
        assert updated.title_en == "Only Title"
        assert updated.category == "news"
        assert updated.cover_url == "https://cdn.example/x.jpg"
        assert updated.carousel_group == "homepage"
        assert updated.visible_from == window
        assert updated.visible_to == window

    async def test_update_explicit_null_on_non_nullable_ignored(self):
        """D4 null semantics: ``null`` on a NOT NULL column means "no change"."""
        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        article = _make_article(article_id=7, slug="old")
        session = FakeDbSession(articles=[article], user=_make_user())
        updated = await NewsService().update_article(
            session,
            7,
            NewsUpdate(title_en=None, slug=None, featured_sort=None),
            uuid.uuid4(),
        )
        assert updated.title_en == "Test Title"
        assert updated.slug == "old"
        assert updated.featured_sort == 0

    async def test_update_missing_404(self):
        from app.core.exceptions import NotFoundError
        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[])
        with pytest.raises(NotFoundError):
            await NewsService().update_article(session, 99, NewsUpdate(title_en="x"), uuid.uuid4())

    async def test_detail_response_includes_visibility_window(self):
        """D4: NewsDetailResponse carries visible_from/visible_to for the
        admin edit form to pre-fill the scheduled visibility window."""
        from datetime import UTC, datetime

        from app.schemas.news import NewsDetailResponse

        window = datetime(2026, 1, 1, tzinfo=UTC)
        article = _make_article(article_id=7, slug="old", visible_from=window, visible_to=window)
        detail = NewsDetailResponse.model_validate(article)
        assert detail.visible_from == window
        assert detail.visible_to == window
        assert detail.content_en == "Test body"

        empty = NewsDetailResponse.model_validate(_make_article(article_id=8))
        assert empty.visible_from is None
        assert empty.visible_to is None

    async def test_delete_soft_deletes_article_and_writes_allow_listed_audit(self):
        from app.models.auth import AuditLog
        from app.services.news_service import NewsService

        actor_id = uuid.uuid4()
        article = _make_article(article_id=5, slug="bye")
        session = FakeDbSession(articles=[article])
        await NewsService().delete_article(session, 5, actor_id=actor_id)

        assert session.deleted == []
        assert article.deleted_at is not None
        assert article.deleted_by == actor_id
        assert session.commits == 1
        audit = next(entry for entry in session.added if isinstance(entry, AuditLog))
        assert audit.user_id == actor_id
        assert audit.action == "news_deleted"
        assert audit.resource_type == "news_article"
        assert audit.resource_id == "5"
        assert audit.old_value == {"lifecycle": "active", "slug": "bye"}
        assert audit.new_value == {"lifecycle": "soft_deleted", "slug": "bye"}

    async def test_purge_deleted_article_removes_only_article_and_retains_allowlisted_audit(self):
        from app.models.auth import AuditLog
        from app.services.news_service import NewsService

        actor_id = uuid.uuid4()
        article = _make_article(article_id=5, slug="purge-me")
        article.deleted_at = datetime.now(UTC)
        article.content_en = "private body"
        article.source_url = "https://source.example/private"
        session = FakeDbSession(articles=[article])

        await NewsService().purge_article(session, 5, actor_id=actor_id)

        assert session.deleted == [article]
        assert session.commits == 1
        audit = next(entry for entry in session.added if isinstance(entry, AuditLog))
        assert audit.action == "news_purged"
        assert audit.resource_type == "news_article"
        assert audit.resource_id == "5"
        assert audit.old_value == {"lifecycle": "soft_deleted", "slug": "purge-me"}
        assert audit.new_value == {"lifecycle": "purged", "slug": "purge-me"}
        assert set(audit.old_value) | set(audit.new_value) == {"lifecycle", "slug"}

    async def test_restore_clears_soft_delete_and_writes_audit(self):
        from app.models.auth import AuditLog
        from app.services.news_service import NewsService

        actor_id = uuid.uuid4()
        article = _make_article(article_id=5, slug="restorable")
        article.deleted_at = datetime.now(UTC)
        article.deleted_by = uuid.uuid4()
        session = FakeDbSession(articles=[article])

        restored = await NewsService().restore_article(session, 5, actor_id=actor_id)

        assert restored is article
        assert article.deleted_at is None
        assert article.deleted_by is None
        assert session.commits == 1
        audit = next(entry for entry in session.added if isinstance(entry, AuditLog))
        assert audit.user_id == actor_id
        assert audit.action == "news_restored"
        assert audit.old_value == {"lifecycle": "soft_deleted", "slug": "restorable"}
        assert audit.new_value == {"lifecycle": "active", "slug": "restorable"}

    async def test_restore_active_article_404(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[_make_article(article_id=5)])
        with pytest.raises(NotFoundError):
            await NewsService().restore_article(session, 5, actor_id=uuid.uuid4())

    async def test_delete_missing_404(self):
        from app.core.exceptions import NotFoundError
        from app.services.news_service import NewsService

        session = FakeDbSession(articles=[])
        with pytest.raises(NotFoundError):
            await NewsService().delete_article(session, 5, actor_id=uuid.uuid4())

    async def test_reorder_updates_featured_sort(self):
        from app.schemas.news import NewsReorderItem, NewsReorderRequest
        from app.services.news_service import NewsService

        a = _make_article(article_id=1, slug="a")
        b = _make_article(article_id=2, slug="b")
        session = FakeDbSession(articles=[a, b])
        response = await NewsService().reorder(
            session,
            NewsReorderRequest(
                items=[
                    NewsReorderItem(id=1, featured_sort=0),
                    NewsReorderItem(id=2, featured_sort=1),
                ]
            ),
        )
        assert response.updated == 2
        assert a.featured_sort == 0
        assert b.featured_sort == 1

    async def test_reorder_unknown_id_404(self):
        from app.core.exceptions import NotFoundError
        from app.schemas.news import NewsReorderItem, NewsReorderRequest
        from app.services.news_service import NewsService

        a = _make_article(article_id=1, slug="a")
        session = FakeDbSession(articles=[a])
        with pytest.raises(NotFoundError):
            await NewsService().reorder(
                session,
                NewsReorderRequest(items=[NewsReorderItem(id=999, featured_sort=0)]),
            )


# ---------------------------------------------------------------------------
# HTTP layer: RBAC + endpoint wiring
# ---------------------------------------------------------------------------


@pytest.fixture
async def api_app():
    """Minimal app with the full v1 router and a fake DB session."""
    from fastapi.exceptions import RequestValidationError

    from app.api.v1.router import api_router
    from app.core.database import get_db

    session = FakeDbSession(user=None)

    async def override_get_db():
        yield session

    application = FastAPI(title="News Test API")
    application.include_router(api_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
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


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


class TestPublicEndpoints:
    async def test_list_200(self, api_client, api_app):
        api_app.state.fake_session.articles = [
            _make_article(article_id=1, slug="one"),
            _make_article(article_id=2, slug="two"),
        ]
        r = await api_client.get("/api/v1/news")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert {i["slug"] for i in body["items"]} == {"one", "two"}
        assert "content_en" not in body["items"][0]

    async def test_list_category_filter_200(self, api_client, api_app):
        api_app.state.fake_session.articles = [_make_article(slug="one")]
        r = await api_client.get("/api/v1/news", params={"category": "news"})
        assert r.status_code == 200

    async def test_featured_200(self, api_client, api_app):
        api_app.state.fake_session.articles = [
            _make_article(
                article_id=1,
                slug="hero",
                carousel_group="home",
                carousel_sort=1,
            )
        ]
        r = await api_client.get("/api/v1/news/featured")
        assert r.status_code == 200
        body = r.json()
        assert body["featured"][0]["slug"] == "hero"
        assert body["carousel"][0]["group"] == "home"

    async def test_detail_published_200(self, api_client, api_app):
        api_app.state.fake_session.articles = [_make_article(slug="post")]
        r = await api_client.get("/api/v1/news/post")
        assert r.status_code == 200
        body = r.json()
        assert body["slug"] == "post"
        assert body["content_en"] == "Test body"

    async def test_detail_hidden_404_without_token(self, api_client, api_app):
        api_app.state.fake_session.articles = [_make_article(slug="secret", status="draft")]
        r = await api_client.get("/api/v1/news/secret")
        assert r.status_code == 404

    async def test_detail_hidden_200_with_valid_preview(self, api_client, api_app):
        from app.services.news_service import sign_preview_token

        api_app.state.fake_session.articles = [_make_article(slug="secret", status="draft")]
        token, exp = sign_preview_token("secret")
        r = await api_client.get("/api/v1/news/secret", params={"preview": token, "exp": exp})
        assert r.status_code == 200
        assert r.json()["slug"] == "secret"

    async def test_detail_hidden_404_with_tampered_preview(self, api_client, api_app):
        from app.services.news_service import sign_preview_token

        api_app.state.fake_session.articles = [_make_article(slug="secret", status="draft")]
        token, exp = sign_preview_token("secret")
        r = await api_client.get(
            "/api/v1/news/secret", params={"preview": token + "zz", "exp": exp}
        )
        assert r.status_code == 404


class TestAdminRBAC:
    async def test_admin_unauthenticated_401(self, api_client):
        r = await api_client.post(
            "/api/v1/admin/news",
            json={"title_en": "T", "content_en": "C", "slug": "t"},
        )
        assert r.status_code == 401

    async def test_admin_viewer_403(self, api_client, api_app):
        user = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/admin/news",
            json={"title_en": "T", "content_en": "C", "slug": "t"},
            headers=_auth_header(user),
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_external_preview_requires_content_editor(self, api_client, api_app, monkeypatch):
        from app.api.v1 import admin_news

        class Previewer:
            calls = 0

            async def preview(self, _platform, _source_url):
                self.calls += 1
                raise AssertionError("unauthorized callers must not fetch external URLs")

        previewer = Previewer()
        monkeypatch.setattr(admin_news, "external_preview_service", previewer)
        payload = {"platform": "wechat", "source_url": "https://mp.weixin.qq.com/s?x=1"}

        unauthenticated = await api_client.post("/api/v1/admin/news/external-preview", json=payload)
        assert unauthenticated.status_code == 401

        viewer = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = viewer
        forbidden = await api_client.post(
            "/api/v1/admin/news/external-preview",
            json=payload,
            headers=_auth_header(viewer),
        )
        assert forbidden.status_code == 403
        assert previewer.calls == 0

    async def test_external_preview_rate_limit_blocks_outbound_fetch(
        self, api_client, api_app, monkeypatch
    ):
        from app.api.v1 import admin_news
        from app.core.exceptions import RateLimitExceededError

        class Previewer:
            calls = 0

            async def preview(self, _platform, _source_url):
                self.calls += 1
                raise AssertionError("rate-limited previews must not fetch external URLs")

        class BlockedLimiter:
            calls: list[tuple[str, str | None]] = []

            async def enforce(self, *, user_id: str, client_ip: str | None):
                self.calls.append((user_id, client_ip))
                raise RateLimitExceededError("Too many external article previews", retry_after=42)

        previewer = Previewer()
        limiter = BlockedLimiter()
        monkeypatch.setattr(admin_news, "external_preview_service", previewer)
        monkeypatch.setattr(admin_news, "external_article_preview_rate_limiter", limiter)
        editor = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = editor

        response = await api_client.post(
            "/api/v1/admin/news/external-preview",
            json={"platform": "wechat", "source_url": "https://mp.weixin.qq.com/s?x=1"},
            headers=_auth_header(editor),
        )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "42"
        assert previewer.calls == 0
        assert limiter.calls == [(str(editor.id), "127.0.0.1")]

    async def test_external_preview_returns_opaque_attestation(
        self, api_client, api_app, monkeypatch
    ):
        from app.api.v1 import admin_news
        from app.services.external_article_service import ExternalArticlePreview

        class Previewer:
            async def preview(self, _platform, _source_url):
                return ExternalArticlePreview(
                    platform="wechat",
                    source_url="https://mp.weixin.qq.com/s?x=1",
                    title="Reviewed",
                    content_html="<p>Reviewed body</p>",
                    source_content_hash="e" * 64,
                    source_published_at=None,
                )

        monkeypatch.setattr(admin_news, "external_preview_service", Previewer())
        editor = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = editor
        response = await api_client.post(
            "/api/v1/admin/news/external-preview",
            json={"platform": "wechat", "source_url": "https://mp.weixin.qq.com/s?x=1"},
            headers=_auth_header(editor),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["source_preview_token"].count(".") == 1
        assert "source_content_hash" not in body

    async def test_admin_researcher_create_403(self, api_client, api_app):
        user = _make_user(RoleName.RESEARCHER)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/admin/news",
            json={
                "title_en": "Hello",
                "content_en": "Body",
                "slug": "hello",
                "status": "published",
            },
            headers=_auth_header(user),
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"

    async def test_admin_content_editor_create_201(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        r = await api_client.post(
            "/api/v1/admin/news",
            json={
                "title_en": "Hello",
                "content_en": "Body",
                "slug": "hello",
                "status": "published",
            },
            headers=_auth_header(user),
        )
        assert r.status_code == 201
        body = r.json()
        assert body["slug"] == "hello"
        assert body["status"] == "published"
        assert body["is_published"] is True

    async def test_admin_content_editor_update_200(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [_make_article(article_id=3, slug="a")]
        r = await api_client.put(
            "/api/v1/admin/news/3",
            json={"title_en": "Updated"},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        assert r.json()["title_en"] == "Updated"

    async def test_admin_update_response_includes_visibility_window(self, api_client, api_app):
        """D4: PUT response serialises visible_from/visible_to so the edit
        form can re-fill the scheduled visibility window."""
        from datetime import UTC, datetime

        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        window = datetime(2026, 1, 1, tzinfo=UTC)
        api_app.state.fake_session.articles = [
            _make_article(article_id=3, slug="a", visible_from=window, visible_to=window)
        ]
        r = await api_client.put(
            "/api/v1/admin/news/3",
            json={"cover_url": None},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["visible_from"] == "2026-01-01T00:00:00Z"
        assert body["visible_to"] == "2026-01-01T00:00:00Z"

    async def test_admin_update_explicit_null_clears_cover_url(self, api_client, api_app):
        """D4: PUT with explicit null clears nullable fields (HTTP round-trip)."""
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        article = _make_article(article_id=3, slug="a")
        article.cover_url = "https://cdn.example/x.jpg"
        article.category = "news"
        api_app.state.fake_session.articles = [article]
        r = await api_client.put(
            "/api/v1/admin/news/3",
            json={"cover_url": None, "category": None},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["cover_url"] is None
        assert body["category"] is None

    async def test_admin_content_editor_delete_204(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        article = _make_article(article_id=3, slug="a")
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [article]
        r = await api_client.delete("/api/v1/admin/news/3", headers=_auth_header(user))
        assert r.status_code == 204
        assert article.deleted_at is not None
        assert article.deleted_by == user.id

    async def test_administrator_lists_deleted_news_metadata_only(self, api_client, api_app):
        user = _make_user(RoleName.ADMINISTRATOR)
        active = _make_article(article_id=1, slug="active")
        deleted = _make_article(article_id=2, slug="deleted")
        deleted.deleted_at = datetime(2025, 1, 2, tzinfo=UTC)
        deleted.content_en = "<p>private body</p>"
        deleted.cover_url = "https://cdn.example/private.jpg"
        deleted.source_url = "https://source.example/private"
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [active, deleted]

        r = await api_client.get("/api/v1/admin/news/deleted", headers=_auth_header(user))

        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["items"] == [
            {
                "id": "2",
                "title_en": "Test Title",
                "title_zh": None,
                "slug": "deleted",
                "category": "news",
                "status": "published",
                "published_at": deleted.published_at.isoformat().replace("+00:00", "Z"),
                "created_at": deleted.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": deleted.updated_at.isoformat().replace("+00:00", "Z"),
                "deleted_at": "2025-01-02T00:00:00Z",
            }
        ]

    async def test_deleted_news_list_requires_administrator(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        deleted = _make_article(article_id=2, slug="deleted")
        deleted.deleted_at = datetime.now(UTC)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [deleted]

        r = await api_client.get("/api/v1/admin/news/deleted", headers=_auth_header(user))

        assert r.status_code == 403

    async def test_content_editor_cannot_restore_news(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        article = _make_article(article_id=3, slug="a")
        article.deleted_at = datetime.now(UTC)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [article]

        r = await api_client.post("/api/v1/admin/news/3/restore", headers=_auth_header(user))

        assert r.status_code == 403
        assert article.deleted_at is not None

    async def test_administrator_restores_soft_deleted_news(self, api_client, api_app):
        user = _make_user(RoleName.ADMINISTRATOR)
        article = _make_article(article_id=3, slug="a")
        article.deleted_at = datetime.now(UTC)
        article.deleted_by = uuid.uuid4()
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [article]

        r = await api_client.post("/api/v1/admin/news/3/restore", headers=_auth_header(user))

        assert r.status_code == 200
        assert r.json()["slug"] == "a"
        assert article.deleted_at is None
        assert article.deleted_by is None

    async def test_content_editor_cannot_purge_news(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        article = _make_article(article_id=3, slug="deleted")
        article.deleted_at = datetime.now(UTC)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [article]

        response = await api_client.delete("/api/v1/admin/news/3/purge", headers=_auth_header(user))

        assert response.status_code == 403
        assert api_app.state.fake_session.deleted == []

    async def test_administrator_purges_deleted_news(self, api_client, api_app):
        user = _make_user(RoleName.ADMINISTRATOR)
        article = _make_article(article_id=3, slug="deleted")
        article.deleted_at = datetime.now(UTC)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [article]

        response = await api_client.delete("/api/v1/admin/news/3/purge", headers=_auth_header(user))

        assert response.status_code == 204
        assert api_app.state.fake_session.deleted == [article]

    async def test_administrator_cannot_purge_active_or_missing_news(self, api_client, api_app):
        user = _make_user(RoleName.ADMINISTRATOR)
        active = _make_article(article_id=3, slug="active")
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [active]

        active_response = await api_client.delete(
            "/api/v1/admin/news/3/purge", headers=_auth_header(user)
        )
        missing_response = await api_client.delete(
            "/api/v1/admin/news/99/purge", headers=_auth_header(user)
        )

        assert active_response.status_code == 404
        assert missing_response.status_code == 404

    async def test_admin_content_editor_reorder_200(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=1, slug="a"),
            _make_article(article_id=2, slug="b"),
        ]
        r = await api_client.patch(
            "/api/v1/admin/news/reorder",
            json={"items": [{"id": 1, "featured_sort": 0}, {"id": 2, "featured_sort": 1}]},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        assert r.json()["updated"] == 2

    async def test_admin_preview_token_200_and_hmac_valid(self, api_client, api_app):
        import hashlib
        import hmac

        from app.core.config import get_settings

        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=4, slug="draft-post", status="draft")
        ]
        r = await api_client.get("/api/v1/admin/news/4/preview-token", headers=_auth_header(user))
        assert r.status_code == 200
        body = r.json()
        assert body["url"].startswith("/api/v1/news/draft-post?preview=")
        expected = hmac.new(
            get_settings().jwt_secret.encode("utf-8"),
            f"draft-post{body['exp']}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert body["preview"] == expected
        # token is HMAC, not a JWT (no signature dots)
        assert body["preview"].count(".") == 0

    async def test_admin_preview_token_404_unknown(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        r = await api_client.get("/api/v1/admin/news/404/preview-token", headers=_auth_header(user))
        assert r.status_code == 404

    # -- admin list endpoint (all statuses) --

    async def test_admin_list_content_editor_200(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=1, slug="pub", status="published"),
            _make_article(article_id=2, slug="draft", status="draft"),
            _make_article(article_id=3, slug="archived", status="archived"),
        ]
        r = await api_client.get("/api/v1/admin/news", headers=_auth_header(user))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    async def test_admin_list_viewer_403(self, api_client, api_app):
        user = _make_user(RoleName.VIEWER)
        api_app.state.fake_session.user = user
        r = await api_client.get("/api/v1/admin/news", headers=_auth_header(user))
        assert r.status_code == 403

    async def test_admin_list_unauthenticated_401(self, api_client):
        r = await api_client.get("/api/v1/admin/news")
        assert r.status_code == 401

    async def test_admin_list_filter_draft(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=1, slug="pub", status="published"),
            _make_article(article_id=2, slug="draft", status="draft"),
            _make_article(article_id=3, slug="arch", status="archived"),
        ]
        r = await api_client.get(
            "/api/v1/admin/news",
            params={"status_filter": "draft"},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        # FakeDbSession returns all rows regardless of WHERE clause;
        # real DB + service applies status filter. Verify endpoint accepts
        # the param and returns paginated shape.
        assert body["total"] == 3
        assert body["page"] == 1
        # At least one draft is present (filter would narrow in real DB)
        statuses = {item["status"] for item in body["items"]}
        assert "draft" in statuses

    async def test_admin_list_pagination(self, api_client, api_app):
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=i, slug=f"a{i}", status="published") for i in range(1, 26)
        ]
        r = await api_client.get(
            "/api/v1/admin/news",
            params={"page": 2, "page_size": 5},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2
        assert body["page_size"] == 5

    async def test_admin_list_accepts_category_and_search_params(self, api_client, api_app):
        """D4: the admin list endpoint accepts the category + search filters
        the ProTable sends (backend service already supports them; verify
        the HTTP wiring accepts the params without error)."""
        user = _make_user(RoleName.CONTENT_EDITOR)
        api_app.state.fake_session.user = user
        api_app.state.fake_session.articles = [
            _make_article(article_id=1, slug="soybean-trial", category="news"),
            _make_article(article_id=2, slug="release-notes", category="update"),
        ]
        r = await api_client.get(
            "/api/v1/admin/news",
            params={"category": "news", "search": "soybean"},
            headers=_auth_header(user),
        )
        assert r.status_code == 200
        body = r.json()
        # FakeDbSession returns all rows; real DB narrows via the service.
        assert body["total"] == 2
        assert {i["slug"] for i in body["items"]} == {
            "soybean-trial",
            "release-notes",
        }


class TestExternalArticleProvenance:
    def _attestation(self, *, platform: str = "wechat") -> str:
        from app.services.external_article_service import (
            ExternalArticlePreview,
            sign_external_article_preview,
        )

        source_url = (
            "https://mp.weixin.qq.com/s?__biz=abc"
            if platform == "wechat"
            else "https://www.x-mol.com/article/42"
        )
        return sign_external_article_preview(
            ExternalArticlePreview(
                platform=platform,
                source_url=source_url,
                title="Reviewed external article",
                content_html="<p>Reviewed body</p>",
                source_content_hash="c" * 64,
                source_published_at=None,
            )
        )

    async def test_create_persists_only_attested_external_provenance(self):
        from app.schemas.news import NewsCreate
        from app.services.news_service import NewsService

        session = FakeDbSession()
        article = await NewsService().create_article(
            session,
            NewsCreate(
                title_en="Imported",
                content_en="<p>Reviewed body</p>",
                slug="imported",
                source_preview_token=self._attestation(),
            ),
            uuid.uuid4(),
        )

        assert article.source_platform == "wechat"
        assert article.source_url == "https://mp.weixin.qq.com/s?__biz=abc"
        assert article.source_content_hash == "c" * 64
        assert article.source_synced_at is not None

    async def test_update_can_replace_or_explicitly_clear_attested_provenance(self):
        from app.schemas.news import NewsUpdate
        from app.services.news_service import NewsService

        article = _make_article(article_id=19, slug="imported")
        session = FakeDbSession(articles=[article])
        updated = await NewsService().update_article(
            session,
            19,
            NewsUpdate(source_preview_token=self._attestation(platform="xmol")),
            uuid.uuid4(),
        )
        assert updated.source_platform == "xmol"
        assert updated.source_url == "https://www.x-mol.com/article/42"
        assert updated.source_content_hash == "c" * 64

        cleared = await NewsService().update_article(
            session,
            19,
            NewsUpdate(clear_source_provenance=True),
            uuid.uuid4(),
        )
        assert cleared.source_platform is None
        assert cleared.source_url is None
        assert cleared.source_content_hash is None
        assert cleared.source_published_at is None
        assert cleared.source_synced_at is None

    def test_unattested_provenance_fields_are_rejected(self):
        from pydantic import ValidationError as PydanticValidationError

        from app.schemas.news import NewsCreate

        with pytest.raises(PydanticValidationError, match="source_preview_token"):
            NewsCreate(
                title_en="Unverified",
                content_en="<p>body</p>",
                slug="unverified",
                source_platform="wechat",
                source_url="https://mp.weixin.qq.com/s?__biz=abc",
                source_content_hash="d" * 64,
            )

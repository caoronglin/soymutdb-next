"""Content snapshot endpoint tests (E2-2)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app

_FIXTURE_SNAPSHOT: dict = {
    "schema_version": 2,
    "generated_at": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC).isoformat(),
    "news": {
        "source_total": 2,
        "included_total": 2,
        "truncated": False,
        "items": [
            {
                "slug": "test-news",
                "title_en": "Test News",
                "title_zh": None,
                "category": "news",
                "cover_url": None,
                "published_at": "2026-08-09T09:00:00+00:00",
                "featured_sort": 0,
                "carousel_group": None,
                "carousel_sort": 0,
                "is_published": True,
                "created_at": "2026-08-09T08:00:00+00:00",
                "updated_at": "2026-08-09T08:30:00+00:00",
            }
        ],
    },
    "news_detail": {
        "test-news": {
            "slug": "test-news",
            "title_en": "Test News",
            "title_zh": None,
            "category": "news",
            "cover_url": None,
            "published_at": "2026-08-09T09:00:00+00:00",
            "content_en": "<h1>Hello</h1><p>Body</p>",
            "content_zh": None,
            "featured_sort": 0,
            "carousel_group": None,
            "carousel_sort": 0,
            "is_published": True,
            "created_at": "2026-08-09T08:00:00+00:00",
            "updated_at": "2026-08-09T08:30:00+00:00",
        }
    },
    "about": {
        "title_en": "About Us",
        "title_zh": None,
        "summary_en": "s",
        "summary_zh": None,
        "content_en": "<p>About content</p>",
        "content_zh": None,
    },
    "static_pages": [
        {
            "id": "page-1",
            "slug": "release-notes",
            "title_en": "Release Notes",
            "title_zh": None,
            "content_en": "<p>Notes</p>",
            "content_zh": None,
            "status": "published",
            "category": "docs",
            "summary": "Notes",
            "sort_order": 0,
            "created_at": "2026-08-09T08:00:00+00:00",
            "updated_at": "2026-08-09T08:00:00+00:00",
        }
    ],
    "publications": [
        {
            "id": "1",
            "title": "SoyMutDB paper",
            "title_zh": "SoyMutDB 论文",
            "authors": "Zhang et al.",
            "authors_zh": "张等",
            "journal": "Plant Journal",
            "year": 2026,
            "doi": "10.1234/example",
            "pmid": None,
            "abstract": "A study.",
            "abstract_zh": "一项研究。",
            "is_featured": True,
            "created_at": "2026-08-09T08:00:00+00:00",
        }
    ],
}


class TestContentSnapshot:
    def setup_method(self) -> None:
        # Route the snapshot builder to a fixed fixture (no DB required).
        import app.api.v1.content as content_module
        from app.core.database import get_db

        self._orig_build = content_module._build_snapshot
        content_module._build_snapshot = _fake_build  # type: ignore[assignment]

        async def _fake_db():
            yield None  # type: ignore[misc]

        app.dependency_overrides[get_db] = _fake_db  # type: ignore[assignment]
        self.client = TestClient(app)

    def teardown_method(self) -> None:
        import app.api.v1.content as content_module
        from app.core.database import get_db

        content_module._build_snapshot = self._orig_build  # type: ignore[assignment]
        app.dependency_overrides.pop(get_db, None)

    def test_snapshot_structure(self) -> None:
        resp = self.client.get("/api/v1/content/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == 2
        assert "generated_at" in data
        assert data["news"]["included_total"] == 2
        assert data["news"]["truncated"] is False
        assert data["news_detail"]["test-news"]["content_en"].startswith("<h1>")
        assert data["about"]["title_en"] == "About Us"
        assert data["publications"][0]["title_zh"] == "SoyMutDB 论文"
        assert data["static_pages"][0]["slug"] == "release-notes"

    def test_snapshot_etag_and_304(self) -> None:
        first = self.client.get("/api/v1/content/snapshot")
        etag = first.headers.get("etag")
        assert etag
        second = self.client.get(
            "/api/v1/content/snapshot", headers={"If-None-Match": etag}
        )
        assert second.status_code == 304

    def test_snapshot_public_no_auth(self) -> None:
        resp = self.client.get("/api/v1/content/snapshot")
        assert resp.status_code == 200


async def _fake_build(db: object, **kwargs: object) -> dict:
    return _FIXTURE_SNAPSHOT


class TestReleaseAwareSnapshot:
    def setup_method(self) -> None:
        import app.api.v1.content as content_module
        from app.core.database import get_db

        self._orig_build = content_module._build_snapshot
        self._seen: dict = {}

        async def recording_build(db, *, release_id=None, page_definition_version=None):
            self._seen["release_id"] = release_id
            self._seen["page_definition_version"] = page_definition_version
            return _FIXTURE_SNAPSHOT

        content_module._build_snapshot = recording_build

        async def _fake_db():
            yield None

        app.dependency_overrides[get_db] = _fake_db
        self.client = TestClient(app)

    def teardown_method(self) -> None:
        import app.api.v1.content as content_module
        from app.core.database import get_db

        content_module._build_snapshot = self._orig_build
        app.dependency_overrides.pop(get_db, None)

    def test_snapshot_accepts_release_and_page_version(self) -> None:
        resp = self.client.get(
            "/api/v1/content/snapshot?release_id=7&page_definition_version=3"
        )
        assert resp.status_code == 200
        assert self._seen["release_id"] == 7
        assert self._seen["page_definition_version"] == 3
        assert "release_id" not in resp.json()  # fixture has no release_id key

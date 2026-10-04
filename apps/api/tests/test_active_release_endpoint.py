"""Docker-free tests for ``GET /api/v1/releases/active``.

The portal pins its release at build time. When an operator publishes, a
long-lived tab keeps sending ``X-SoyMutDB-Release: <old>`` until it is told
otherwise, so this endpoint is what makes the switch observable at all.

The cases here cover the two things that would silently break the client:

* route ordering — ``/active`` declared after ``/{release_id}`` is captured by
  the id route and answers 422, which reads as "no such release" rather than as
  a wiring mistake;
* the empty state — before the first publish there is no release, and that is an
  answer, not a 404.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease

RELEASES_PREFIX = "/api/v1/releases"


class _Row:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):  # pragma: no cover - not awaited in these tests
        async def _self() -> Any:
            return self.value

        return _self().__await__()


class FakeActiveReleaseDB:
    """Minimal AsyncSession double: only ``db.get(Model, pk)`` is exercised."""

    def __init__(self, active: ActiveRelease | None, releases: dict[int, Release]) -> None:
        self.active = active
        self.releases = releases
        self.gets: list[tuple[type, Any]] = []

    async def get(self, model: type, pk: Any) -> Any:
        self.gets.append((model, pk))
        if model is ActiveRelease:
            return self.active
        if model is Release:
            return self.releases.get(pk)
        return None

    async def execute(self, query: object) -> Any:  # pragma: no cover - unused here
        raise AssertionError("the active-release endpoint must not run a list query")


def make_release(release_id: int, version: str) -> Release:
    now = datetime.now(UTC)
    return Release(
        id=release_id,
        version=version,
        name=f"Release {version}",
        status=ReleaseStatus.PUBLISHED,
        published_at=now,
        created_at=now,
        updated_at=now,
    )


@pytest_asyncio.fixture
async def release_client():
    from app.core.database import get_db
    from app.main import create_app

    async def _make(active: ActiveRelease | None, releases: dict[int, Release] | None = None):
        fake_db = FakeActiveReleaseDB(active, releases or {})
        application = create_app()

        async def override_get_db():
            yield fake_db

        application.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test.local") as client:
            yield client, fake_db
        application.dependency_overrides.clear()

    return _make


@pytest.mark.asyncio
class TestActiveReleaseEndpoint:
    async def test_reports_the_published_release(self, release_client) -> None:
        release = make_release(7, "2026.10")
        async for client, _db in release_client(ActiveRelease(id=1, release_id=7), {7: release}):
            response = await client.get(f"{RELEASES_PREFIX}/active")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["release_id"] == "7"
            assert body["version"] == "2026.10"
            assert body["published_at"] is not None

    async def test_route_is_not_captured_by_the_release_id_route(self, release_client) -> None:
        """`/active` must not be parsed as a release id (that would be a 422)."""
        r = make_release(7, "2026.10")
        async for client, _db in release_client(ActiveRelease(id=1, release_id=7), {7: r}):
            response = await client.get(f"{RELEASES_PREFIX}/active")
            assert response.status_code != 422
            assert "release_id" in response.json()

    async def test_answers_empty_before_the_first_publish(self, release_client) -> None:
        async for client, _db in release_client(None):
            response = await client.get(f"{RELEASES_PREFIX}/active")
            assert response.status_code == 200
            body = response.json()
            assert body == {"release_id": None, "version": None, "published_at": None}

    async def test_answers_empty_when_the_pointer_has_no_release(self, release_client) -> None:
        async for client, _db in release_client(ActiveRelease(id=1, release_id=None)):
            response = await client.get(f"{RELEASES_PREFIX}/active")
            assert response.status_code == 200
            assert response.json()["release_id"] is None

    async def test_answers_empty_when_the_pointer_dangles(self, release_client) -> None:
        # A pointer to a row that no longer exists must not become a 500.
        dangling = 999  # a release id that certainly has no row
        async for client, _db in release_client(ActiveRelease(id=1, release_id=dangling)):
            response = await client.get(f"{RELEASES_PREFIX}/active")
            assert response.status_code == 200
            assert response.json()["release_id"] is None

    async def test_reads_the_singleton_row_by_id_one(self, release_client) -> None:
        """The pointer is a fixed row; a different pk would read the wrong one."""
        r = make_release(7, "2026.10")
        async for client, db in release_client(ActiveRelease(id=1, release_id=7), {7: r}):
            await client.get(f"{RELEASES_PREFIX}/active")
            assert db.gets[0] == (ActiveRelease, 1)


def test_response_defaults_are_explicit() -> None:
    from app.schemas.content import ActiveReleaseResponse

    empty = ActiveReleaseResponse()
    assert empty.release_id is None
    assert empty.version is None
    assert empty.published_at is None

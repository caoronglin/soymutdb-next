"""PostgreSQL-backed release management/public visibility and cache boundaries."""

from datetime import UTC, datetime

import pytest

from app.core.security import create_access_token
from app.models.auth import User
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease

PRIVATE = "PRIVATE_DRAFT_RELEASE_SENTINEL_20261013"


@pytest.fixture
async def release_rows(db_session):
    published = Release(
        version="public-boundary-published", name="Public release",
        status=ReleaseStatus.PUBLISHED, published_at=datetime.now(UTC),
    )
    draft = Release(version="public-boundary-draft", name=PRIVATE, status=ReleaseStatus.DRAFT)
    db_session.add_all([published, draft])
    await db_session.commit()
    return published, draft


async def _headers(db_session, administrator):
    user = User(
        username="release-boundary-admin" if administrator else "release-boundary-viewer",
        email="admin@release.invalid" if administrator else "viewer@release.invalid",
        password_hash="unused", is_superuser=administrator,
    )
    db_session.add(user)
    await db_session.commit()
    return {"Authorization": "Bearer " + create_access_token(str(user.id))}


async def test_anonymous_list_contains_only_published(client, release_rows):
    published, _draft = release_rows
    response = await client.get("/api/v1/releases")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [str(published.id)]
    assert PRIVATE not in response.text
    assert response.headers["cache-control"].startswith("public")


async def test_explicit_draft_filter_is_not_public(client, release_rows):
    response = await client.get("/api/v1/releases?status=draft")
    assert response.status_code == 200
    assert response.json() == []
    assert PRIVATE not in response.text


async def test_anonymous_draft_detail_is_indistinguishable_from_missing(client, release_rows):
    _published, draft = release_rows
    for identity in (draft.id, 2147483647):
        response = await client.get(f"/api/v1/releases/{identity}")
        assert response.status_code == 404
        assert PRIVATE not in response.text


@pytest.mark.parametrize("path", ["", "/detail"])
async def test_internal_read_requires_authentication(client, release_rows, path):
    _published, draft = release_rows
    suffix = "" if not path else f"/{draft.id}"
    response = await client.get(f"/api/v1/releases{suffix}?variant=internal")
    assert response.status_code == 401
    assert PRIVATE not in response.text


async def test_non_admin_cannot_read_internal_drafts(client, db_session, release_rows):
    response = await client.get(
        "/api/v1/releases?variant=internal", headers=await _headers(db_session, False),
    )
    assert response.status_code == 403
    assert PRIVATE not in response.text


async def test_admin_internal_reads_are_private_and_do_not_fill_public_cache(
    client, db_session, release_rows, monkeypatch,
):
    from app.api.v1 import releases as releases_module

    _published, draft = release_rows
    headers = await _headers(db_session, True)

    async def no_shared_cache(*args, **kwargs):
        raise AssertionError("Private metadata must bypass shared cache")

    monkeypatch.setattr(releases_module, "get_or_set", no_shared_cache)
    for suffix in ("", f"/{draft.id}"):
        response = await client.get(f"/api/v1/releases{suffix}?variant=internal", headers=headers)
        assert response.status_code == 200, response.text
        assert PRIVATE in response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert "Authorization" in response.headers["vary"]


async def test_active_pointer_to_draft_discloses_nothing(client, db_session, release_rows):
    _published, draft = release_rows
    db_session.add(ActiveRelease(id=1, release_id=draft.id))
    await db_session.commit()
    response = await client.get("/api/v1/releases/active")
    assert response.status_code == 200
    assert response.json() == {"release_id": None, "version": None, "published_at": None}
    assert PRIVATE not in response.text


async def test_admin_validation_cannot_unpublish_active_release(client, db_session, release_rows):
    published, _draft = release_rows
    db_session.add(ActiveRelease(id=1, release_id=published.id))
    await db_session.commit()
    response = await client.post(
        f"/api/v1/admin/releases/{published.id}/validate",
        headers=await _headers(db_session, True),
    )
    assert response.status_code == 422, response.text
    await db_session.refresh(published)
    assert published.status == ReleaseStatus.PUBLISHED.value
    public = await client.get(f"/api/v1/releases/{published.id}")
    assert public.status_code == 200
    active = await client.get("/api/v1/releases/active")
    assert active.json()["release_id"] == str(published.id)

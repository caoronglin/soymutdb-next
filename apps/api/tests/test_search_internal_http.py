"""R06: real-application HTTP cache-policy assertions for internal search.

The unit-level route-function test exercises the header assignment in
isolation; these tests drive the real FastAPI app (exception handlers and
dependency chain included) so a middleware or handler regression cannot
silently turn an internal response into a shared-cacheable one.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.variant import MutantLine

INTERNAL_SEARCH = "/api/v1/search/internal"


async def _make_role_user(
    db_session, role_name: str, username: str
) -> User:
    role = (
        await db_session.execute(select(Role).where(Role.name == role_name))
    ).scalar_one()
    user = User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@soymutdb.local",
        password_hash="x",
        is_active=True,
        is_deleted=False,
        role_rel=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def published_release_with_line(db_session):
    """Active published release holding one identified mutant line."""
    release = Release(
        version="internal-http-release",
        name="internal http release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    line = MutantLine(
        name="http-lab-1",
        public_id="SMHTTP001",
        release_id=release.id,
    )
    db_session.add(line)
    await db_session.flush()
    return release, line


@pytest.mark.asyncio
async def test_internal_search_success_carries_private_no_store(
    client, db_session, published_release_with_line
):
    release, _line = published_release_with_line
    user = await _make_role_user(db_session, RoleName.RESEARCHER.value, "r06-researcher")
    await db_session.commit()

    response = await client.get(
        INTERNAL_SEARCH,
        params={"query": "SMHTTP001"},
        headers={"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"},
    )
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "private, no-store"
    assert release.status == ReleaseStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_internal_search_anonymous_error_is_private_no_store(
    client, db_session, published_release_with_line
):
    await _make_role_user(db_session, RoleName.RESEARCHER.value, "r06-seed")
    await db_session.commit()

    response = await client.get(INTERNAL_SEARCH, params={"query": "SMHTTP001"})
    assert response.status_code == 401
    assert response.headers.get("Cache-Control") == "private, no-store"


@pytest.mark.asyncio
async def test_internal_search_privileged_error_is_private_no_store(
    client, db_session, published_release_with_line
):
    """A logged-in but under-privileged user gets 403 and no shared caching."""
    user = await _make_role_user(db_session, RoleName.VIEWER.value, "r06-viewer")
    await db_session.commit()

    response = await client.get(
        INTERNAL_SEARCH,
        params={"query": "SMHTTP001"},
        headers={"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"},
    )
    assert response.status_code == 403
    assert response.headers.get("Cache-Control") == "private, no-store"

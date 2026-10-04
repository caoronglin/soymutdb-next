"""Docker-free tests for the additive ``effective_roles`` capability field.

``GET /auth/me`` now answers with the roles the session actually satisfies,
expanded from ``core.security._ROLE_GRANTS``. Before this field the portal kept
a private copy of the role table and it had already drifted: the front end
listed only ``researcher`` and ``administrator``, denying curator,
content_editor, auditor and the four other roles a capability
``require_role(RoleName.RESEARCHER)`` grants them.

Two things are asserted here:

* the pure grant expansion, against the real ``_ROLE_GRANTS`` table, for every
  role (this is what a client reads);
* the HTTP shape of ``/auth/me`` over the same docker-free harness
  ``test_auth_sessions.py`` uses, so the field is proven to be *on the wire*
  and not merely constructible.

.. note:: PostgreSQL-backed coverage of the same field lives in
   ``test_auth.py`` and is skipped without Docker; these run everywhere.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import RoleName, effective_roles, has_role
from app.models.auth import Role

from .test_auth_sessions import (
    AUTH_PREFIX,
    BASE_URL,
    SAME_ORIGIN,
    FakeAuthDB,
    make_user,
)


class TestEffectiveRoles:
    """The expansion every client now depends on."""

    def test_viewer_grants_only_itself(self) -> None:
        assert effective_roles(["viewer"]) == ["viewer"]
        assert not has_role(["viewer"], RoleName.RESEARCHER)

    def test_researcher_grants_researcher(self) -> None:
        assert has_role(["researcher"], RoleName.RESEARCHER)
        assert "curator" not in effective_roles(["researcher"])

    @pytest.mark.parametrize(
        "role",
        [
            "curator",
            "data_manager",
            "track_manager",
            "blast_manager",
            "seed_manager",
            "content_editor",
            "auditor",
        ],
    )
    def test_every_privileged_role_outside_viewer_grants_researcher(self, role: str) -> None:
        # The drift that motivated this field: these roles all satisfy
        # `require_role(RoleName.RESEARCHER)` server-side.
        assert has_role([role], RoleName.RESEARCHER)
        assert "researcher" in effective_roles([role])

    def test_administrator_grants_every_role(self) -> None:
        assert effective_roles(["administrator"]) == [r.value for r in RoleName]

    def test_union_covers_every_grant_of_any_assignment(self) -> None:
        combined = effective_roles(["viewer", "blast_manager"])
        assert combined == effective_roles(["blast_manager"])

    def test_unknown_and_empty_assignments_are_safe(self) -> None:
        assert effective_roles([]) == []
        assert effective_roles(["not_a_role"]) == []
        assert effective_roles(["viewer", "not_a_role"]) == ["viewer"]

    def test_output_order_is_stable_and_privilege_ordered(self) -> None:
        first = effective_roles(["auditor"])
        second = effective_roles(["auditor"])
        assert first == second
        assert first.index("viewer") < first.index("researcher") < first.index("auditor")


@pytest_asyncio.fixture
async def me_env(request):
    """App + fake session whose user carries the role under test.

    Follows the shape ``test_auth_sessions.auth_env`` already uses — an async
    generator fixture that yields a live client — rather than a factory: a
    factory had to open the client in setup and close it in teardown, and that
    split hangs under ``asyncio_mode=auto``.
    """
    from app.core.database import get_db
    from app.main import create_app

    role_name, is_superuser = request.param
    user = make_user()
    user.role_rel = Role(id=uuid.uuid4(), name=role_name)
    user.is_superuser = is_superuser
    # `make_user` leaves the DB-managed timestamps unset; a real row would get
    # them from the column defaults, the in-memory double cannot.
    user.created_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)

    fake_db = FakeAuthDB(user=user)
    application = create_app()

    async def override_get_db():
        yield fake_db

    application.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
        yield client, fake_db, user

    application.dependency_overrides.clear()


@pytest.mark.asyncio
class TestMeEndpoint:
    """The capability field has to be on the wire, not just buildable."""

    async def _login(self, client: AsyncClient, user) -> str:
        login = await client.post(
            f"{AUTH_PREFIX}/login",
            headers={"Origin": SAME_ORIGIN},
            json={"username": user.email, "password": "TestPass123!"},
        )
        assert login.status_code == 200, login.text
        return login.json()["access_token"]

    @pytest.mark.parametrize(
        "me_env, role",
        [
            pytest.param(("viewer", False), "viewer", id="viewer"),
            pytest.param(("researcher", False), "researcher", id="researcher"),
            pytest.param(("curator", False), "curator", id="curator"),
            pytest.param(("administrator", False), "administrator", id="administrator"),
        ],
        indirect=["me_env"],
    )
    async def test_me_reports_effective_roles(self, me_env, role: str) -> None:
        client, _db, user = me_env
        token = await self._login(client, user)

        me = await client.get(
            f"{AUTH_PREFIX}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        body = me.json()
        assert body["role_name"] == role
        assert body["effective_roles"] == effective_roles([role])
        # The wire answer and the server-side grant table must never disagree.
        assert has_role([role], RoleName.RESEARCHER) == (
            "researcher" in body["effective_roles"]
        )

    @pytest.mark.parametrize("me_env", [("viewer", True)], indirect=True)
    async def test_superuser_is_reported_as_administrator_grants(self, me_env) -> None:
        client, _db, user = me_env
        token = await self._login(client, user)

        me = await client.get(
            f"{AUTH_PREFIX}/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        body = me.json()
        # get_user_roles() injects administrator for a superuser, so the
        # expansion is the full set even though role_name still says viewer.
        assert "administrator" in body["effective_roles"]
        assert body["role_name"] == "viewer"

    @pytest.mark.parametrize("me_env", [("researcher", False)], indirect=True)
    async def test_me_still_requires_authentication(self, me_env) -> None:
        client, _db, _user = me_env
        me = await client.get(f"{AUTH_PREFIX}/me")
        assert me.status_code == 401


def test_user_response_defaults_to_empty_grants() -> None:
    """Additive means additive: an old payload without the field still validates."""
    from app.schemas.auth import UserResponse

    now = datetime.now(UTC)
    payload = UserResponse(
        id="1",
        username="u",
        email="u@example.org",
        full_name=None,
        is_active=True,
        is_superuser=False,
        joined_at=now,
        created_at=now,
        updated_at=now,
    )
    assert payload.effective_roles == []

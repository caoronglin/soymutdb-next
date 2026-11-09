"""P0 regression tests for public-registration and resource access boundaries.

These tests are intentionally Docker-free.  They exercise the real FastAPI
dependencies and service methods with small AsyncSession stand-ins so the
security contract remains runnable without Testcontainers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app.api.v1 import tracks as track_routes
from app.api.v1.auth import register
from app.api.v1.deps import get_current_user, get_user_roles
from app.api.v1.seeds import router as seeds_router
from app.core.database import get_db
from app.core.exceptions import (
    AuthenticationError,
    NotFoundError,
    SoyMutDBError,
    ValidationError,
    soy_mut_db_exception_handler,
)
from app.core.security import RoleName, has_role
from app.models.auth import Role, User
from app.models.genomic import Assembly
from app.models.tracks import (
    FileFormat,
    Track,
    TrackStatus,
    TrackType,
    TrackVisibility,
)
from app.schemas.auth import UserCreate
from app.services import track_service as track_service_module
from app.services.release_context import ReleaseContext
from app.services.track_service import TrackService


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


def _registration_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "username": "new_viewer",
        "email": "new_viewer@example.org",
        "password": "SecurePass123!",
        "full_name": "New Viewer",
        "role_name": RoleName.VIEWER.value,
    }
    payload.update(overrides)
    return payload


class _RegistrationSession:
    """Session stand-in that records which role the register route resolves."""

    def __init__(self) -> None:
        self.roles = {
            RoleName.VIEWER.value: Role(id=1, name=RoleName.VIEWER.value),
            RoleName.ADMINISTRATOR.value: Role(
                id=99, name=RoleName.ADMINISTRATOR.value
            ),
        }
        self.role_queries: list[str] = []
        self.added_user: User | None = None

    async def execute(self, stmt: Any) -> _Result:
        sql = str(stmt)
        if "FROM users" in sql:
            return _Result([])
        if "FROM roles" in sql:
            role_name = next(iter(stmt.compile().params.values()))
            self.role_queries.append(str(role_name))
            role = self.roles.get(str(role_name))
            return _Result([role] if role else [])
        return _Result([])

    def add(self, user: User) -> None:
        self.added_user = user

    async def commit(self) -> None:
        return None

    async def refresh(self, user: User) -> None:
        role = next((role for role in self.roles.values() if role.id == user.role_id), None)
        now = datetime.now(UTC)
        user.role_rel = role
        user.is_superuser = False
        user.created_at = now
        user.updated_at = now


def _make_user(
    role: RoleName = RoleName.VIEWER,
    *,
    user_id: uuid.UUID | None = None,
    is_superuser: bool = False,
) -> User:
    return User(
        id=user_id or uuid.uuid4(),
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@example.org",
        password_hash="not-used",
        is_active=True,
        is_deleted=False,
        is_superuser=is_superuser,
        role_rel=Role(id=1, name=role.value),
    )


def test_public_registration_schema_rejects_elevated_role() -> None:
    with pytest.raises(PydanticValidationError):
        UserCreate(**_registration_payload(role_name=RoleName.ADMINISTRATOR.value))


async def test_register_route_resolves_viewer_even_if_schema_is_bypassed() -> None:
    payload = UserCreate(**_registration_payload())
    # Assignment validation is intentionally bypassed to prove the route itself
    # does not trust an already-constructed model from another internal caller.
    payload.role_name = RoleName.ADMINISTRATOR.value
    session = _RegistrationSession()

    response = await register(payload, db=session)  # type: ignore[arg-type]

    assert session.role_queries == [RoleName.VIEWER.value]
    assert session.added_user is not None
    assert session.added_user.role_id == session.roles[RoleName.VIEWER.value].id
    assert response.role_name == RoleName.VIEWER.value


def test_public_registration_preserves_explicit_viewer_payload() -> None:
    payload = UserCreate(**_registration_payload())
    assert payload.role_name == RoleName.VIEWER.value


SPECIALIZED_ROLES = (
    RoleName.DATA_MANAGER,
    RoleName.TRACK_MANAGER,
    RoleName.BLAST_MANAGER,
    RoleName.SEED_MANAGER,
    RoleName.CONTENT_EDITOR,
    RoleName.AUDITOR,
)


def test_specialized_roles_do_not_imply_other_specialized_roles() -> None:
    for held_role in SPECIALIZED_ROLES:
        assert has_role([held_role.value], held_role)
        assert has_role([held_role.value], RoleName.RESEARCHER)
        for required_role in SPECIALIZED_ROLES:
            if required_role != held_role:
                assert not has_role([held_role.value], required_role), (
                    f"{held_role.value} must not imply {required_role.value}"
                )


def test_administrator_and_superuser_preserve_all_role_capabilities() -> None:
    for required_role in RoleName:
        assert has_role([RoleName.ADMINISTRATOR.value], required_role)

    superuser = _make_user(RoleName.VIEWER, is_superuser=True)
    superuser_roles = get_user_roles(superuser)
    for required_role in RoleName:
        assert has_role(superuser_roles, required_role)


class _SeedSession:
    async def execute(self, stmt: Any) -> _Result:
        return _Result([])


@pytest.fixture
def seed_app() -> FastAPI:
    session = _SeedSession()

    async def override_get_db():
        yield session

    application = FastAPI(title="Seed privacy boundary test")
    application.include_router(seeds_router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.dependency_overrides[get_db] = override_get_db
    application.state.current_user = None

    async def override_current_user() -> User:
        user = application.state.current_user
        if user is None:
            raise AuthenticationError("Authentication required")
        return user

    application.dependency_overrides[get_current_user] = override_current_user
    return application


async def _seed_request_list(seed_app: FastAPI) -> Any:
    transport = ASGITransport(app=seed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/seeds/requests")


async def test_seed_request_list_rejects_anonymous_callers(seed_app: FastAPI) -> None:
    response = await _seed_request_list(seed_app)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "is_superuser", "expected_status"),
    [
        (RoleName.VIEWER, False, 403),
        (RoleName.DATA_MANAGER, False, 403),
        (RoleName.TRACK_MANAGER, False, 403),
        (RoleName.SEED_MANAGER, False, 200),
        (RoleName.ADMINISTRATOR, False, 200),
        (RoleName.VIEWER, True, 200),
    ],
)
async def test_seed_request_list_requires_seed_manager_capability(
    seed_app: FastAPI,
    role: RoleName,
    is_superuser: bool,
    expected_status: int,
) -> None:
    seed_app.state.current_user = _make_user(role, is_superuser=is_superuser)
    response = await _seed_request_list(seed_app)
    assert response.status_code == expected_status


def _make_assembly(
    assembly_id: int = 1,
    *,
    release_id: int = 7,
    name: str = "Wm82v5.0",
    fasta_url: str | None = None,
    fai_url: str | None = None,
) -> Assembly:
    return Assembly(
        id=assembly_id,
        name=name,
        species="Glycine max",
        version=name.rsplit("v", maxsplit=1)[-1],
        description=None,
        fasta_url=fasta_url,
        fai_url=fai_url,
        is_default=False,
        release_id=release_id,
    )


def _release_context(
    *,
    release_id: int = 7,
    assembly_id: int | None = 1,
    assembly: str = "Wm82v5.0",
) -> ReleaseContext:
    return ReleaseContext(
        release_id=release_id,
        assembly_id=assembly_id,
        assembly=assembly,
    )


def _make_track(
    track_id: int,
    visibility: TrackVisibility,
    *,
    owner_id: uuid.UUID | None = None,
    project_id: int | None = None,
    status: TrackStatus = TrackStatus.READY,
    index_url: str | None = None,
) -> Track:
    now = datetime.now(UTC)
    return Track(
        id=track_id,
        name=f"Track {track_id}",
        description=None,
        track_type=TrackType.ANNOTATION,
        file_format=FileFormat.BED,
        assembly_id=1,
        release_id=7,
        category_id=None,
        category=None,
        file_url=f"tracks/track-{track_id}.bed.gz",
        index_url=index_url,
        owner_id=owner_id,
        project_id=project_id,
        visibility=visibility,
        status=status,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )


class _TrackSession:
    def __init__(
        self,
        tracks: list[Track],
        project_ids: set[int] | None = None,
        assemblies: list[Assembly] | None = None,
    ) -> None:
        self.tracks = tracks
        self.project_ids = project_ids or set()
        self.assemblies = [_make_assembly()] if assemblies is None else assemblies
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        sql = str(stmt)
        if "FROM project_members" in sql:
            return _Result(sorted(self.project_ids))
        if "FROM assemblies" in sql and "FROM tracks" not in sql:
            return _Result(list(self.assemblies))
        if "FROM tracks" in sql:
            rows = list(self.tracks)
            if "tracks.release_id" in sql:
                rows = [
                    track
                    for track in rows
                    if track.release_id == 7
                ]
            if "tracks.assembly_id" in sql:
                rows = [track for track in rows if track.assembly_id == 1]
            return _Result(rows)
        return _Result([])


async def test_anonymous_track_surfaces_return_only_public_tracks(monkeypatch) -> None:
    public = _make_track(1, TrackVisibility.PUBLIC)
    private = _make_track(2, TrackVisibility.PRIVATE, owner_id=uuid.uuid4())
    project = _make_track(3, TrackVisibility.PROJECT, project_id=7)
    service = TrackService()
    monkeypatch.setattr(
        track_service_module,
        "generate_download_url",
        lambda object_key, **kwargs: f"https://minio.example/{object_key}",
    )

    listed = await service.list_tracks(
        _TrackSession([public, private, project]),
        release_id=7,
        user_id=None,
        user_roles=[],
    )
    assert [track["id"] for track in listed] == ["1"]

    config = await service.get_jbrowse_config(
        _TrackSession([public, private, project]),
        assembly_id=1,
        release_context=_release_context(),
        user_id=None,
        user_roles=[],
    )
    assert [track["trackId"] for track in config["tracks"]] == ["track_1"]

    with pytest.raises(NotFoundError):
        await service.get_track(
            _TrackSession([private]),
            private.id,
            release_id=7,
            user_id=None,
            user_roles=[],
        )


async def test_track_surfaces_fail_closed_for_other_and_unpinned_releases() -> None:
    """A track outside the selected release is hidden, not silently adopted.

    ``tracks.release_id`` is nullable for legacy rows; treating those (or rows
    pinned to another release) as members of the active release would let a
    list hand out track ids that JBrowse itself refuses to render.
    """
    current = _make_track(40, TrackVisibility.PUBLIC)
    other = _make_track(41, TrackVisibility.PUBLIC)
    other.release_id = 8
    unpinned = _make_track(42, TrackVisibility.PUBLIC)
    unpinned.release_id = None
    service = TrackService()

    listed = await service.list_tracks(
        _TrackSession([current, other, unpinned]),
        release_id=7,
        user_id=None,
        user_roles=[],
    )
    assert [track["id"] for track in listed] == ["40"]

    for hidden in (other, unpinned):
        with pytest.raises(NotFoundError):
            await service.get_track(
                _TrackSession([hidden]),
                hidden.id,
                release_id=7,
                user_id=None,
                user_roles=[],
            )


async def test_non_management_track_surfaces_return_only_ready_tracks() -> None:
    ready = _make_track(4, TrackVisibility.PUBLIC)
    pending = _make_track(
        5,
        TrackVisibility.PUBLIC,
        status=TrackStatus.PENDING,
    )
    service = TrackService()

    listed = await service.list_tracks(
        _TrackSession([ready, pending]),
        release_id=7,
        user_id=None,
        user_roles=[],
    )
    assert [track["id"] for track in listed] == ["4"]

    with pytest.raises(NotFoundError):
        await service.get_track(
            _TrackSession([pending]),
            pending.id,
            release_id=7,
            user_id=None,
            user_roles=[],
        )


async def test_public_track_surfaces_do_not_expose_pending_to_manager() -> None:
    pending = _make_track(
        7,
        TrackVisibility.PRIVATE,
        owner_id=uuid.uuid4(),
        status=TrackStatus.PENDING,
    )
    roles = [RoleName.TRACK_MANAGER.value]
    service = TrackService()

    assert await service.list_tracks(
        _TrackSession([pending]),
        release_id=7,
        user_id=uuid.uuid4(),
        user_roles=roles,
    ) == []
    with pytest.raises(NotFoundError):
        await service.get_track(
            _TrackSession([pending]),
            pending.id,
            release_id=7,
            user_id=uuid.uuid4(),
            user_roles=roles,
        )
    with pytest.raises(NotFoundError):
        await service.get_signed_url(
            _TrackSession([pending]),
            track_id=pending.id,
            user_id=uuid.uuid4(),
            user_roles=roles,
        )


async def test_track_detail_does_not_expose_storage_keys() -> None:
    track = _make_track(
        6,
        TrackVisibility.PUBLIC,
        index_url="tracks/track-6.bed.gz.tbi",
    )

    detail = await TrackService().get_track(
        _TrackSession([track]),
        track.id,
        release_id=7,
        user_id=None,
        user_roles=[],
    )

    assert "file_url" not in detail
    assert "index_url" not in detail


async def test_jbrowse_config_presigns_main_and_index_objects(monkeypatch) -> None:
    track = _make_track(
        8,
        TrackVisibility.PUBLIC,
        index_url="tracks/track-8.vcf.gz.tbi",
    )
    track.file_format = FileFormat.VCF
    track.file_url = "tracks/track-8.vcf.gz"
    monkeypatch.setattr(
        track_service_module,
        "generate_download_url",
        lambda object_key, **kwargs: f"https://minio.example/{object_key}?signed=true",
    )

    config = await TrackService().get_jbrowse_config(
        _TrackSession([track]),
        assembly_id=1,
        release_context=_release_context(),
        user_id=None,
        user_roles=[],
    )

    adapter = config["tracks"][0]["adapter"]
    assert adapter["vcfGzLocation"]["uri"].endswith(
        "tracks/track-8.vcf.gz?signed=true"
    )
    assert adapter["index"]["location"]["uri"].endswith(
        "tracks/track-8.vcf.gz.tbi?signed=true"
    )


async def test_track_owner_and_project_member_can_view_their_tracks(monkeypatch) -> None:
    user_id = uuid.uuid4()
    owned = _make_track(10, TrackVisibility.PRIVATE, owner_id=user_id)
    project = _make_track(11, TrackVisibility.PROJECT, project_id=77)
    unrelated = _make_track(12, TrackVisibility.PROJECT, project_id=88)
    service = TrackService()
    monkeypatch.setattr(
        track_service_module,
        "generate_download_url",
        lambda object_key, **kwargs: f"https://minio.example/{object_key}",
        raising=False,
    )

    listed = await service.list_tracks(
        _TrackSession([owned, project, unrelated], project_ids={77}),
        release_id=7,
        user_id=user_id,
        user_roles=[RoleName.VIEWER.value],
    )
    assert {track["id"] for track in listed} == {"10", "11"}

    detail = await service.get_track(
        _TrackSession([project], project_ids={77}),
        project.id,
        release_id=7,
        user_id=user_id,
        user_roles=[RoleName.VIEWER.value],
    )
    assert detail["id"] == "11"

    signed = await service.get_signed_url(
        _TrackSession([project], project_ids={77}),
        track_id=project.id,
        user_id=user_id,
        user_roles=[RoleName.VIEWER.value],
    )
    assert signed.url


async def test_track_signed_url_hides_existence_and_requires_ready() -> None:
    user_id = uuid.uuid4()
    private = _make_track(13, TrackVisibility.PRIVATE, owner_id=uuid.uuid4())
    pending = _make_track(
        14,
        TrackVisibility.PRIVATE,
        owner_id=user_id,
        status=TrackStatus.PENDING,
    )
    service = TrackService()

    with pytest.raises(NotFoundError):
        await service.get_signed_url(
            _TrackSession([private]),
            track_id=private.id,
            user_id=user_id,
            user_roles=[RoleName.VIEWER.value],
        )
    with pytest.raises(NotFoundError):
        await service.get_signed_url(
            _TrackSession([pending]),
            track_id=pending.id,
            user_id=user_id,
            user_roles=[RoleName.VIEWER.value],
        )


async def test_track_signed_url_presigns_main_and_index_objects(monkeypatch) -> None:
    user_id = uuid.uuid4()
    track = _make_track(
        15,
        TrackVisibility.PRIVATE,
        owner_id=user_id,
        index_url="tracks/track-15.bed.gz.tbi",
    )
    track.file_url = "tracks/track-15.bed.gz"
    calls: list[tuple[str, str | None, int]] = []

    def fake_presign(
        object_key: str,
        *,
        bucket: str | None = None,
        expires_in: int,
    ) -> str:
        calls.append((object_key, bucket, expires_in))
        return f"https://minio.example/{object_key}?signed=true"

    monkeypatch.setattr(track_service_module, "generate_download_url", fake_presign)

    signed = await TrackService().get_signed_url(
        _TrackSession([track]),
        track_id=track.id,
        user_id=user_id,
        user_roles=[RoleName.VIEWER.value],
    )

    assert signed.url.endswith("tracks/track-15.bed.gz?signed=true")
    assert signed.index_url is not None
    assert signed.index_url.endswith("tracks/track-15.bed.gz.tbi?signed=true")
    assert signed.expires_in == 600
    assert calls == [
        ("tracks/track-15.bed.gz", "user-tracks", 600),
        ("tracks/track-15.bed.gz.tbi", "user-tracks", 600),
    ]


async def test_only_track_manager_or_administrator_can_bypass_track_ownership() -> None:
    private = _make_track(20, TrackVisibility.PRIVATE, owner_id=uuid.uuid4())
    service = TrackService()

    denied = await service.list_tracks(
        _TrackSession([private]),
        release_id=7,
        user_id=uuid.uuid4(),
        user_roles=[RoleName.SEED_MANAGER.value],
    )
    assert denied == []

    for role in (RoleName.TRACK_MANAGER, RoleName.ADMINISTRATOR):
        visible = await service.list_tracks(
            _TrackSession([private]),
            release_id=7,
            user_id=uuid.uuid4(),
            user_roles=[role.value],
        )
        assert [track["id"] for track in visible] == ["20"]


async def test_track_routes_forward_optional_user_access_context(monkeypatch) -> None:
    mocked_service = SimpleNamespace(
        list_tracks=AsyncMock(return_value=[]),
        get_track=AsyncMock(return_value={}),
        get_jbrowse_config=AsyncMock(return_value={"assembly": {}, "tracks": []}),
    )
    monkeypatch.setattr(track_routes, "service", mocked_service)
    db = object()

    # Anonymous list/detail responses vary by Authorization and may be shared
    # only in their public projection.
    list_response = Response()
    await track_routes.list_tracks(
        response=list_response,
        db=db,
        assembly_id=None,
        category_id=None,
        release_context=_release_context(),
        current_user=None,
    )
    assert list_response.headers["Vary"] == "Authorization"
    assert list_response.headers["Cache-Control"].startswith("public")

    response = Response()
    await track_routes.get_jbrowse_config(
        response=response,
        assembly_id=1,
        db=db,
        release_context=_release_context(),
        current_user=None,
    )
    assert response.headers["Cache-Control"].startswith("public")
    assert response.headers["Vary"] == "Authorization"

    owner = _make_user(RoleName.VIEWER)
    detail_response = Response()
    await track_routes.get_track(
        track_id=5,
        response=detail_response,
        db=db,
        release_context=_release_context(),
        current_user=owner,
    )
    # An authenticated projection (owner/visibility) is never shareable.
    assert detail_response.headers["Cache-Control"] == "private, no-store"
    assert detail_response.headers["Vary"] == "Authorization"

    mocked_service.list_tracks.assert_awaited_once_with(
        db,
        assembly_id=None,
        category_id=None,
        release_id=7,
        user_id=None,
        user_roles=[],
    )
    mocked_service.get_jbrowse_config.assert_awaited_once_with(
        db,
        assembly_id=1,
        release_context=_release_context(),
        user_id=None,
        user_roles=[],
    )
    mocked_service.get_track.assert_awaited_once_with(
        db,
        5,
        release_id=7,
        user_id=owner.id,
        user_roles=[RoleName.VIEWER.value],
    )


@pytest.mark.asyncio
async def test_jbrowse_config_binds_release_and_assembly_identity(monkeypatch) -> None:
    track = _make_track(30, TrackVisibility.PUBLIC)
    session = _TrackSession(
        [track],
        assemblies=[
            _make_assembly(
                assembly_id=1,
                release_id=7,
                name="Wm82v5.0",
                fasta_url="https://data.example/Wm82_v5.fa.gz",
                fai_url="https://data.example/Wm82_v5.fa.gz.fai",
            )
        ],
    )
    monkeypatch.setattr(
        track_service_module,
        "generate_download_url",
        lambda object_key, **kwargs: f"https://minio.example/{object_key}",
    )

    config = await TrackService().get_jbrowse_config(
        session,
        assembly_id=1,
        release_context=_release_context(),
        user_id=None,
        user_roles=[],
    )

    assert config["release_id"] == 7
    assert config["assembly_id"] == 1
    assert config["release"] == {"id": 7, "assembly_id": 1}
    assert config["assembly"]["id"] == 1
    assert config["assembly"]["name"] == "Wm82v5.0"
    assert config["assembly"]["sequence"]["adapter"]["fastaLocation"]["uri"].endswith(
        "Wm82_v5.fa.gz"
    )
    assert [item["trackId"] for item in config["tracks"]] == ["track_30"]
    sql = "\\n".join(str(statement) for statement in session.statements)
    assert "assemblies.release_id" in sql
    assert "tracks.assembly_id" in sql


@pytest.mark.asyncio
async def test_jbrowse_config_rejects_missing_or_cross_release_assembly() -> None:
    service = TrackService()

    with pytest.raises(ValidationError, match="no assembly identity"):
        await service.get_jbrowse_config(
            _TrackSession([]),
            assembly_id=1,
            release_context=_release_context(assembly_id=None),
            user_id=None,
            user_roles=[],
        )

    with pytest.raises(ValidationError, match="does not belong"):
        await service.get_jbrowse_config(
            _TrackSession([]),
            assembly_id=2,
            release_context=_release_context(assembly_id=1),
            user_id=None,
            user_roles=[],
        )


@pytest.mark.asyncio
async def test_jbrowse_config_rejects_assembly_not_in_release() -> None:
    session = _TrackSession([], assemblies=[])

    with pytest.raises(NotFoundError, match="not available in release 7"):
        await TrackService().get_jbrowse_config(
            session,
            assembly_id=1,
            release_context=_release_context(),
            user_id=None,
            user_roles=[],
        )


@pytest.mark.asyncio
async def test_authenticated_jbrowse_config_is_private_and_not_cacheable(monkeypatch) -> None:
    user = _make_user(RoleName.VIEWER)
    mocked_service = SimpleNamespace(
        get_jbrowse_config=AsyncMock(return_value={"assembly": {}, "tracks": []}),
    )
    monkeypatch.setattr(track_routes, "service", mocked_service)
    response = Response()

    await track_routes.get_jbrowse_config(
        response=response,
        assembly_id=1,
        db=object(),
        release_context=_release_context(),
        current_user=user,
    )

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Vary"] == "Authorization"

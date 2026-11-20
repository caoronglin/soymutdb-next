"""Site-brand and species-instance health contracts.

The two features share one rule: the console may read a small, explicit
projection of a peer and write nothing to it. Brand values are per-variant and
versioned; instance health is bounded operational metadata that never carries
biology or credentials.

Offline migration checks run everywhere; the service tests need PostgreSQL
(``SOYMUTDB_TEST_DATABASE_URL`` or testcontainers).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SettingsVersionConflictError
from app.core.exceptions import ValidationError as SoyValidationError
from app.core.site_variant import SiteVariant
from app.models.auth import User
from app.models.media import MediaAsset
from app.models.table_views import SpeciesInstance
from app.schemas.site import SiteBrandPatchValues
from app.schemas.table_views import SpeciesInstanceCreate, SpeciesInstanceUpdate
from app.services import site_brand_service
from app.services import species_instance_health_service as health_service

API_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Migration 0040: offline contracts (no database required)
# ---------------------------------------------------------------------------


def _offline_alembic(command: str, revision_range: str) -> str:
    environment = os.environ.copy()
    workspace_root = API_ROOT.parents[1]
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(workspace_root / "packages/jobs-py/src"),
            str(API_ROOT),
            environment.get("PYTHONPATH", ""),
        ]
    )
    environment["SOYMUTDB_DATABASE_URL"] = "postgresql+asyncpg://offline:offline@localhost/offline"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            command,
            revision_range,
            "--sql",
        ],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_0040_upgrade_adds_bounded_health_columns_and_check_constraint() -> None:
    sql = _offline_alembic("upgrade", "0039:0040")

    for column in (
        "connection_state",
        "last_checked_at",
        "last_error_at",
        "last_error_code",
    ):
        assert f"ADD COLUMN {column}" in sql
    assert "'unknown'::character varying" in sql or "DEFAULT 'unknown'" in sql
    assert "ck_species_instances_connection_state" in sql
    # Health is operational metadata only: no biological or credential column.
    for forbidden in ("token", "password", "public_id", "internal_id", "coordinates"):
        assert forbidden not in sql.lower()


def test_0041_seeds_the_local_instance_without_clobbering_operator_rows() -> None:
    sql = _offline_alembic("upgrade", "0040:0041")

    assert "INSERT INTO species_instances" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "is_local" in sql
    # A seed must never overwrite or delete what an operator registered.
    # (The offline SQL also carries Alembic's own alembic_version bookkeeping.)
    lowered = sql.lower()
    assert "delete from species_instances" not in lowered
    assert "update species_instances" not in lowered
    # Console metadata only: no biological tables are touched.
    for forbidden in ("variant", "gene", "mutant", "public_id"):
        assert forbidden not in lowered


def test_0041_downgrade_removes_only_the_untouched_seed() -> None:
    sql = _offline_alembic("downgrade", "0041:0040")

    assert "DELETE FROM species_instances" in sql
    for guard in ("code = ", "name = ", "api_base_url = ", "is_local"):
        assert guard in sql


def test_0042_repairs_model_schema_drift_with_backfills() -> None:
    sql = _offline_alembic("upgrade", "0041:0042")

    # Bilingual fields are backfilled from the legacy single-language columns
    # and only then made NOT NULL.
    assert "ALTER TABLE news_articles ADD COLUMN title_en" in sql
    assert "ALTER TABLE static_pages ADD COLUMN title_en" in sql
    assert "UPDATE news_articles SET title_en = title" in sql
    assert "UPDATE static_pages SET content_en = content" in sql
    assert "ALTER COLUMN title_en SET NOT NULL" in sql
    # Legacy columns are backfilled rather than dropped.
    assert "db_path" in sql and "UPDATE blast_databases SET file_path = db_path" in sql
    assert "UPDATE track_categories SET display_order = sort_order" in sql
    # The missing table is created.
    assert "CREATE TABLE content_versions" in sql
    # No destructive statement on existing data tables.
    for forbidden in (
        "DROP TABLE news_articles",
        "DROP TABLE static_pages",
        "DROP COLUMN title",
        "DROP COLUMN content",
    ):
        assert forbidden not in sql


def test_0042_downgrade_drops_only_added_objects() -> None:
    sql = _offline_alembic("downgrade", "0042:0041")

    assert "DROP TABLE content_versions" in sql
    assert "DROP COLUMN title_en" in sql
    assert "DROP COLUMN is_featured" in sql
    # The pre-0042 tables themselves must survive the rollback.
    assert "DROP TABLE news_articles" not in sql
    assert "DROP TABLE static_pages" not in sql
    assert "DROP TABLE tracks" not in sql


def test_0040_downgrade_drops_constraint_before_columns() -> None:
    sql = _offline_alembic("downgrade", "0040:0039")

    assert "DROP CONSTRAINT ck_species_instances_connection_state" in sql
    constraint_at = sql.index("DROP CONSTRAINT ck_species_instances_connection_state")
    for column in ("connection_state", "last_checked_at", "last_error_at", "last_error_code"):
        assert sql.index(f"DROP COLUMN {column}") > constraint_at


# ---------------------------------------------------------------------------
# Instance URL contract (no database required)
# ---------------------------------------------------------------------------


def test_remote_instance_requires_https_origin() -> None:
    with pytest.raises(ValidationError):
        SpeciesInstanceCreate(
            code="peer",
            name="Peer",
            species="Glycine max",
            api_base_url="http://peer.example.org",
            is_local=False,
        )

    local = SpeciesInstanceCreate(
        code="local",
        name="Local",
        species="Glycine max",
        api_base_url="http://localhost:8010",
        is_local=True,
    )
    assert local.api_base_url == "http://localhost:8010"


def test_instance_urls_reject_credentials_query_and_paths() -> None:
    for bad in (
        "https://user:pass@peer.example.org",
        "https://peer.example.org?token=1",
        "https://peer.example.org/api/v1",
    ):
        with pytest.raises(ValidationError):
            SpeciesInstanceCreate(
                code="peer",
                name="Peer",
                species="Glycine max",
                api_base_url=bad,
            )


def test_site_url_alias_maps_to_portal_base_url_and_cannot_disagree() -> None:
    # `site_url` is accepted as an alias by the model's before-validator, not
    # as a declared field, so it is passed through `model_validate`: the
    # keyword form would be a type error even though the runtime contract is
    # exactly what this test pins.
    created = SpeciesInstanceCreate.model_validate({
        "code": "peer",
        "name": "Peer",
        "species": "Glycine max",
        "api_base_url": "https://peer.example.org",
        "site_url": "https://portal.example.org",
    })
    assert created.portal_base_url == "https://portal.example.org"

    with pytest.raises(ValidationError):
        SpeciesInstanceUpdate.model_validate({
            "site_url": "https://portal.example.org",
            "portal_base_url": "https://other.example.org",
        })


# ---------------------------------------------------------------------------
# Health allowlist and staleness helpers (no database required)
# ---------------------------------------------------------------------------


def test_health_allowlist_keeps_only_exact_https_origins() -> None:
    origins = health_service.configured_health_origins(
        "https://peer.example.org, https://peer.example.org:8443/,\n"
        "http://plain.example.org, https://user:pass@bad.example.org, not-a-url"
    )
    assert origins == frozenset({"https://peer.example.org", "https://peer.example.org:8443"})


def test_health_staleness_tracks_only_real_probe_states() -> None:
    instance = SpeciesInstance(
        code="peer",
        name="Peer",
        species="Glycine max",
        api_base_url="https://peer.example.org",
        connection_state="unknown",
    )
    assert health_service.is_instance_health_stale(instance) is True

    instance.connection_state = "healthy"
    instance.last_checked_at = datetime.now(UTC) - timedelta(minutes=1)
    assert health_service.is_instance_health_stale(instance) is False
    instance.last_checked_at = datetime.now(UTC) - timedelta(minutes=30)
    assert health_service.is_instance_health_stale(instance) is True

    instance.connection_state = "disabled"
    instance.last_checked_at = None
    # "disabled" is not a probe outcome, so it is stale until one exists.
    assert health_service.is_instance_health_stale(instance) is True


# ---------------------------------------------------------------------------
# PostgreSQL-backed service tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def actor(db_session: AsyncSession) -> uuid.UUID:
    user = User(
        username=f"brand-actor-{uuid.uuid4().hex[:8]}",
        email=f"brand-actor-{uuid.uuid4().hex[:8]}@example.org",
        password_hash="not-used",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user.id


def _media_asset(actor_id: uuid.UUID, *, object_key: str, status: str = "ready") -> MediaAsset:
    return MediaAsset(
        object_key=object_key,
        public_url=f"http://localhost:8080/files/{object_key}",
        original_filename=object_key.rsplit("/", 1)[-1],
        purpose="site-icon",
        content_type="image/png",
        size_bytes=1024,
        checksum_sha256="a" * 64,
        width=64,
        height=64,
        status=status,
        uploaded_by=actor_id,
    )


@pytest.mark.integration
async def test_brand_defaults_are_isolated_per_site_variant(
    db_session: AsyncSession, actor: uuid.UUID
) -> None:
    external = await site_brand_service.get_site_brand_document(
        db_session, variant=SiteVariant.EXTERNAL
    )
    assert external.version == 0
    assert external.values.name_zh == "SoyMutDB"
    assert external.values.name_en == "SoyMutDB"
    assert external.values.icon_url is None

    updated = await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.EXTERNAL,
        expected_version=0,
        values=SiteBrandPatchValues(name_zh="大豆突变体数据库"),
        actor_id=actor,
        ip_address=None,
    )
    assert updated.version == 1
    assert updated.values.name_zh == "大豆突变体数据库"

    internal = await site_brand_service.get_site_brand_document(
        db_session, variant=SiteVariant.INTERNAL
    )
    assert internal.version == 0
    assert internal.values.name_zh == "SoyMutDB"


@pytest.mark.integration
async def test_brand_patch_rejects_a_stale_revision(
    db_session: AsyncSession, actor: uuid.UUID
) -> None:
    await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.INTERNAL,
        expected_version=0,
        values=SiteBrandPatchValues(name_en="Internal"),
        actor_id=actor,
        ip_address=None,
    )

    with pytest.raises(SettingsVersionConflictError):
        await site_brand_service.patch_site_brand(
            db_session,
            variant=SiteVariant.INTERNAL,
            expected_version=0,
            values=SiteBrandPatchValues(name_en="Overwrite"),
            actor_id=actor,
            ip_address=None,
        )


@pytest.mark.integration
async def test_brand_icon_requires_a_ready_uploaded_raster(
    db_session: AsyncSession, actor: uuid.UUID
) -> None:
    ready = _media_asset(actor, object_key="uploads/icons/site.png")
    archived = _media_asset(actor, object_key="uploads/icons/old.png", status="archived")
    db_session.add_all([ready, archived])
    await db_session.commit()
    await db_session.refresh(ready)

    updated = await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.EXTERNAL,
        expected_version=0,
        values=SiteBrandPatchValues(icon_url=ready.public_url),
        actor_id=actor,
        ip_address=None,
    )
    assert updated.values.icon_url == ready.public_url

    # An archived upload and an arbitrary external URL are both rejected.
    for bad_url in (archived.public_url, "https://evil.example/icon.png"):
        with pytest.raises(SoyValidationError):
            await site_brand_service.patch_site_brand(
                db_session,
                variant=SiteVariant.EXTERNAL,
                expected_version=1,
                values=SiteBrandPatchValues(icon_url=bad_url),
                actor_id=actor,
                ip_address=None,
            )

    cleared = await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.EXTERNAL,
        expected_version=1,
        values=SiteBrandPatchValues(icon_url=None),
        actor_id=actor,
        ip_address=None,
    )
    assert cleared.values.icon_url is None


@pytest.mark.integration
async def test_brand_names_reject_markup_and_blank_values(
    db_session: AsyncSession, actor: uuid.UUID
) -> None:
    with pytest.raises(SoyValidationError):
        await site_brand_service.patch_site_brand(
            db_session,
            variant=SiteVariant.EXTERNAL,
            expected_version=0,
            values=SiteBrandPatchValues(name_zh="<script>alert(1)</script>"),
            actor_id=actor,
            ip_address=None,
        )

    with pytest.raises(ValidationError):
        SiteBrandPatchValues(name_zh="   ")


@pytest.mark.integration
async def test_local_instance_is_healthy_without_a_network_probe(
    db_session: AsyncSession, actor: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_probe(*_args, **_kwargs):  # pragma: no cover - asserted
        raise AssertionError("the local instance must not be probed over the network")

    monkeypatch.setattr(health_service, "_probe_registered_peer", _must_not_probe)

    instance = SpeciesInstance(
        code="local",
        name="Local",
        species="Glycine max",
        api_base_url="http://localhost:8010",
        is_local=True,
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    result = await health_service.check_species_instance_health(
        db_session, instance_id=instance.id, actor_id=actor, ip_address=None
    )
    assert result.connection_state == "healthy"
    assert result.remote_management == "local"
    assert result.is_stale is False


@pytest.mark.integration
async def test_disabled_instance_reports_disabled_without_probing(
    db_session: AsyncSession, actor: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _must_not_probe(*_args, **_kwargs):  # pragma: no cover - asserted
        raise AssertionError("a disabled instance must not be probed")

    monkeypatch.setattr(health_service, "_probe_registered_peer", _must_not_probe)

    instance = SpeciesInstance(
        code="peer-off",
        name="Peer off",
        species="Glycine max",
        api_base_url="https://peer.example.org",
        is_enabled=False,
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    result = await health_service.check_species_instance_health(
        db_session, instance_id=instance.id, actor_id=actor, ip_address=None
    )
    assert result.connection_state == "disabled"
    assert result.remote_management == "registration_only"


@pytest.mark.integration
async def test_remote_instance_stays_unconfigured_without_an_allowlist(
    db_session: AsyncSession, actor: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(health_service.HEALTH_ALLOWLIST_ENV, raising=False)

    instance = SpeciesInstance(
        code="peer-cn",
        name="Peer CN",
        species="Glycine max",
        api_base_url="https://peer.example.org",
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    result = await health_service.check_species_instance_health(
        db_session, instance_id=instance.id, actor_id=actor, ip_address=None
    )
    assert result.connection_state == "unconfigured"
    assert result.error_code == "trust_not_configured"
    assert result.last_checked_at is None


@pytest.mark.integration
async def test_allowlisted_remote_probe_persists_bounded_health_state(
    db_session: AsyncSession, actor: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(health_service.HEALTH_ALLOWLIST_ENV, "https://peer.example.org")

    instance = SpeciesInstance(
        code="peer-cn",
        name="Peer CN",
        species="Glycine max",
        api_base_url="https://peer.example.org",
    )
    db_session.add(instance)
    await db_session.commit()
    await db_session.refresh(instance)

    async def _healthy(_instance: SpeciesInstance) -> tuple[str, str | None, bool]:
        return "healthy", None, True

    monkeypatch.setattr(health_service, "_probe_registered_peer", _healthy)
    healthy = await health_service.check_species_instance_health(
        db_session, instance_id=instance.id, actor_id=actor, ip_address=None
    )
    assert healthy.connection_state == "healthy"
    assert healthy.last_checked_at is not None

    async def _unhealthy(_instance: SpeciesInstance) -> tuple[str, str | None, bool]:
        return "unhealthy", "timeout", True

    monkeypatch.setattr(health_service, "_probe_registered_peer", _unhealthy)
    unhealthy = await health_service.check_species_instance_health(
        db_session, instance_id=instance.id, actor_id=actor, ip_address=None
    )
    assert unhealthy.connection_state == "unhealthy"
    assert unhealthy.error_code == "timeout"
    assert unhealthy.last_error_at is not None
    assert unhealthy.remote_management == "registration_only"


@pytest.mark.integration
async def test_unknown_instance_health_is_not_found(
    db_session: AsyncSession, actor: uuid.UUID
) -> None:
    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await health_service.check_species_instance_health(
            db_session, instance_id=999_999, actor_id=actor, ip_address=None
        )


# ---------------------------------------------------------------------------
# Public branding endpoint: cache policy and the internal read boundary
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_public_branding_serves_saved_values_with_a_shared_cache(
    client, db_session: AsyncSession, actor: uuid.UUID
) -> None:
    await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.EXTERNAL,
        expected_version=0,
        values=SiteBrandPatchValues(name_zh="大豆库", name_en="SoyMutDB"),
        actor_id=actor,
        ip_address=None,
    )

    response = await client.get("/api/v1/site/branding?variant=external")

    assert response.status_code == 200
    body = response.json()
    assert body["variant"] == "external"
    assert body["name_zh"] == "大豆库"
    assert body["name_en"] == "SoyMutDB"
    assert body["icon_url"] is None
    assert response.headers["cache-control"].startswith("public")


@pytest.mark.integration
async def test_internal_branding_never_reaches_an_anonymous_cache(
    app, client, db_session: AsyncSession, actor: uuid.UUID
) -> None:
    await site_brand_service.patch_site_brand(
        db_session,
        variant=SiteVariant.INTERNAL,
        expected_version=0,
        values=SiteBrandPatchValues(name_en="SoyMutDB Internal"),
        actor_id=actor,
        ip_address=None,
    )

    anonymous = await client.get("/api/v1/site/branding?variant=internal")
    assert anonymous.status_code == 401
    assert "SoyMutDB Internal" not in anonymous.text

    from types import SimpleNamespace

    from app.api.v1.deps import get_optional_user

    viewer = SimpleNamespace(
        id=uuid.uuid4(),
        is_superuser=False,
        is_active=True,
        is_deleted=False,
        role_rel=SimpleNamespace(name="researcher"),
    )
    app.dependency_overrides[get_optional_user] = lambda: viewer

    internal = await client.get("/api/v1/site/branding?variant=internal")
    assert internal.status_code == 200
    assert internal.json()["name_en"] == "SoyMutDB Internal"
    assert internal.headers["cache-control"] == "private, no-store"
    assert internal.headers["vary"] == "Authorization"

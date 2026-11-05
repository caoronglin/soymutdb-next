"""Provenance manifests for catalogued files and variant exports.

The database is a scientific database: a downloader must be able to cite and
verify what they received. These tests pin the three things that turn a
manifest into evidence rather than decoration:

* a produced artifact's manifest reports the byte digest written by the worker
  (and the licence/generation time), not an invented value;
* an artifact that predates checksum recording is reported as ``sha256: null``
  with ``sha256_state='not_recorded'`` — never an empty string or all-zero
  digest that would look verified;
* the manifest echoes only public filter keys. The resolved mutant-line name
  is a worker join key, and the raw filters column also holds it; neither may
  leak through a public endpoint. Internal persistence ids are absent too.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.variant_export import VariantExport, VariantExportStatus
from app.services.variant_export_service import (
    PUBLIC_MANIFEST_FILTER_KEYS,
    _public_manifest_filters,
)


async def _published_release(db_session, slug: str) -> Release:
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    return release


async def _make_user(db_session, role_name: str, username: str) -> User:
    role = (
        await db_session.execute(select(Role).where(Role.name == role_name))
    ).scalar_one()
    user = User(
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


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}


async def _seed_export(
    db_session,
    owner: User,
    *,
    sha256: str | None,
    filters: dict | None = None,
) -> VariantExport:
    record = VariantExport(
        id=uuid.uuid4(),
        user_id=owner.id,
        status=VariantExportStatus.SUCCEEDED,
        release_key="7",
        assembly_key="Wm82.a4.v1",
        format="tsv",
        compress=True,
        filters=filters or {"assembly": "Wm82.a4.v1", "chromosome": "chr01"},
        artifact_path="exports/soymutdb_export.tsv.gz",
        record_count=12,
        file_size=2048,
        sha256=sha256,
        license="CC-BY-4.0",
        generated_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(record)
    await db_session.commit()
    return record


# ---------------------------------------------------------------------------
# Manifest of a verified artifact.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_reports_the_worker_recorded_digest(client, db_session):
    await _published_release(db_session, "prov")
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-prov")
    await db_session.commit()
    digest = "a" * 64
    record = await _seed_export(db_session, owner, sha256=digest)

    response = await client.get(
        f"/api/v1/variants/export/{record.id}/manifest", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == digest
    assert body["sha256_state"] == "recorded"
    assert body["license"] == "CC-BY-4.0"
    assert body["generated_at"] is not None
    assert body["release_key"] == "7"
    assert body["assembly_key"] == "Wm82.a4.v1"
    assert body["filters"] == {
        "assembly": "Wm82.a4.v1",
        "chromosome": "chr01",
    }
    assert response.headers["cache-control"] == "private, no-store"


# ---------------------------------------------------------------------------
# A legacy artifact must not be presented as verified.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_of_a_legacy_artifact_never_invents_a_digest(client, db_session):
    await _published_release(db_session, "legacy")
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-legacy")
    await db_session.commit()
    record = await _seed_export(db_session, owner, sha256=None)

    response = await client.get(
        f"/api/v1/variants/export/{record.id}/manifest", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] is None
    assert body["sha256_state"] == "not_recorded"
    assert body["sha256"] != ""
    assert body["sha256"] != "0" * 64


# ---------------------------------------------------------------------------
# Negative leakage: internal join keys and ids never reach a public response.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manifest_never_leaks_the_worker_join_key(client, db_session):
    await _published_release(db_session, "leak")
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-leak")
    await db_session.commit()
    secret_name = "internal-mutant-line-name-do-not-echo"
    record = await _seed_export(
        db_session,
        owner,
        sha256="b" * 64,
        filters={
            "assembly": "Wm82.a4.v1",
            "release_key": "7",
            "mutant_line_name": secret_name,
            "user_id": str(uuid.uuid4()),
        },
    )

    response = await client.get(
        f"/api/v1/variants/export/{record.id}/manifest", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    text = response.text
    assert secret_name not in text
    assert "mutant_line_name" not in text
    assert "user_id" not in text
    assert str(record.id) in text  # the public export id itself is fine
    assert response.json()["filters"] == {"assembly": "Wm82.a4.v1"}


@pytest.mark.asyncio
async def test_manifest_is_not_visible_to_another_researcher(client, db_session):
    await _published_release(db_session, "owner")
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner2")
    stranger = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-stranger")
    await db_session.commit()
    record = await _seed_export(db_session, owner, sha256="c" * 64)

    response = await client.get(
        f"/api/v1/variants/export/{record.id}/manifest", headers=_auth(stranger)
    )

    assert response.status_code == 404, "a foreign export's existence must not be disclosed"


def test_public_filter_whitelist_has_no_internal_keys() -> None:
    """The whitelist itself is the contract; assert the dangerous keys are out."""
    assert "mutant_line_name" not in PUBLIC_MANIFEST_FILTER_KEYS
    assert "release_key" not in PUBLIC_MANIFEST_FILTER_KEYS
    assert "user_id" not in PUBLIC_MANIFEST_FILTER_KEYS
    assert "id" not in PUBLIC_MANIFEST_FILTER_KEYS


def test_public_manifest_filters_drops_unknown_and_enum_values() -> None:
    class _Enum:
        value = "SNP"

    result = _public_manifest_filters({
        "assembly": "Wm82.a4.v1",
        "variant_type": _Enum(),
        "mutant_line_name": "secret",
        "start": 100,
        "end": None,
    })
    assert result == {
        "assembly": "Wm82.a4.v1",
        "variant_type": "SNP",
        "start": 100,
    }


# ---------------------------------------------------------------------------
# Query builder: whitelist, no silently ignored filters, same pipeline.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_builder_submits_through_the_existing_export_pipeline(client, db_session):
    from app.models.content import Release
    from app.models.data_publishing import ActiveRelease
    from app.models.genomic import Assembly
    from app.models.outbox import OutboxEvent
    from app.models.variant_facts import variant_facts

    release = Release(
        version="prov-q-release", name="prov q release",
        status=ReleaseStatus.PUBLISHED, assembly="Wm82.a4.v1",
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    assembly_row = Assembly(
        name="Wm82.a4.v1", version="v4", species="Glycine max",
        is_default=True, release_id=release.id,
    )
    db_session.add(assembly_row)
    await db_session.flush()
    await db_session.execute(variant_facts.insert(), {
        "release_id": release.id, "assembly_id": assembly_row.id,
        "variant_id": 1, "assembly_key": "Wm82.a4.v1",
        "chromosome": "chr01", "position": 100,
        "ref_allele": "A", "alt_allele": "T", "variant_type": "SNP",
    })
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-q")
    await db_session.commit()

    response = await client.post(
        "/api/v1/exports/query",
        json={"format": "vcf", "filters": {"assembly": "Wm82.a4.v1", "chromosome": "chr01"}},
        headers=_auth(owner),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["format"] == "vcf"
    assert body["applied_filters"] == {"assembly": "Wm82.a4.v1", "chromosome": "chr01"}
    event = (
        await db_session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == body["export_id"])
        )
    ).scalar_one()
    assert event.payload["task_name"] == "soymutdb_worker.tasks.export.export_variants"
    assert event.payload["kwargs"]["filters"]["release_key"] == str(release.id)
    assert event.payload["kwargs"]["filters"]["assembly"] == "Wm82.a4.v1"


@pytest.mark.asyncio
async def test_query_builder_refuses_an_unbacked_filter(client, db_session):
    from app.models.data_publishing import ActiveRelease

    release = await _published_release(db_session, "prov-refuse")
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-q-refuse")
    await db_session.commit()

    response = await client.post(
        "/api/v1/exports/query",
        json={"filters": {"go_term": "GO:0008150"}},
        headers=_auth(owner),
    )

    assert response.status_code == 422, response.text
    assert "go_term" in response.text


def test_query_builder_whitelist_contains_no_unbacked_filters() -> None:
    from app.schemas.export_query import (
        SUPPORTED_QUERY_FILTERS,
        UNSUPPORTED_QUERY_FILTERS,
    )

    assert SUPPORTED_QUERY_FILTERS.isdisjoint(UNSUPPORTED_QUERY_FILTERS)
    assert "go_term" in UNSUPPORTED_QUERY_FILTERS
    assert "species" in UNSUPPORTED_QUERY_FILTERS

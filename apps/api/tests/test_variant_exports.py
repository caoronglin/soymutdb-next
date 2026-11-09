"""Owner-scoped variant exports: submit → status → download.

The export request used to leave no owner-visible trace: the outbox carried
the command, the Celery result backend is disposable, so neither the API nor
the submitter could learn whether the export finished or where the file is.

These tests run against a real PostgreSQL database (the session fixture
provides one) and pin the three properties that matter:

* the request writes the export record **and** the outbox event in one
  transaction, so a committed request always has both;
* only the submitter and an administrator may read an export — the
  unguessable id is never the authorization, and a stranger's export is
  reported as missing rather than as forbidden;
* the download URL is signed on demand for a short window; the stored
  artifact is an object key, never a URL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from soymutdb_jobs.export_artifact import (
    build_export_artifact_key,
    build_export_filename,
)
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly
from app.models.outbox import OutboxEvent
from app.models.variant_export import VariantExport, VariantExportStatus
from app.models.variant_facts import variant_facts

pytestmark = pytest.mark.asyncio


#: The assembly namespace the fixture publishes variants in.
EXPORT_ASSEMBLY = "Wm82.a4.v1"


async def _published_release(
    db_session, slug: str = "export", *, assembly: str | None = None
) -> Release:
    release = Release(
        version=f"{slug}-release",
        name=f"{slug} release",
        status=ReleaseStatus.PUBLISHED,
        # The release's assembly scope. ``None`` models a release that was
        # published without one (the scope column is nullable).
        assembly=assembly,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    # An export is refused when the release publishes no variants in the
    # requested namespace, so the fixture has to publish one: otherwise every
    # submission in this file would be refused for the wrong reason.
    assembly_row = Assembly(
        name=EXPORT_ASSEMBLY,
        version="v4",
        species="Glycine max",
        is_default=True,
        release_id=release.id,
    )
    db_session.add(assembly_row)
    await db_session.flush()
    await db_session.execute(
        variant_facts.insert(),
        {
            "release_id": release.id,
            "assembly_id": assembly_row.id,
            "variant_id": 1,
            "assembly_key": EXPORT_ASSEMBLY,
            "chromosome": "chr01",
            "position": 100,
            "ref_allele": "A",
            "alt_allele": "T",
            "variant_type": "SNP",
        },
    )
    await db_session.flush()
    return release


async def _publish_facts(db_session, release: Release, assembly_key: str) -> None:
    """Publish one variant in *assembly_key*.

    An export of a namespace the release holds no variants in is refused, so
    a test that exports another namespace has to publish it first.
    """
    assembly_row = Assembly(
        name=assembly_key,
        version="v4",
        species="Glycine max",
        release_id=release.id,
    )
    db_session.add(assembly_row)
    await db_session.flush()
    await db_session.execute(
        variant_facts.insert(),
        {
            "release_id": release.id,
            "assembly_id": assembly_row.id,
            # A distinct identity per namespace: the release/variant pair is
            # unique across the whole release.
            "variant_id": 9001,
            "assembly_key": assembly_key,
            "chromosome": "chr01",
            "position": 100,
            "ref_allele": "A",
            "alt_allele": "T",
            "variant_type": "SNP",
        },
    )
    await db_session.flush()


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


async def _submit(client, headers, **overrides) -> dict:
    body = {
        "format": "tsv",
        "compress": True,
        "filters": {"assembly": "Wm82.a4.v1", "chromosome": "chr01"},
    }
    body.update(overrides)
    response = await client.post("/api/v1/variants/export", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 1. Submission writes the record and the command event together.
# ---------------------------------------------------------------------------


async def test_submission_keeps_the_legacy_response_shape(client, db_session):
    await _published_release(db_session)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    await db_session.commit()

    payload = await _submit(client, _auth(researcher))

    assert set(payload) == {"export_id", "status", "message"}
    assert payload["status"] == "pending"
    assert payload["message"] == "Export job submitted"
    assert uuid.UUID(payload["export_id"])


async def test_submission_writes_the_owner_record_and_the_event(
    client, db_session
):
    release = await _published_release(db_session)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-record")
    await db_session.commit()

    payload = await _submit(client, _auth(researcher))

    record = (
        await db_session.execute(
            select(VariantExport).where(
                VariantExport.id == uuid.UUID(payload["export_id"])
            )
        )
    ).scalar_one()
    assert record.user_id == researcher.id
    assert record.status == VariantExportStatus.PENDING
    assert record.release_key == str(release.id)
    assert record.format == "tsv"
    assert record.compress is True
    # The stored filters are the resolved, public ones.
    assert record.filters["release_key"] == str(release.id)
    assert "mutant_line_id" not in record.filters
    assert "mutant_line_public_id" not in record.filters

    event = (
        await db_session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == payload["export_id"]
            )
        )
    ).scalar_one()
    assert event.event_type == "variant_export_requested"
    assert event.payload["kwargs"]["export_id"] == payload["export_id"]


async def test_an_export_of_an_unknown_namespace_is_refused(client, db_session):
    """A namespace the release does not publish must not yield an empty file.

    The artifact would otherwise be recorded as ``succeeded`` with zero rows:
    the export record would advertise a release/assembly pair that does not
    exist and the download would be an empty file that claims to be the
    release's data.
    """
    await _published_release(db_session)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-unknown")
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={
            "format": "tsv",
            "compress": True,
            "filters": {"assembly": "Wm82.a4.v2"},
        },
        headers=_auth(researcher),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    # Nothing was queued: a refused request leaves no record behind.
    assert (await db_session.execute(select(VariantExport))).scalars().all() == []


async def test_anonymous_submission_is_refused(client, db_session):
    await _published_release(db_session)
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={"format": "tsv", "compress": True, "filters": {}},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 2. Only the submitter and an administrator may read the export.
# ---------------------------------------------------------------------------


async def test_the_submitter_can_read_the_status(client, db_session):
    await _published_release(db_session)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-read")
    await db_session.commit()

    payload = await _submit(client, _auth(researcher))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(researcher)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["export_id"] == payload["export_id"]
    assert body["status"] == "pending"
    assert body["record_count"] is None
    # The storage key is not part of the status contract.
    assert "artifact_path" not in body


async def test_another_researcher_cannot_read_somebody_elses_export(
    client, db_session
):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    stranger = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-other")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(stranger)
    )

    # Reported as missing: the unguessable id must not disclose that an
    # export exists.
    assert response.status_code == 404, response.text


async def test_an_administrator_can_read_the_export(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    admin = await _make_user(db_session, RoleName.ADMINISTRATOR.value, "exp-admin")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(admin)
    )

    assert response.status_code == 200, response.text
    assert response.json()["export_id"] == payload["export_id"]


async def test_a_viewer_cannot_read_the_export(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    viewer = await _make_user(db_session, RoleName.VIEWER.value, "exp-viewer")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(viewer)
    )

    assert response.status_code == 403


async def test_an_unknown_export_is_not_found(client, db_session):
    await _published_release(db_session)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-read")
    await db_session.commit()

    response = await client.get(
        f"/api/v1/variants/export/{uuid.uuid4()}", headers=_auth(researcher)
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3. The download link is signed on demand, for the requester only.
# ---------------------------------------------------------------------------


async def _finish_export(db_session, export_id: str, *, expires_in_days: int = 7):
    record = (
        await db_session.execute(
            select(VariantExport).where(VariantExport.id == uuid.UUID(export_id))
        )
    ).scalar_one()
    record.status = VariantExportStatus.SUCCEEDED
    record.artifact_path = f"exports/{export_id}/soymutdb_export_{export_id}.tsv.gz"
    record.record_count = 12
    record.file_size = 2048
    record.completed_at = datetime.now(UTC)
    record.expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    await db_session.commit()
    return record


async def test_a_completed_export_gets_a_short_lived_signed_url(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-dl")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    record = await _finish_export(db_session, payload["export_id"])

    with patch(
        "app.services.variant_export_service.generate_presigned_url",
        return_value="https://minio.test/exports/export.tsv.gz?sig=x",
    ) as signer:
        response = await client.get(
            f"/api/v1/variants/export/{payload['export_id']}/download",
            headers=_auth(owner),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["download_url"].startswith("https://minio.test/")
    assert body["expires_in_seconds"] <= 3600
    signer.assert_called_once()
    signed_path = signer.call_args.args[0]
    assert signer.call_args.kwargs["expires_in"] == body["expires_in_seconds"]
    # The signed path is exactly the key the worker stored, under the
    # export bucket: the download must not drift from the artifact.
    filename = build_export_filename(str(record.id), record.format, record.compress)
    assert signed_path == (
        f"{get_settings().s3_export_bucket}/"
        f"{build_export_artifact_key(str(record.id), filename)}"
    )
    assert signed_path.endswith(f"exports/{record.id}/{filename}")


async def test_the_download_answer_is_not_cacheable(client, db_session):
    """An owner-scoped answer must not enter a shared cache."""
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-cache")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"


async def test_a_pending_export_has_no_download(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-pending")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/download",
        headers=_auth(owner),
    )

    assert response.status_code == 409, response.text


async def test_an_expired_export_has_no_download(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-expired")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    await _finish_export(db_session, payload["export_id"], expires_in_days=-1)

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/download",
        headers=_auth(owner),
    )

    assert response.status_code == 404, response.text


async def test_another_researcher_cannot_download_somebody_elses_export(
    client, db_session
):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    stranger = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-other")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    await _finish_export(db_session, payload["export_id"])

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/download",
        headers=_auth(stranger),
    )

    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 4. The manifest is the citable provenance of an owned artifact.
# ---------------------------------------------------------------------------


async def test_the_manifest_reports_recorded_provenance(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-manifest")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    record = await _finish_export(db_session, payload["export_id"])
    record.sha256 = "a" * 64
    record.license = "CC BY 4.0"
    record.generated_at = datetime.now(UTC)
    # The worker's join key is internal; a manifest must not echo it even
    # though it lives in the record's filter document.
    record.filters = {**record.filters, "mutant_line_name": "private-line"}
    await db_session.commit()

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/manifest",
        headers=_auth(owner),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == "a" * 64
    assert body["sha256_state"] == "recorded"
    assert body["release_key"] == record.release_key
    assert body["assembly_key"] == EXPORT_ASSEMBLY
    assert body["record_count"] == 12
    assert body["license"] == "CC BY 4.0"
    # Public request filters are echoed; the internal join key is not.
    assert body["filters"] == {
        "assembly": EXPORT_ASSEMBLY,
        "chromosome": "chr01",
    }
    assert "private-line" not in response.text
    # Provenance is owner-scoped, so it must not enter a shared cache.
    assert response.headers["cache-control"] == "private, no-store"


async def test_a_legacy_manifest_does_not_invent_a_digest(client, db_session):
    """An artifact produced before checksums shipped reports ``not_recorded``."""
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-legacy")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    await _finish_export(db_session, payload["export_id"])

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/manifest",
        headers=_auth(owner),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] is None
    assert body["sha256_state"] == "not_recorded"


async def test_another_researcher_cannot_read_the_manifest(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-owner")
    stranger = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-other")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    await _finish_export(db_session, payload["export_id"])

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}/manifest",
        headers=_auth(stranger),
    )

    assert response.status_code == 404, response.text


async def test_a_failed_export_reports_its_final_state(client, db_session):
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-failed")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    record = (
        await db_session.execute(
            select(VariantExport).where(
                VariantExport.id == uuid.UUID(payload["export_id"])
            )
        )
    ).scalar_one()
    record.status = VariantExportStatus.FAILED
    record.error_message = "ValueError: unsupported filter"
    await db_session.commit()

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_message"] == (
        "Export failed. Please submit a new export or contact support."
    )
    assert "unsupported filter" not in response.text


async def test_a_failed_export_hides_legacy_worker_diagnostics(client, db_session):
    """Even printable SQL/parameters in old rows must not reach the owner."""
    await _published_release(db_session)
    owner = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-failed")
    await db_session.commit()

    payload = await _submit(client, _auth(owner))
    record = (
        await db_session.execute(
            select(VariantExport).where(
                VariantExport.id == uuid.UUID(payload["export_id"])
            )
        )
    ).scalar_one()
    record.status = VariantExportStatus.FAILED
    # PostgreSQL rejects NUL bytes in text, but other control characters
    # are storable and must not reach a client verbatim.
    record.error_message = (
        "SELECT internal_id FROM mutants WHERE name='PRIVATE_LINE' "
        "parameters={'token': 'private-secret'} /private/storage/path\x07\x1b"
    )
    await db_session.commit()

    response = await client.get(
        f"/api/v1/variants/export/{payload['export_id']}", headers=_auth(owner)
    )

    assert response.status_code == 200, response.text
    message = response.json()["error_message"]
    assert "\x07" not in message
    assert "\x1b" not in message
    assert message == "Export failed. Please submit a new export or contact support."
    for private_value in ("SELECT", "internal_id", "PRIVATE_LINE", "private-secret", "/private/"):
        assert private_value not in response.text


# ---------------------------------------------------------------------------
# 4. The artifact is built from exactly one assembly namespace.
# ---------------------------------------------------------------------------
#
# An export is a *file*, not a search result set: its rows cannot be
# "clearly labelled per assembly" the way a listing can, and its VCF/BED
# provenance carries a single assembly. The worker only constrains its SQL
# by the assembly that the API put into the filters, so the record, the
# command and the artifact must state the same namespace. Before the fix a
# request that named no assembly reached the worker with no constraint at
# all: the artifact could hold v4 and v5 rows while the record advertised
# the release's single assembly.


async def _export_command_filters(db_session, export_id: str) -> dict:
    """The filters the API handed to the worker for this export."""
    event = (
        await db_session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == export_id)
        )
    ).scalar_one()
    return event.payload["kwargs"]["filters"]


async def _export_record(db_session, export_id: str) -> VariantExport:
    return (
        await db_session.execute(
            select(VariantExport).where(VariantExport.id == uuid.UUID(export_id))
        )
    ).scalar_one()


async def test_an_export_without_an_assembly_is_scoped_to_the_release_assembly(
    client, db_session
):
    """A request naming no assembly still exports exactly one namespace."""
    await _published_release(db_session, "exp-scope", assembly="Wm82.a4.v1")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-scope")
    await db_session.commit()

    payload = await _submit(
        client, _auth(researcher), filters={"chromosome": "chr01"}
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    # The worker adds "v.assembly_key = :assembly" only for this key; without
    # it the artifact would span every assembly of the release.
    assert command_filters["assembly"] == "Wm82.a4.v1"

    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == "Wm82.a4.v1"
    assert record.filters["assembly"] == "Wm82.a4.v1"
    # The record and the command must never disagree about the namespace.
    assert record.assembly_key == command_filters["assembly"]


async def test_a_blank_assembly_is_scoped_to_the_release_assembly(client, db_session):
    """An empty assembly is no assembly, not a filter for the empty string."""
    await _published_release(db_session, "exp-blank", assembly="Wm82.a4.v1")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-blank")
    await db_session.commit()

    payload = await _submit(
        client, _auth(researcher), filters={"assembly": "", "chromosome": "chr01"}
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    assert command_filters["assembly"] == "Wm82.a4.v1"
    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == "Wm82.a4.v1"


async def test_an_explicit_assembly_is_the_one_that_is_recorded(client, db_session):
    """A named assembly wins, and is stated identically everywhere."""
    release = await _published_release(db_session, "exp-explicit", assembly="Wm82.a4.v1")
    await _publish_facts(db_session, release, "Wm82.a5.v1")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-named")
    await db_session.commit()

    payload = await _submit(
        client,
        _auth(researcher),
        filters={"assembly": "Wm82.a5.v1", "chromosome": "chr01"},
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    assert command_filters["assembly"] == "Wm82.a5.v1"
    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == "Wm82.a5.v1"
    assert record.assembly_key == command_filters["assembly"]


async def test_an_export_requested_by_version_reaches_name_keyed_facts(
    client, db_session
):
    """The portal sends the assembly *name*; a version label means the same row.

    Facts may be imported under either label, so an export must resolve the
    requested label through the assemblies row instead of refusing a
    namespace that is present under its sibling label.
    """
    await _published_release(db_session, "exp-alias-name", assembly="Wm82.a4.v1")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-alias-name")
    await db_session.commit()

    payload = await _submit(
        client,
        _auth(researcher),
        filters={"assembly": "v4", "chromosome": "chr01"},
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    assert command_filters["assembly"] == "Wm82.a4.v1"
    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == "Wm82.a4.v1"


async def test_an_export_requested_by_name_reaches_version_keyed_facts(
    client, db_session
):
    """The reverse label direction resolves to the namespace the rows use."""
    release = await _published_release(
        db_session, "exp-alias-version", assembly="Wm82.a4.v1"
    )
    # Re-key the published fact to the version label: the assemblies row is
    # now the only explicit link between the name the caller sends and the
    # key the rows carry.
    await db_session.execute(
        variant_facts.update()
        .where(variant_facts.c.release_id == release.id)
        .values(assembly_key="v4")
    )
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-alias-ver")
    await db_session.commit()

    payload = await _submit(
        client,
        _auth(researcher),
        filters={"assembly": "Wm82.a4.v1", "chromosome": "chr01"},
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    assert command_filters["assembly"] == "v4"
    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == "v4"


async def test_an_ambiguous_assembly_alias_is_refused(client, db_session):
    """Two assemblies sharing a version label: refuse rather than guess.

    The caller asked for a label that maps to two published namespaces, and
    one artifact may not span them.
    """
    release = await _published_release(db_session, "exp-ambig", assembly="Wm82.a4.v1")
    await _publish_facts(db_session, release, "Wm82.a5.v1")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-ambig")
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={
            "format": "tsv",
            "compress": True,
            "filters": {"assembly": "v4", "chromosome": "chr01"},
        },
        headers=_auth(researcher),
    )

    assert response.status_code == 422, response.text
    assert (await db_session.execute(select(VariantExport))).scalars().all() == []


async def test_an_export_is_refused_when_no_assembly_can_be_resolved(client, db_session):
    """No client assembly and no release scope: refuse, never guess.

    The alternative is an artifact that spans assembly namespaces while the
    record advertises a single one, which the database contract forbids.
    """
    await _published_release(db_session, "exp-noscope")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-noscope")
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={"format": "tsv", "compress": True, "filters": {"chromosome": "chr01"}},
        headers=_auth(researcher),
    )

    assert response.status_code == 422, response.text
    # Nothing was accepted: no record and no command.
    assert (await db_session.execute(select(VariantExport))).scalars().all() == []
    assert (await db_session.execute(select(OutboxEvent))).scalars().all() == []


# ---------------------------------------------------------------------------
# 5. The resolved assembly has to fit the export record.
# ---------------------------------------------------------------------------
#
# ``variant_exports.assembly_key`` is a ``String(64)`` column while the
# release's own assembly scope is free text. A name that does not fit would
# fail the INSERT and surface as a 500, so the API refuses it with a clean
# 422 instead — and it refuses it rather than truncating it or mapping it
# onto another name, which would export the wrong namespace.


async def test_an_assembly_that_fits_is_recorded(client, db_session):
    """A name of exactly the column width is accepted and stored as given."""
    release = await _published_release(db_session, "exp-fit")
    name = "A" * 64
    await _publish_facts(db_session, release, name)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-fit")
    await db_session.commit()
    payload = await _submit(
        client, _auth(researcher), filters={"assembly": name, "chromosome": "chr01"}
    )

    command_filters = await _export_command_filters(db_session, payload["export_id"])
    assert command_filters["assembly"] == name
    record = await _export_record(db_session, payload["export_id"])
    assert record.assembly_key == name


async def test_an_over_long_assembly_is_refused(client, db_session):
    """An explicit name that does not fit: 422, and nothing is queued."""
    await _published_release(db_session, "exp-long")
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-long")
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={
            "format": "tsv",
            "compress": True,
            "filters": {"assembly": "A" * 65, "chromosome": "chr01"},
        },
        headers=_auth(researcher),
    )

    assert response.status_code == 422, response.text
    # The domain refusal uses the shared error envelope.
    assert response.json()["error"]["code"] == "validation_error"
    assert (await db_session.execute(select(VariantExport))).scalars().all() == []
    assert (await db_session.execute(select(OutboxEvent))).scalars().all() == []


async def test_an_over_long_release_assembly_scope_is_refused(client, db_session):
    """The default scope is held to the same limit as a named one."""
    await _published_release(db_session, "exp-longscope", assembly="B" * 65)
    researcher = await _make_user(db_session, RoleName.RESEARCHER.value, "exp-longscope")
    await db_session.commit()

    response = await client.post(
        "/api/v1/variants/export",
        json={"format": "tsv", "compress": True, "filters": {"chromosome": "chr01"}},
        headers=_auth(researcher),
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert (await db_session.execute(select(VariantExport))).scalars().all() == []
    assert (await db_session.execute(select(OutboxEvent))).scalars().all() == []

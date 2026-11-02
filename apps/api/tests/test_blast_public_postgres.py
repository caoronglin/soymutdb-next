"""PostgreSQL proof of the anonymous BLAST ownership and transactional boundary."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.api.v1 import blast as routes
from app.core.blast_capability import PUBLIC_JOB_MARKER, issue_blast_capability
from app.core.config import get_settings
from app.models.auth import User
from app.models.blast import BlastDatabase, BlastJob
from app.models.content import Release
from app.models.genomic import Assembly
from app.models.outbox import OutboxEvent


async def test_public_blast_postgres_release_ownership_and_atomic_outbox(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(routes, "public_blast_rate_limiter", AsyncMock())
    monkeypatch.setattr(get_settings(), "blast_public_enabled", True)
    releases = [
        Release(version="blast-published", name="published", status="published"),
        Release(version="blast-draft", name="draft", status="draft"),
    ]
    db_session.add_all(releases)
    await db_session.flush()
    assemblies = [
        Assembly(name=f"blast-{release.status}", version="v1", release_id=release.id)
        for release in releases
    ]
    db_session.add_all(assemblies)
    await db_session.flush()
    databases = [
        BlastDatabase(
            name=f"blast_{release.status}",
            assembly_id=assembly.id,
            db_type="prot",
            file_path="/private/index/protein",
            is_active=True,
        )
        for release, assembly in zip(releases, assemblies, strict=True)
    ]
    account = User(username="blast-owner", email="blast-owner@example.org", password_hash="unused")
    db_session.add_all([*databases, account])
    await db_session.commit()
    base = "/api/v1/blast/public/jobs"
    release_headers = {"X-SoyMutDB-Release": str(releases[0].id)}
    query = ">protein\nMKVLAAGIVGLNLGGK"
    submitted = await client.post(
        base,
        headers=release_headers,
        json={
            "database_id": databases[0].id,
            "query_sequence": query,
        },
    )
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    job_id = uuid.UUID(body["job"]["job_id"])
    job = (await db_session.execute(select(BlastJob).where(BlastJob.id == job_id))).scalar_one()
    assert job.user_id is None
    assert job.parameters[PUBLIC_JOB_MARKER] is True
    event = (
        await db_session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == str(job_id)))
    ).scalar_one()
    assert event.event_type == "blast_job.run"
    assert event.payload["payload"]["release_key"] == str(releases[0].id)
    assert event.payload["payload"]["assembly_id"] == assemblies[0].id
    assert PUBLIC_JOB_MARKER not in event.payload["payload"]["parameters"]
    token_header = {"X-Blast-Token": body["access_token"]}
    for suffix in ("", "/results"):
        response = await client.get(f"{base}/{job_id}{suffix}", headers=token_header)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "X-Blast-Token"
        assert "/private/" not in response.text
    # A valid capability is neither account auth nor authority over a different job.
    private = await client.get(
        f"/api/v1/blast/jobs/{job_id}", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert private.status_code == 401
    other_token, _ = issue_blast_capability(uuid.uuid4())
    assert (
        await client.get(f"{base}/{job_id}", headers={"X-Blast-Token": other_token})
    ).status_code == 401
    # Account-owned jobs and later account-orphans both remain inaccessible.
    job.user_id = account.id
    job.parameters = {}
    await db_session.commit()
    assert (await client.get(f"{base}/{job_id}", headers=token_header)).status_code == 403
    job.user_id = None
    await db_session.commit()
    assert (await client.get(f"{base}/{job_id}", headers=token_header)).status_code == 403
    # A draft DB is unreachable through a published release or an explicit draft pin.
    for release_id in (releases[0].id, releases[1].id):
        refused = await client.post(
            base,
            headers={"X-SoyMutDB-Release": str(release_id)},
            json={
                "database_id": databases[1].id,
                "query_sequence": query,
            },
        )
        assert refused.status_code == 404, refused.text
        assert "/private/" not in refused.text
    assert await db_session.scalar(select(func.count()).select_from(BlastJob)) == 1
    assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 1

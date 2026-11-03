"""HTTP boundary: index builds are enqueued, never executed in the request."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.database import get_db
from app.core.security import RoleName, create_access_token
from app.models.auth import Role, User
from app.models.blast import BlastDatabase, BlastIndexBuild
from app.models.content import Release
from app.models.data_publishing import ActiveRelease
from app.models.genomic import Assembly
from app.models.outbox import OutboxEvent


async def _admin(db_session, app):
    role = (await db_session.execute(
        select(Role).where(Role.name == RoleName.ADMINISTRATOR.value)
    )).scalar_one()
    user = User(
        id=uuid.uuid4(), username="admin", email="admin@soymutdb.local",
        password_hash="x", is_active=True, is_deleted=False, role_id=role.id,
    )
    user.role_rel = role
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    async def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    return {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}


async def test_admin_build_request_records_pending_rows_and_outbox_event(
    db_session, client, app, monkeypatch,
):
    headers = await _admin(db_session, app)
    release = Release(version="build-http", name="build-http", status="published")
    db_session.add(release)
    await db_session.flush()
    assembly = Assembly(name="Wm82.a4.v1", version="v4", release_id=release.id,
                        is_default=True)
    db_session.add(assembly)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.commit()

    payload = {
        "source_object_key": "blast-sources/synthetic.fa",
        "db_type": "nucl", "assembly_name": "Wm82.a4.v1",
        "annotation_version": "a4.v1", "source_version": "s1",
        "source_url": "https://www.ncbi.nlm.nih.gov/", "license": "CC0-1.0",
        "name": "wm82_a4_genome", "sequence_type": "genome",
    }
    response = await client.post(
        "/api/v1/blast/index-builds", json=payload, headers=headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "pending"
    assert body["name"] == "wm82_a4_genome"
    assert "file_path" not in body and "source_object_key" not in body
    assert "/private" not in response.text and "makeblastdb" not in response.text

    catalog = (await db_session.execute(
        select(BlastDatabase).where(BlastDatabase.name == "wm82_a4_genome")
    )).scalar_one()
    assert catalog.build_status == "pending"
    assert catalog.is_active is False and catalog.engine == "ncbi_blast"
    assert catalog.file_path == ""

    build = (await db_session.execute(select(BlastIndexBuild))).scalar_one()
    assert build.state == "pending"
    # Identity is frozen from the DB, never accepted from the client.
    assert build.build_metadata["assembly_id"] == str(assembly.id)
    assert build.build_metadata["assembly_version"] == "v4"
    assert build.build_metadata["release_id"] == str(release.id)

    events = (await db_session.execute(select(OutboxEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].payload["task_name"] == (
        "soymutdb_worker.tasks.blast_index.build_index"
    )
    assert events[0].payload["kwargs"] == {"build_id": str(build.id)}
    assert "source_object_key" not in events[0].payload["kwargs"]
    assert "index_root" not in events[0].payload["kwargs"]


async def test_non_admin_cannot_request_a_build(db_session, client, app):
    role = (await db_session.execute(
        select(Role).where(Role.name == RoleName.RESEARCHER.value)
    )).scalar_one()
    researcher = User(
        id=uuid.uuid4(), username="researcher", email="r@soymutdb.local",
        password_hash="x", is_active=True, is_deleted=False, role_id=role.id,
    )
    researcher.role_rel = role
    db_session.add(researcher)
    await db_session.flush()
    await db_session.commit()

    async def override():
        yield db_session

    app.dependency_overrides[get_db] = override
    headers = {
        "Authorization": f"Bearer {create_access_token(subject=str(researcher.id))}"
    }
    response = await client.post(
        "/api/v1/blast/index-builds",
        json={
            "source_object_key": "blast-sources/a.fa", "db_type": "nucl",
            "assembly_name": "Wm82", "annotation_version": "a", "source_version": "s",
            "source_url": "https://www.ncbi.nlm.nih.gov/", "license": "CC0-1.0",
            "name": "x",
        },
        headers=headers,
    )
    assert response.status_code in (401, 403)
    assert await db_session.scalar(
        select(func.count()).select_from(BlastIndexBuild)
    ) == 0

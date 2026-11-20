"""Real PostgreSQL catalog constraints, discovery and pre-dispatch refusal."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError
from app.models.blast import BlastDatabase, BlastJob
from app.models.content import Release
from app.models.genomic import Assembly
from app.models.outbox import OutboxEvent
from app.schemas.blast import BlastSubmitRequest
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


async def seed(db):
    release = Release(version="catalog-published", name="catalog", status="published")
    draft = Release(version="catalog-draft", name="draft", status="draft")
    db.add_all([release, draft])
    await db.flush()
    assembly = Assembly(name="catalog-Wm82", version="v4", release_id=release.id, is_default=True)
    draft_assembly = Assembly(name="catalog-draft", version="v5", release_id=draft.id)
    db.add_all([assembly, draft_assembly])
    await db.flush()
    return release, assembly, draft, draft_assembly


def row(name, assembly_id, **fields):
    return BlastDatabase(
        name=name, assembly_id=assembly_id, db_type=fields.pop("db_type", "prot"),
        file_path=f"/private/index/{name}",
        build_status=fields.pop("build_status", "ready"), **fields,
    )


async def test_postgres_catalog_restricts_all_selectors_before_job_and_outbox(
    db_session, client, monkeypatch,
):
    from app.api.v1 import blast as routes
    from app.services import blast_service

    monkeypatch.setattr(routes, "public_blast_rate_limiter", AsyncMock())
    release, assembly, draft, draft_assembly = await seed(db_session)
    ready = row("catalog_ready", assembly.id, is_default=True,
                provenance={"secret": "/private/provenance"}, source_url="file:///private/source.fa")
    unavailable = [
        row("catalog_ncbi", assembly.id, engine="ncbi_blast", is_default=True),
        row("catalog_building", assembly.id, build_status="building"),
        row("catalog_failed", assembly.id, build_status="failed"),
        row("catalog_nucl", assembly.id, db_type="nucl"),
        row("catalog_inactive", assembly.id, is_active=False),
        row("catalog_draft", draft_assembly.id),
    ]
    db_session.add_all([ready, *unavailable])
    await db_session.commit()
    service = BlastService()
    context = ReleaseContext(release_id=release.id, assembly_id=assembly.id, assembly=assembly.name)
    discovered = await service.list_databases(db_session, release_context=context)
    assert [entry.id for entry in discovered] == [ready.id, unavailable[0].id]
    public = await client.get("/api/v1/blast/databases", headers={
        "X-SoyMutDB-Release": str(release.id),
    })
    assert public.status_code == 200, public.text
    assert [entry["id"] for entry in public.json()] == [ready.id, unavailable[0].id]
    assert "/private/" not in public.text
    assert "provenance" not in public.text
    assert "catalog_draft" not in public.text
    assert public.json()[0]["source_url"] is None

    for unavailable_row in unavailable:
        for selector in (
            {"database_id": unavailable_row.id}, {"database": unavailable_row.name},
            {"database_id": unavailable_row.id, "database": unavailable_row.name},
        ):
            request = BlastSubmitRequest(
                engine="diamond", query_sequence="MKVLAAGIVGLNLGGK", **selector
            )
            with pytest.raises(NotFoundError):
                await service.submit_job(db_session, None, request, release_context=context)
        # An incompatible configured default may fall back to the release's
        # runnable default but must never select the incompatible row itself.
        monkeypatch.setattr(blast_service.settings, "blast_default_db", unavailable_row.name)
        resolved = await service._resolve_database(
            db_session, BlastSubmitRequest(engine="diamond", query_sequence="MKVLAAGIVGLNLGGK"),
            release_context=context,
        )
        assert resolved.id == ready.id
    assert await db_session.scalar(select(func.count()).select_from(BlastJob)) == 0
    assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    # Explicit draft release pins cannot bypass the published-only API context.
    draft_request = await client.post(
        "/api/v1/blast/public/jobs", headers={"X-SoyMutDB-Release": str(draft.id)},
        json={"database_id": unavailable[-1].id, "query_sequence": "MKVLAAGIVGLNLGGK"},
    )
    assert draft_request.status_code == 404
    response = await service.submit_job(
        db_session, None,
        BlastSubmitRequest(
            engine="diamond", database_id=ready.id, query_sequence="MKVLAAGIVGLNLGGK"
        ),
        release_context=context,
    )
    assert response.database_id == ready.id
    event = (await db_session.execute(select(OutboxEvent))).scalar_one()
    assert event.payload["payload"]["database"] == ready.name
    assert event.payload["payload"]["assembly_id"] == assembly.id


@pytest.mark.parametrize("field,value", [
    ("engine", "unknown"), ("build_status", "queued"), ("sequence_type", "guessed_subtype"),
    ("sequence_count", -1), ("total_length", -1), ("fasta_sha256", "not-sha256"),
    ("fasta_sha256", "A" * 64),
])
async def test_postgres_catalog_constraints(db_session, field, value):
    _, assembly, _, _ = await seed(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(row("catalog_invalid", assembly.id, **{field: value}))
            await db_session.flush()


async def test_postgres_active_default_unique_per_assembly_engine_type(db_session):
    _, assembly, _, other_assembly = await seed(db_session)
    default = row("catalog_default", assembly.id, is_default=True)
    db_session.add(default)
    await db_session.flush()
    # Different engine/type/assembly or inactive/non-default rows are allowed.
    allowed = [
        row("catalog_ncbi_default", assembly.id, engine="ncbi_blast", is_default=True),
        row("catalog_nucl_default", assembly.id, db_type="nucl", is_default=True),
        row("catalog_other_default", other_assembly.id, is_default=True),
        row("catalog_inactive_default", assembly.id, is_active=False, is_default=True),
        row("catalog_secondary", assembly.id),
    ]
    db_session.add_all(allowed)
    await db_session.flush()
    assert default.engine == "diamond" and default.build_status == "ready"
    assert default.annotation_version is None and default.license is None
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(row("catalog_conflicting_default", assembly.id, is_default=True))
            await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text(
                "UPDATE blast_databases SET is_active=true WHERE name='catalog_inactive_default'"
            ))

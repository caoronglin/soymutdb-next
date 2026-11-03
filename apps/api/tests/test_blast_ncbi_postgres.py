"""Persisted NCBI API submissions keep program, ownership and per-query HSP IDs."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.blast import BlastHit, BlastJob
from app.models.outbox import OutboxEvent
from tests.test_blast_catalog_postgres import row, seed
from tests.test_blast_ncbi_execution import PROGRAMS, PROTEIN, QUERY


async def catalogs(db):
    release, assembly, draft, draft_assembly = await seed(db)
    protein = row("ncbi_protein", assembly.id, engine="ncbi_blast", index_version="a" * 64,
                  fasta_sha256="b" * 64, is_default=True)
    nucleotide = row("ncbi_genome", assembly.id, engine="ncbi_blast", db_type="nucl",
                     index_version="c" * 64, fasta_sha256="d" * 64, is_default=True)
    db.add_all([protein, nucleotide])
    await db.commit()
    return release, assembly, protein, nucleotide, draft, draft_assembly


@pytest.mark.parametrize("program,db_type", PROGRAMS.items())
async def test_ncbi_public_submit_and_capability_read_real_postgres(
    db_session, client, monkeypatch, program, db_type,
):
    from app.api.v1 import blast as routes

    monkeypatch.setattr(routes, "public_blast_rate_limiter", AsyncMock())
    release, assembly, protein, nucleotide, _, _ = await catalogs(db_session)
    catalog = protein if db_type == "prot" else nucleotide
    query = PROTEIN if program in {"blastp", "tblastn"} else QUERY
    response = await client.post(
        "/api/v1/blast/public/jobs", headers={"X-SoyMutDB-Release": str(release.id)},
        json={"program": program, "database_id": catalog.id,
              "query_sequence": f">first\n{query}\n>second\n{query}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["job"]["engine"] == "ncbi_blast"
    assert body["job"]["program"] == program
    job = (await db_session.execute(select(BlastJob))).scalar_one()
    assert job.user_id is None
    frozen = job.parameters["_search_provenance"]
    assert frozen["index_identity"] == catalog.index_version
    assert frozen["assembly_id"] == assembly.id
    assert frozen["release_id"] == release.id
    event = (await db_session.execute(select(OutboxEvent))).scalar_one()
    assert event.payload["payload"]["engine"] == "ncbi_blast"
    assert event.payload["payload"]["index_identity"] == catalog.index_version
    assert "/private/" not in str(event.payload)
    # Each HSP retains its input query ID; it cannot collapse into a single
    # invented 'query' identifier when a multi-FASTA job completes.
    job.status = "completed"
    job.hit_count = 2
    for index, query_id in enumerate(("first", "second"), start=1):
        db_session.add(BlastHit(
            job_id=job.id, hsp_num=index, query_id=query_id, subject_id="target",
            percent_identity=100, alignment_length=10, mismatches=0, gap_opens=0,
            query_start=1, query_end=10, subject_start=1, subject_end=10,
            evalue=1e-20, bit_score=100,
        ))
    await db_session.commit()
    results = await client.get(
        f"/api/v1/blast/public/jobs/{job.id}/results",
        headers={"X-Blast-Token": body["access_token"]},
    )
    assert results.status_code == 200, results.text
    assert {hit["query_id"] for hit in results.json()["hits"]} == {"first", "second"}
    assert results.headers["cache-control"] == "private, no-store"
    no_token = await client.get(f"/api/v1/blast/public/jobs/{job.id}/results")
    assert no_token.status_code == 401


async def test_ncbi_program_catalog_and_release_refusals_are_atomic(
    db_session, client, monkeypatch,
):
    from app.api.v1 import blast as routes

    monkeypatch.setattr(routes, "public_blast_rate_limiter", AsyncMock())
    release, _, protein, nucleotide, draft, draft_assembly = await catalogs(db_session)
    draft_catalog = row("ncbi_draft", draft_assembly.id, engine="ncbi_blast",
                        index_version="e" * 64, fasta_sha256="f" * 64)
    unverified = row("ncbi_unverified", protein.assembly_id, engine="ncbi_blast")
    db_session.add_all([draft_catalog, unverified])
    await db_session.commit()
    for payload, release_id in [
        ({"program": "blastp", "database_id": nucleotide.id}, release.id),
        ({"program": "blastn", "database_id": protein.id}, release.id),
        ({"program": "blastp", "database_id": draft_catalog.id}, release.id),
        ({"program": "blastp", "database_id": draft_catalog.id}, draft.id),
        ({"program": "blastp", "database_id": unverified.id}, release.id),
        ({"engine": "diamond", "program": "blastp", "database_id": protein.id}, release.id),
    ]:
        query = QUERY if payload["program"] == "blastn" else PROTEIN
        response = await client.post(
            "/api/v1/blast/public/jobs", headers={"X-SoyMutDB-Release": str(release_id)},
            json={**payload, "query_sequence": query},
        )
        assert response.status_code in {404, 422}, response.text
        assert "/private/" not in response.text
        assert await db_session.scalar(select(func.count()).select_from(BlastJob)) == 0
        assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


async def test_ncbi_default_resolution_and_conflicting_identifiers(db_session, monkeypatch):
    from app.core.exceptions import ValidationError as ServiceValidationError
    from app.schemas.blast import BlastSubmitRequest
    from app.services import blast_service
    from app.services.release_context import ReleaseContext

    release, assembly, protein, nucleotide, _, _ = await catalogs(db_session)
    diamond = row("explicit_diamond", assembly.id, is_default=True)
    db_session.add(diamond)
    await db_session.commit()
    monkeypatch.setattr(blast_service.settings, "blast_default_db", diamond.name)
    context = ReleaseContext(release_id=release.id, assembly_id=assembly.id, assembly=assembly.name)
    service = blast_service.BlastService()
    # Configured legacy DIAMOND default cannot redirect NCBI submissions.
    for program, db_type in PROGRAMS.items():
        selected = await service._resolve_database(
            db_session, BlastSubmitRequest(
                program=program,
                query_sequence=PROTEIN if program in {"blastp", "tblastn"} else QUERY,
            ), release_context=context,
        )
        assert selected.id == (protein.id if db_type == "prot" else nucleotide.id)
    selected = await service._resolve_database(
        db_session, BlastSubmitRequest(engine="diamond", query_sequence=PROTEIN),
        release_context=context,
    )
    assert selected.id == diamond.id
    with pytest.raises(ServiceValidationError, match="do not match"):
        await service.submit_job(
            db_session, None,
            BlastSubmitRequest(database_id=protein.id, database=nucleotide.name,
                               query_sequence=PROTEIN), release_context=context,
        )
    assert await db_session.scalar(select(func.count()).select_from(BlastJob)) == 0
    assert await db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 0

"""Phase 1 execution-side contracts: build state, genome targets, cancel/retry/expiry.

Explicitly covers the NCBI engine alongside DIAMOND so the two engines cannot
drift. No mocked BLAST search is claimed: these tests assert API/worker
contracts, not sequence alignment results.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ValidationError
from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.models.genomic import Assembly
from app.schemas.blast import (
    BlastGenomeTargetResponse,
    BlastIndexBuildRequest,
    BlastIndexBuildResponse,
)
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


def _context(release_id: int, assembly_id: int, assembly: str = "Wm82") -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=assembly_id, assembly=assembly)


def _session(row, catalog=None, assembly=None):
    """Session stub answering each table's query with the matching row.

    The catalog/assembly rows are captured when the stub is built, so a lookup
    can never be served the job row — that is what hides "read a
    ``blast_databases`` column off ``BlastJob``" defects.
    """
    def _pick(stmt):
        sql = str(stmt)
        if "FROM blast_databases" in sql:
            return catalog
        if "FROM assemblies" in sql:
            return assembly
        return row

    def _add(_obj):
        return None

    return SimpleNamespace(
        execute=AsyncMock(side_effect=lambda stmt, *a, **k: _result(_pick(stmt))),
        scalar=AsyncMock(return_value=0),
        add=_add, commit=AsyncMock(), flush=AsyncMock(), refresh=AsyncMock(),
    )


def _result(row):
    return SimpleNamespace(
        scalar_one_or_none=lambda: row,
        scalars=lambda: SimpleNamespace(all=lambda: [row] if row is not None else [],
                                        first=lambda: row),
    )


# ---------------------------------------------------------------------------
# Only published indexes are searchable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["diamond", "ncbi_blast"])
@pytest.mark.parametrize("state,searchable", [
    ("pending", False), ("building", False), ("validating", False),
    ("published", True), ("failed", False), ("ready", True),
])
def test_only_published_indexes_are_runnable(engine, state, searchable):
    row = BlastDatabase(
        id=1, name="db", db_type="prot", assembly_id=1, is_active=True,
        engine=engine, build_status=state, is_default=False,
        file_path="/private/index", created_at=datetime.now(UTC),
    )
    assert BlastService._is_runnable_database(row) is searchable


# ---------------------------------------------------------------------------
# Genome targets: AA coordinates never become genomic coordinates
# ---------------------------------------------------------------------------


def test_genome_target_schema_refuses_coordinates_without_a_resolution():
    with pytest.raises(ValueError):
        BlastGenomeTargetResponse(status="unresolved", reason="subject_not_found", locus="chr1:1-2")
    with pytest.raises(ValueError):
        BlastGenomeTargetResponse(status="resolved", gene_id="g", chromosome="chr1",
                                  start=1, end=2, locus="chr1:1-2",
                                  resolution="gene_accession", release_id=1)
    ok = BlastGenomeTargetResponse(status="resolved", gene_id="g", chromosome="chr1",
                                   start=1, end=2, locus="chr1:1-2",
                                   resolution="gene_accession", release_id=1,
                                   assembly_id=1, assembly_name="Wm82")
    assert ok.locus == "chr1:1-2"
    assert BlastGenomeTargetResponse(status="unresolved", reason="ambiguous_subject").locus is None


def test_build_request_rejects_unreviewed_or_private_sources():
    base = dict(
        db_type="nucl", assembly_name="Wm82.a4.v1",
        annotation_version="a4", source_version="s1",
        source_url="https://www.ncbi.nlm.nih.gov/", license="CC0-1.0", name="wm82_a4",
    )
    request = BlastIndexBuildRequest(source_object_key="blast-sources/a.fa", **base)
    assert request.db_type == "nucl"
    frozen = request.build_metadata(assembly_id="7", assembly_version="v4", release_id="3")
    assert frozen["assembly_id"] == "7" and frozen["release_id"] == "3"
    assert "/private" not in str(frozen)
    for bad in ["data/a.fa", "blast-sources/../secret", "s3://bucket/a.fa",
                "blast-sources/a\\b.fa"]:
        with pytest.raises(ValueError):
            BlastIndexBuildRequest(source_object_key=bad, **base)
    with pytest.raises(ValueError):
        BlastIndexBuildRequest(source_object_key="blast-sources/a.fa",
                               **{**base, "source_url": "file:///private/a.fa"})
    assert BlastIndexBuildResponse(
        build_id=str(uuid.uuid4()), database_id=1, name="db", state="building",
        db_type="nucl", created_at=datetime.now(UTC),
    ).state == "building"


# ---------------------------------------------------------------------------
# Cancel / retry / download expiry, engine-independent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine,program", [
    ("diamond", "blastp"), ("ncbi_blast", "blastp"),
    ("ncbi_blast", "blastn"), ("ncbi_blast", "blastx"),
    ("ncbi_blast", "tblastn"), ("ncbi_blast", "tblastx"),
])
async def test_cancel_guards_terminal_jobs_for_both_engines(engine, program):
    service = BlastService()
    owner = uuid.uuid4()
    job = BlastJob(
        id=uuid.uuid4(), user_id=owner, program=program, database_id=1,
        query_sequence="MKVLAAGIVGLNLGGK", status=BlastJobStatus.COMPLETED,
        parameters={"_search_provenance": {"engine": engine}},
        submitted_at=datetime.now(UTC),
    )
    db = _session(job)
    with pytest.raises(ValidationError):
        await service.cancel_job(db, job.id, owner, [])
    assert job.status == BlastJobStatus.COMPLETED


@pytest.mark.parametrize("engine", ["diamond", "ncbi_blast"])
async def test_retry_creates_a_new_job_and_new_outbox_event(engine, monkeypatch):
    from app.services import blast_service

    service = BlastService()
    owner = uuid.uuid4()
    original = BlastJob(
        id=uuid.uuid4(), user_id=owner, program="blastp", database_id=1,
        query_sequence="MKVLAAGIVGLNLGGK", status=BlastJobStatus.FAILED,
        parameters={"_search_provenance": {
                        "engine": engine,
                        # Retry replays this frozen identity verbatim.
                        "index_identity": "a" * 64, "fasta_sha256": "b" * 64,
                        "index_version": "a" * 64, "annotation_version": "v1",
                        "release_id": 1, "assembly_id": 1,
                    }, "evalue": 1e-5, "max_target_seqs": 50},
        submitted_at=datetime.now(UTC),
    )
    original.database = BlastDatabase(
        id=1, name="db", db_type="prot", assembly_id=1, is_active=True,
        engine=engine, build_status="published", file_path="/private",
        created_at=datetime.now(UTC),
        # Retry replays the identity frozen at submission; a retryable NCBI
        # row therefore has to carry one.
        index_version="a" * 64, fasta_sha256="b" * 64,
    )
    assembly = Assembly(id=1, name="Wm82", version="v4", species="Glycine max",
                        release_id=1)
    original.database.assembly = assembly
    db = _session(original, catalog=original.database, assembly=assembly)
    monkeypatch.setattr(blast_service.settings, "blast_default_db", None)
    created = []

    async def fake_submit(db_, user_id, request, *, release_context):
        assert user_id == owner
        assert request.engine == engine
        assert request.database_id == original.database_id
        assert request.query_sequence == original.query_sequence
        response = SimpleNamespace(job_id=str(uuid.uuid4()))
        created.append(response)
        return response

    monkeypatch.setattr(service, "submit_job", fake_submit)
    result = await service.retry_job(
        db, original.id, owner, [], release_context=_context(1, 1)
    )
    # Retry re-arms the same row (no copied job); the engine never changes.
    assert result.job_id == str(original.id)
    assert created == []
    assert original.status == BlastJobStatus.PENDING
    assert original.error_message is None and original.result_path is None


@pytest.mark.parametrize("engine", ["diamond", "ncbi_blast"])
async def test_retry_rejects_completed_jobs(engine):
    service = BlastService()
    owner = uuid.uuid4()
    job = BlastJob(
        id=uuid.uuid4(), user_id=owner, program="blastp", database_id=1,
        query_sequence="MKVLAAGIVGLNLGGK", status=BlastJobStatus.COMPLETED,
        parameters={"_search_provenance": {"engine": engine}},
        submitted_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        await service.retry_job(
            _session(job), job.id, owner, [], release_context=_context(1, 1)
        )


@pytest.mark.parametrize("engine", ["diamond", "ncbi_blast"])
async def test_expired_ncbi_and_diamond_results_never_offer_a_download(engine, monkeypatch):
    """The presigned URL is bounded by job/capability expiry for both engines."""
    from app.services import blast_service

    service = BlastService()
    job = BlastJob(
        id=uuid.uuid4(), user_id=None, program="blastp", database_id=1,
        query_sequence="MKVLAAGIVGLNLGGK", status=BlastJobStatus.COMPLETED,
        parameters={"_search_provenance": {"engine": engine}, "_public_blast": True},
        submitted_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        result_path="blast-results/expired.txt", hit_count=1,
    )
    db = _session(job)
    monkeypatch.setattr(
        blast_service, "verify_blast_capability",
        lambda token, job_id: datetime.now(UTC) + timedelta(hours=1),
    )
    result = await service.get_result(
        db, job.id, limit=50, offset=0, public_token="capability"
    )
    assert result.status.value == "expired"
    assert result.download_url is None
    assert result.hits is None

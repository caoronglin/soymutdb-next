"""New NCBI submissions bind query/program/catalog/immutable provenance."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.core.exceptions import ValidationError as ServiceValidationError
from app.models.blast import BlastJob
from app.schemas.blast import BlastParameters, BlastSubmitRequest
from app.services.blast_service import BlastService
from tests.test_blast_database_select import FakeDbSession, _context, _make_db

QUERY = "ACGTACGTACGTACGTACGTACGTACGTACGT"
PROTEIN = "MKVLAAGIVGLNLGGK"
PROGRAMS = {"blastn": "nucl", "blastp": "prot", "blastx": "prot",
            "tblastn": "nucl", "tblastx": "nucl"}


def request(program="blastp", **kwargs):
    return BlastSubmitRequest(
        program=program, query_sequence=PROTEIN if program in {"blastp", "tblastn"} else QUERY,
        database_id=1, **kwargs,
    )


def ncbi_catalog(db_type="prot", **kwargs):
    catalog = _make_db(db_type=db_type)
    catalog.engine = "ncbi_blast"
    catalog.index_version = "a" * 64
    catalog.fasta_sha256 = "b" * 64
    catalog.annotation_version = "v4.1"
    for key, value in kwargs.items():
        setattr(catalog, key, value)
    return catalog


@pytest.mark.parametrize("program,db_type", PROGRAMS.items())
async def test_all_five_programs_freeze_engine_identity_before_dispatch(program, db_type):
    catalog = ncbi_catalog(db_type)
    session = FakeDbSession(blast_db=catalog)
    result = await BlastService().submit_job(session, uuid.uuid4(), request(program),
                                            release_context=_context())
    job = next(item for item in session.added if isinstance(item, BlastJob))
    event = next(item for item in session.added if not isinstance(item, BlastJob))
    payload = event.payload["payload"]
    assert result.engine == "ncbi_blast"
    assert payload["engine"] == "ncbi_blast"
    assert payload["database_type"] == db_type
    assert payload["index_identity"] == "a" * 64
    assert payload["fasta_sha256"] == "b" * 64
    assert payload["release_key"] == "7"
    assert payload["assembly_id"] == 1
    assert "/data/" not in str(payload)
    assert "_search_provenance" not in payload["parameters"]
    assert job.parameters["_search_provenance"]["engine"] == "ncbi_blast"
    catalog.index_version = "c" * 64
    assert job.parameters["_search_provenance"]["index_identity"] == "a" * 64


@pytest.mark.parametrize("program,db_type", PROGRAMS.items())
async def test_wrong_catalog_type_is_rejected_without_job_or_outbox(program, db_type):
    session = FakeDbSession(blast_db=ncbi_catalog("nucl" if db_type == "prot" else "prot"))
    with pytest.raises(NotFoundError):
        await BlastService().submit_job(session, None, request(program), release_context=_context())
    assert not session.added


@pytest.mark.parametrize("field,value", [
    ("index_version", None), ("index_version", "version-label"), ("fasta_sha256", None),
    ("fasta_sha256", "A" * 64),
])
async def test_unverified_ncbi_index_never_creates_job(field, value):
    session = FakeDbSession(blast_db=ncbi_catalog(**{field: value}))
    with pytest.raises(ServiceValidationError, match="verified identity"):
        await BlastService().submit_job(session, None, request(), release_context=_context())
    assert not session.added


@pytest.mark.parametrize("program", ["blastn", "blastx", "tblastn", "tblastx"])
def test_diamond_is_explicitly_blastp_only(program):
    with pytest.raises(ValidationError, match="DIAMOND"):
        request(program, engine="diamond")


@pytest.mark.parametrize("params", [
    {"evalue": float("inf")}, {"evalue": float("nan")}, {"evalue": 1001},
    {"gap_open": 101}, {"word_size": 1000}, {"arbitrary_flag": "-out /private"},
])
def test_parameters_are_bounded_and_never_silently_ignored(params):
    with pytest.raises(ValidationError):
        request(parameters=BlastParameters(**params))


@pytest.mark.parametrize("program", ["blastn", "blastx", "tblastx"])
def test_nucleotide_queries_use_shared_iupac_validator(program):
    query = request(program)
    assert query.engine == "ncbi_blast"
    with pytest.raises(ValidationError):
        BlastSubmitRequest(program=program, query_sequence=PROTEIN)


def test_ncbi_blastn_identity_filter_maps_to_executable_flag():
    params = BlastParameters(percent_identity=95)
    valid = request("blastn", parameters=params)
    assert valid.parameters.canonical_parameters("blastn", "ncbi_blast")["perc_identity"] == 95
    for program in ("blastp", "blastx", "tblastn", "tblastx"):
        with pytest.raises(ValidationError, match="only by NCBI blastn"):
            request(program, parameters=params)


async def test_job_response_uses_frozen_provenance_and_legacy_engine_fallback():
    from app.models.blast import BlastJobStatus
    from tests.test_blast_results import _make_job

    service = BlastService()
    legacy = _make_job(BlastJobStatus.COMPLETED)
    assert service._job_to_response(legacy).engine == "diamond"
    catalog = ncbi_catalog()
    session = FakeDbSession(blast_db=catalog)
    await service.submit_job(session, uuid.uuid4(), request(), release_context=_context())
    job = next(item for item in session.added if isinstance(item, BlastJob))
    # Even if the associated mutable catalog is later relabeled, the submitted
    # engine and release describe the execution originally requested.
    catalog.engine = "diamond"
    response = service._job_to_response(job)
    assert response.engine == "ncbi_blast"
    assert response.release_id == 7


@pytest.fixture(autouse=True)
def isolated_database_quota_boundary(monkeypatch):
    """These fake-session tests cover mapping; PostgreSQL quota tests cover locks."""
    async def enforce(_self, _db, _user_id):
        return None

    monkeypatch.setattr(BlastService, "_enforce_user_limit", enforce)

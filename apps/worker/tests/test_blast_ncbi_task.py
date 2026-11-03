"""The NCBI engine reuses the existing job lifecycle without weakening index binding."""

from __future__ import annotations

import pytest

from soymutdb_worker.tasks import blast
from tests.test_blast_task import FakeSession, FakeTask, _call_task, _fake_db, _payload


def provenance():
    return {
        "source_sha256": "a" * 64,
        "db_type": "nucl",
        "metadata": {"release_id": "7", "assembly_id": "42"},
    }


def test_ncbi_mapping_requires_frozen_identity(monkeypatch, tmp_path):
    identity = "b" * 64
    prefix = tmp_path / identity / "db"
    monkeypatch.setattr(blast, "NCBI_BLAST_DATABASE_PATHS", {"reference": str(prefix)})
    calls = []

    def verify(root, key, **kwargs):
        calls.append((root, key))
        return {"manifest": {"request": provenance()}}

    monkeypatch.setattr(blast, "verify_index", verify)
    args = dict(
        index_identity=identity,
        fasta_sha256="a" * 64,
        database_type="nucl",
        release_key="7",
        assembly_id="42",
    )
    assert blast.get_ncbi_db_path("reference", **args) == prefix
    assert calls == [(tmp_path, identity)]
    for key, value in (
        ("fasta_sha256", "c" * 64),
        ("database_type", "prot"),
        ("release_key", "8"),
        ("assembly_id", "43"),
        ("index_identity", "d" * 64),
    ):
        with pytest.raises(ValueError, match="mismatch"):
            blast.get_ncbi_db_path("reference", **{**args, key: value})
    with pytest.raises(ValueError, match="not configured"):
        blast.get_ncbi_db_path("other", **args)


@pytest.mark.parametrize(
    "program,db_type,sequence",
    [
        ("blastn", "nucl", ">dna\nACGTTGCAACGTTGCA"),
        ("blastp", "prot", ">protein\nMKVLAAGIVGLNLGGK"),
        ("blastx", "prot", ">dna\nATGAAAGTTCTTGCTGCTGGT"),
        ("tblastn", "nucl", ">protein\nMKVLAAGIVGLNLGGK"),
        ("tblastx", "nucl", ">dna\nATGAAAGTTCTTGCTGCTGGT"),
    ],
)
def test_ncbi_task_uses_existing_lifecycle_and_result_storage(
    monkeypatch,
    tmp_path,
    program,
    db_type,
    sequence,
):
    from soymutdb_worker import ncbi_blast

    session = FakeSession()
    monkeypatch.setattr(blast, "get_db", lambda: _fake_db(session))
    monkeypatch.setattr(blast, "get_ncbi_db_path", lambda *args, **kwargs: tmp_path / "db")
    monkeypatch.setattr(blast, "notify_completed", lambda *args, **kwargs: None)
    monkeypatch.setattr(blast, "upload_file", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        blast, "generate_presigned_url", lambda *args, **kwargs: "https://objects/results"
    )
    monkeypatch.setattr(
        blast, "get_blast_db_path", lambda *args, **kwargs: pytest.fail("DIAMOND index used")
    )
    monkeypatch.setattr(
        blast, "run_blast_command", lambda *args, **kwargs: pytest.fail("DIAMOND executed")
    )
    hit = {
        "query_id": "first-query",
        "subject_id": "subject",
        "subject_title": "",
        "percent_identity": 100.0,
        "alignment_length": 15,
        "mismatches": 0,
        "gap_opens": 0,
        "query_start": 1,
        "query_end": 15,
        "subject_start": 30,
        "subject_end": 16,
        "evalue": 1e-10,
        "bit_score": 42.0,
        "query_strand": "plus",
        "subject_strand": "minus",
    }
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        assert kwargs["query_path"].read_text().startswith(">")
        kwargs["output_path"].write_text("known raw NCBI output\n")
        return {"hits": [hit], "total_hits": 1}

    monkeypatch.setattr(ncbi_blast, "run_search", search)
    payload = _payload()
    payload["payload"].update(
        {
            "engine": "ncbi_blast",
            "program": program,
            "database_type": db_type,
            "sequence": sequence,
            "index_identity": "b" * 64,
            "fasta_sha256": "a" * 64,
            "release_key": "7",
            "assembly_id": 42,
        }
    )
    result = _call_task(blast.run_blast, FakeTask(), payload=payload)
    assert result["total_hits"] == 1
    assert session.status == "completed"
    assert session.inserted_hits[0]["query_id"] == "first-query"
    assert session.inserted_hits[0]["subject_strand"] == "minus"
    assert calls[0]["program"] == program
    assert calls[0]["db_type"] == db_type
    repeated = _call_task(blast.run_blast, FakeTask(), payload=payload)
    assert repeated["skipped"] is True
    assert len(calls) == 1

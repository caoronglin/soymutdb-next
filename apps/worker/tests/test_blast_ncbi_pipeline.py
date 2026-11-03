"""Real immutable index -> existing task -> PostgreSQL HSP persistence.

The object-store upload and notifications are replaced at their network edge;
this proves local search/persistence, not a live broker or S3 deployment.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from soymutdb_worker.blast_index import BuildMetadata, build_index
from soymutdb_worker.shared import BLAST_RUN_TASK, JobPayload
from soymutdb_worker.tasks import blast
from tests.test_blast_task import FakeTask, _call_task
from tests.test_ncbi_blast_real import DNA, PROTEIN


@pytest.fixture(scope="module")
def real_indexes(tmp_path_factory):
    raw = os.getenv("SOYMUTDB_TEST_NCBI_BIN_DIR")
    if not raw:
        pytest.skip("SOYMUTDB_TEST_NCBI_BIN_DIR is required")
    binary_dir = Path(raw)
    directory = tmp_path_factory.mktemp("ncbi-pipeline")
    root = directory / "indexes"
    root.mkdir()
    indexes = {}
    for kind, sequence in (("nucl", DNA), ("prot", PROTEIN)):
        source = directory / f"{kind}.fa"
        source.write_text(f">subject\n{sequence}\n")
        result = build_index(
            source,
            root,
            kind,
            BuildMetadata(
                "42",
                "synthetic-v1",
                "7",
                "synthetic-v1",
                "https://github.com/caoronglin/soymutdb-next/",
                "test-fixture",
                "CC0-1.0",
            ),
            makeblastdb_bin=binary_dir / "makeblastdb",
            blastdbcmd_bin=binary_dir / "blastdbcmd",
        )
        indexes[kind] = (root / result["index_prefix"], result)
    return binary_dir, indexes


@pytest.fixture
def database():
    url = os.getenv("SOYMUTDB_WORKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SOYMUTDB_WORKER_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    schema = "ncbi_pipeline_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(
            text("""
            CREATE TABLE blast_jobs (
                id UUID PRIMARY KEY, user_id UUID, status VARCHAR(32) NOT NULL,
                started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
                -- The worker re-checks the job's deadline before launching the
                -- aligner, so the fixture must carry the real column (0042).
                expires_at TIMESTAMPTZ,
                error_message TEXT, result_path TEXT, query_len INTEGER, hit_count INTEGER,
                parameters JSONB
            )
        """)
        )
        # Protein-subject programs resolve their hits through explicit
        # assembly-scoped relations, so the fixture carries the four tables
        # that resolver reads (it must not need a table the worker cannot
        # assume exists).
        connection.execute(text("""
            CREATE TABLE assemblies (id INTEGER PRIMARY KEY, name VARCHAR(128),
                                     version VARCHAR(64), release_id INTEGER)
        """))
        connection.execute(text("""
            CREATE TABLE chromosomes (id INTEGER PRIMARY KEY, assembly_id INTEGER NOT NULL,
                                      name VARCHAR(64))
        """))
        connection.execute(text("""
            CREATE TABLE genes (gene_pk BIGSERIAL PRIMARY KEY, accession VARCHAR(64),
                                assembly_id INTEGER NOT NULL, chromosome_id INTEGER,
                                start BIGINT, "end" BIGINT, strand VARCHAR(1))
        """))
        connection.execute(text("""
            CREATE TABLE transcripts (id VARCHAR(64) PRIMARY KEY, gene_id BIGINT,
                                      is_canonical BOOLEAN)
        """))
        connection.execute(text("""
            CREATE TABLE gene_aliases (id SERIAL PRIMARY KEY, gene_id BIGINT,
                                       alias VARCHAR(256), source VARCHAR(128))
        """))
        connection.execute(
            text("""
            CREATE TABLE blast_hits (
                id SERIAL PRIMARY KEY, job_id UUID NOT NULL REFERENCES blast_jobs(id),
                hsp_num INTEGER NOT NULL,
                query_id VARCHAR(256), subject_id VARCHAR(256) NOT NULL, subject_title TEXT,
                percent_identity FLOAT, alignment_length INTEGER, mismatches INTEGER,
                gap_opens INTEGER, query_start INTEGER, query_end INTEGER,
                subject_start INTEGER, subject_end INTEGER, evalue FLOAT, bit_score FLOAT,
                query_strand VARCHAR(8), subject_strand VARCHAR(8),
                -- Migration 0053: proven genomic resolution, never AA offsets.
                genome_resolution JSONB
            )
        """)
        )

    @contextmanager
    def session():
        with Session(engine) as db:
            db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            with db.begin_nested():
                yield db
            db.commit()

    yield session
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


@pytest.mark.parametrize(
    "program,kind,query",
    [
        ("blastn", "nucl", DNA),
        ("blastp", "prot", PROTEIN),
        ("blastx", "prot", DNA),
        ("tblastn", "nucl", PROTEIN),
        ("tblastx", "nucl", DNA),
    ],
)
def test_real_ncbi_task_persists_query_identity_and_execution_provenance(
    monkeypatch,
    database,
    real_indexes,
    program,
    kind,
    query,
):
    binary_dir, indexes = real_indexes
    prefix, index = indexes[kind]
    identity = index["index_identity"]
    digest = index["manifest"]["request"]["source_sha256"]
    job_id = uuid.uuid4()
    with database() as db:
        db.execute(
            text("""
            INSERT INTO blast_jobs(id,status,parameters) VALUES (
                :job,'pending',CAST(:parameters AS jsonb)
            )
        """),
            {
                "job": job_id,
                "parameters": '{"_public_blast":true,"_search_provenance":{"engine":"ncbi_blast"}}',
            },
        )
    monkeypatch.setattr(blast, "get_db", database)
    monkeypatch.setattr(blast, "NCBI_BLAST_BIN_DIR", binary_dir)
    monkeypatch.setattr(blast, "NCBI_BLAST_DATABASE_PATHS", {"synthetic": str(prefix)})
    monkeypatch.setattr(blast, "notify_completed", lambda *args, **kwargs: None)
    monkeypatch.setattr(blast, "notify_failed", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        blast, "generate_presigned_url", lambda *args, **kwargs: "https://objects/results"
    )
    uploads = []
    monkeypatch.setattr(
        blast,
        "upload_file",
        lambda path, target, **kwargs: uploads.append((Path(path).read_bytes(), target, kwargs)),
    )
    now = datetime.now(UTC)
    payload = JobPayload(
        job_id=str(job_id),
        task_name=BLAST_RUN_TASK,
        idempotency_key=f"blast:{job_id}",
        created_at=now,
        updated_at=now,
        payload={
            "job_id": str(job_id),
            "engine": "ncbi_blast",
            "program": program,
            "database": "synthetic",
            "database_type": kind,
            "index_identity": identity,
            "fasta_sha256": digest,
            "release_key": "7",
            "assembly_id": 42,
            "sequence": f">first-query\n{query}\n>second-query\n{query}\n",
            "evalue": 1e-5,
            "max_target_seqs": 5,
        },
    ).model_dump(mode="json")
    result = _call_task(blast.run_blast, FakeTask(), payload=payload)
    assert result["total_hits"] >= 2
    assert len(uploads) == 1 and uploads[0][0]
    with database() as db:
        job = db.execute(
            text("SELECT status,parameters,query_len FROM blast_jobs WHERE id=:job"),
            {"job": job_id},
        ).one()
        assert job.status == "completed"
        assert job.parameters["_public_blast"] is True
        assert job.parameters["_search_provenance"]["engine"] == "ncbi_blast"
        assert job.parameters["_execution"]["binary"]["program"] == program
        assert len(job.parameters["_execution"]["binary"]["sha256"]) == 64
        assert job.query_len == len(query) * 2
        ids = (
            db.execute(
                text("SELECT DISTINCT query_id FROM blast_hits WHERE job_id=:job"), {"job": job_id}
            )
            .scalars()
            .all()
        )
        assert set(ids) == {"first-query", "second-query"}
    repeated = _call_task(blast.run_blast, FakeTask(), payload=payload)
    assert repeated["skipped"] is True
    assert len(uploads) == 1

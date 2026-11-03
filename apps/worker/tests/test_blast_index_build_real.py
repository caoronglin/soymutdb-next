"""Opt-in real NCBI binaries + real PostgreSQL build/publish acceptance.

No mocked search: ``makeblastdb``/``blastdbcmd`` 2.17.0+ run for real on
purpose-written synthetic CC0 sequence, and the state transitions land in a
real PostgreSQL ``blast_index_builds``/``blast_databases`` schema.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from soymutdb_worker.tasks import blast_index as build_module

DNA = ">synthetic_forward\nACGTTGCAACGTTGCAACGTTGCA\n>synthetic_reverse\nTGCAACGTTGCAACGT\n"
METADATA = {
    "assembly_id": "synthetic-test-assembly", "assembly_version": "1",
    "release_id": "test-only", "annotation_version": "synthetic-v1",
    "source_url": "https://github.com/caoronglin/soymutdb-next/blob/main/"
                  "apps/worker/tests/test_blast_index_build_real.py",
    "source_version": "2026-11-03", "license": "CC0-1.0",
}


class FakeTask:
    def update_state(self, **kwargs):
        pass


@pytest.fixture(scope="module")
def ncbi_binaries():
    raw = os.getenv("SOYMUTDB_TEST_NCBI_BIN_DIR")
    if not raw:
        pytest.skip("SOYMUTDB_TEST_NCBI_BIN_DIR is required")
    directory = Path(raw)
    for name in ("makeblastdb", "blastdbcmd"):
        if not (directory / name).is_file():
            pytest.skip(f"missing {name} in {directory}")
    return directory


@pytest.fixture
def database():
    url = os.getenv("SOYMUTDB_WORKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SOYMUTDB_WORKER_TEST_DATABASE_URL is required")
    engine = create_engine(url)
    schema = "blast_build_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("""
            CREATE TABLE blast_index_builds (
                id UUID PRIMARY KEY, database_id INTEGER, state VARCHAR(20) NOT NULL,
                source_object_key VARCHAR(2048) NOT NULL, source_sha256 VARCHAR(64),
                db_type VARCHAR(4) NOT NULL, build_metadata JSONB NOT NULL,
                index_identity VARCHAR(64), sequence_count BIGINT, total_length BIGINT,
                error_message TEXT, requested_by UUID, started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        connection.execute(text("""
            CREATE TABLE blast_databases (
                id INTEGER PRIMARY KEY, name VARCHAR(256), db_type VARCHAR(4),
                engine VARCHAR(16), build_status VARCHAR(20), is_active BOOLEAN,
                is_default BOOLEAN, index_version VARCHAR(256), fasta_sha256 VARCHAR(64),
                sequence_count BIGINT, total_length BIGINT, provenance JSONB
            )
        """))
        connection.execute(text(
            "INSERT INTO blast_databases(id,name,db_type,engine,build_status,is_active,"
            "is_default,sequence_count,total_length) VALUES "
            "(1,'synthetic','nucl','ncbi_blast','pending',false,false,0,0)"
        ))

    @contextmanager
    def session():
        with Session(engine) as db:
            db.execute(text(f'SET search_path TO "{schema}"'))
            yield db
            db.commit()

    yield engine, schema, session
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def test_real_build_publishes_and_is_idempotent(monkeypatch, tmp_path, ncbi_binaries, database):
    engine, schema, session_factory = database
    build_id = uuid.uuid4()
    with session_factory() as db:
        db.execute(text(
            "INSERT INTO blast_index_builds(id,database_id,state,source_object_key,"
            "db_type,build_metadata) VALUES (:id,1,'pending','blast-sources/synthetic.fa',"
            "'nucl',CAST(:metadata AS jsonb))"
        ), {"id": build_id, "metadata": __import__("json").dumps(METADATA)})

    root = tmp_path / "indexes"
    root.mkdir()
    monkeypatch.setattr(build_module, "INDEX_ROOT", root)
    monkeypatch.setattr(build_module, "MAKEBLASTDB_BIN", ncbi_binaries / "makeblastdb")
    monkeypatch.setattr(build_module, "BLASTDBCMD_BIN", ncbi_binaries / "blastdbcmd")
    monkeypatch.setattr(build_module, "get_db", session_factory)
    monkeypatch.setattr(
        build_module, "_download_source",
        lambda key, destination: (
            destination.write_text(DNA),
            __import__("hashlib").sha256(DNA.encode()).hexdigest(),
        )[1],
    )

    result = build_module.build_index.run.__func__(FakeTask(), build_id=str(build_id))
    assert result["state"] == "published"
    identity = result["index_identity"]
    assert len(identity) == 64
    assert (root / identity / "manifest.json").is_file()
    assert not list(tmp_path.glob(".blast-build-*"))

    with engine.begin() as connection:
        connection.execute(text(f'SET search_path TO "{schema}"'))
        row = connection.execute(text(
            "SELECT state,index_identity,sequence_count,total_length FROM blast_index_builds"
        )).one()
        assert row[0] == "published" and row[1] == identity
        expected_letters = (len("ACGTTGCAACGTTGCAACGTTGCA")
                            + len("TGCAACGTTGCAACGT"))
        assert row[2] == 2 and row[3] == expected_letters
        catalog = connection.execute(text(
            "SELECT build_status,index_version,fasta_sha256,sequence_count,is_active "
            "FROM blast_databases"
        )).one()
        assert catalog[0] == "published" and catalog[1] == identity
        assert len(catalog[2]) == 64 and catalog[3] == 2
        # Publication must activate the row, otherwise search discovery skips it.
        assert catalog[4] is True

    # A redelivery of the same outbox event must not rebuild or overwrite.
    monkeypatch.setattr(
        build_module, "build_immutable_index",
        lambda *a, **k: pytest.fail("redelivery must not rebuild"),
    )
    assert build_module.build_index.run.__func__(FakeTask(), build_id=str(build_id)) == {
        "build_id": str(build_id), "skipped": True, "state": "published",
    }

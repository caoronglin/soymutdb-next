"""Celery index build lifecycle: guarded states, cleanup, no HTTP-path leaks."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from soymutdb_jobs import blast_catalog_state as state
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert, select
from sqlalchemy.orm import Session

from soymutdb_worker.blast_catalog_store import BlastCatalogStore, CatalogStateError
from soymutdb_worker.blast_index import BuildMetadata
from soymutdb_worker.tasks import blast_index_tasks as tasks
from tests.test_blast_task import FakeTask


class _Call:
    def __init__(self, payload: dict):
        self.payload = payload


@pytest.fixture
def catalog_db():
    """Minimal real SQLite schema mirroring the catalog columns we touch."""
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table(
        "blast_databases", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(256)),
        Column("engine", String(16)),
        Column("db_type", String(4)),
        Column("build_status", String(20), nullable=False, default="pending"),
        Column("build_error", String),
        Column("build_attempt", Integer, nullable=False, default=0),
        Column("build_started_at", String),
        Column("build_finished_at", String),
        Column("index_health_checked_at", String),
        Column("file_path", String(2048)),
        Column("index_version", String(256)),
        Column("fasta_sha256", String(64)),
        Column("sequence_count", Integer),
        Column("total_length", Integer),
        Column("annotation_version", String(256)),
    )
    metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(insert(table).values(
            id=7, name="synthetic", engine="ncbi_blast", db_type="nucl",
            build_status="pending", file_path="", sequence_count=0, total_length=0,
        ))
        session.commit()
    yield engine, table
    engine.dispose()


def _db(engine):
    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session
            session.commit()
    return factory


def _status(engine, table, database_id=7):
    with Session(engine) as session:
        return session.execute(
            select(table.c.build_status, table.c.index_version, table.c.build_error,
                   table.c.build_attempt, table.c.sequence_count, table.c.total_length)
            .where(table.c.id == database_id)
        ).one()


def test_guarded_transitions_and_publication(catalog_db):
    engine, table = catalog_db
    with Session(engine) as session:
        store = BlastCatalogStore(session)
        assert store.runnable(store.get(7)) is False
        assert store.transition(7, expected=state.PENDING, target=state.BUILDING)
        with pytest.raises(CatalogStateError):
            store.transition(7, expected=state.BUILDING, target=state.PUBLISHED)
        assert store.transition(7, expected=state.BUILDING, target=state.VALIDATING)
        assert store.transition(7, expected=state.VALIDATING, target=state.PUBLISHING)
        assert store.publish(
            7, index_identity="a" * 64, fasta_sha256="b" * 64,
            sequence_count=2, total_length=64, annotation_version="v1",
        )
        session.commit()
    status, identity, error, attempt, count, length = _status(engine, table)
    assert status == state.PUBLISHED and identity == "a" * 64
    assert error is None and attempt == 1 and count == 2 and length == 64
    with Session(engine) as session:
        store = BlastCatalogStore(session)
        assert store.runnable(store.get(7)) is True
        assert store.mark_healthy(7)
        # Publishing is one-shot: a second delivery cannot re-publish.
        assert not store.publish(7, index_identity="c" * 64, fasta_sha256="d" * 64,
                                 sequence_count=9, total_length=99)
        with pytest.raises(CatalogStateError):
            store.transition(7, expected=state.PUBLISHED, target=state.PUBLISHED)


def test_failed_build_records_a_sanitized_reason(catalog_db):
    engine, table = catalog_db
    with Session(engine) as session:
        store = BlastCatalogStore(session)
        store.transition(7, expected=state.PENDING, target=state.BUILDING)
        store.transition(7, expected=state.BUILDING, target=state.FAILED,
                         build_error="makeblastdb: /data/private/secret.fa\nraw AA")
        session.commit()
    status, _identity, error, *_ = _status(engine, table)
    assert status == state.FAILED
    assert error == "makeblastdb: /data/private/secret.fa\nraw AA"


def test_source_object_reference_is_bounded():
    with pytest.raises(ValueError):
        tasks._source_key("/etc/passwd")
    with pytest.raises(ValueError):
        tasks._source_key("blast-sources/../other.fa")
    with pytest.raises(ValueError):
        tasks._source_key("s3://other-bucket/x.fa")
    assert tasks._source_key("blast-sources/wm82.v4.fa") == "blast-sources/wm82.v4.fa"
    with pytest.raises(ValueError):
        tasks._source_key("s3://blast-dbs/blast-sources/wm82.v4.fa")


def test_build_task_drives_the_whole_state_machine(monkeypatch, catalog_db, tmp_path):
    engine, table = catalog_db
    root = tmp_path / "indexes"
    root.mkdir()
    monkeypatch.setattr(tasks, "BLAST_INDEX_ROOT", root)
    monkeypatch.setattr(tasks, "get_db", _db(engine))
    monkeypatch.setattr(tasks, "_download_source", lambda ref, dest: dest.write_text(
        ">subject\nACGTTGCAACGTTGCA\n>other\nTGCAACGTTGCAACGT\n"))

    def fake_build(source, output_root, db_type, metadata, **kwargs):
        assert source.read_text().startswith(">subject")
        assert db_type == "nucl"
        assert isinstance(metadata, BuildMetadata)
        (output_root / ".build-stale").mkdir()
        return {
            "index_identity": "a" * 64,
            "reused": False,
            "manifest": {"request": {
                "source_sha256": "b" * 64, "sequence_count": 2, "letter_count": 32,
                "metadata": {"annotation_version": "v1"},
            }},
        }

    monkeypatch.setattr(tasks, "build_index", fake_build)
    monkeypatch.setattr(tasks, "verify_index", lambda *a, **k: {
        "manifest": {"request": {
            "source_sha256": "b" * 64, "sequence_count": 2, "letter_count": 32,
            "metadata": {"annotation_version": "v1"},
        }}
    })
    payload = {"database_id": 7, "db_type": "nucl", "source_object": "blast-sources/x.fa",
               "assembly_id": "42", "assembly_version": "v4", "release_id": "7",
               "annotation_version": "v1", "source_url": "https://www.soybase.org/",
               "source_version": "v1", "license": "CC0-1.0"}
    result = tasks.build_blast_index.run.__func__(FakeTask(), payload)
    assert result["index_identity"] == "a" * 64
    assert result["build_status"] == state.PUBLISHED
    # The success path deliberately does NOT sweep staging: a concurrent
    # builder may own a .build-* directory. The hourly health task does.
    assert (root / ".build-stale").exists()
    assert not list(root.glob(".source-7.fasta"))
    monkeypatch.setattr(tasks, "get_db", _db(engine))
    monkeypatch.setattr(tasks, "verify_index", lambda *a, **k: {
        "manifest": {"request": {"source_sha256": "b" * 64, "sequence_count": 2,
                                 "letter_count": 32,
                                 "metadata": {"annotation_version": "v1"}}}
    })
    tasks.check_blast_index_health.run.__func__(FakeTask())
    assert not (root / ".build-stale").exists(), "health task swept orphan staging"
    status, identity, error, *_ = _status(engine, table)
    assert (status, identity, error) == (state.PUBLISHED, "a" * 64, None)

    # Re-delivery is a no-op; the published identity is immutable.
    again = tasks.build_blast_index.run.__func__(
        FakeTask(), {**payload, "index_identity": "a" * 64}
    )
    assert again["skipped"] is True


def test_failed_build_cleans_staging_and_marks_failed(monkeypatch, catalog_db, tmp_path):
    engine, table = catalog_db
    root = tmp_path / "indexes"
    root.mkdir()
    monkeypatch.setattr(tasks, "BLAST_INDEX_ROOT", root)
    monkeypatch.setattr(tasks, "get_db", _db(engine))
    monkeypatch.setattr(tasks, "_download_source", lambda ref, dest: dest.write_text(">x\nACGT\n"))

    def boom(*args, **kwargs):
        (root / ".build-orphan").mkdir()
        raise RuntimeError("binary exploded /data/private/path.fa\nACGT")

    monkeypatch.setattr(tasks, "build_index", boom)
    payload = {"database_id": 7, "db_type": "nucl", "source_object": "blast-sources/x.fa",
               "assembly_id": "42", "assembly_version": "v4", "release_id": "7",
               "annotation_version": "v1", "source_url": "https://www.soybase.org/",
               "source_version": "v1", "license": "CC0-1.0"}
    with pytest.raises(RuntimeError):
        tasks.build_blast_index.run.__func__(FakeTask(), payload)
    status, identity, error, *_ = _status(engine, table)
    assert status == state.FAILED and identity is None
    assert "binary exploded" in error
    assert not (root / ".build-orphan").exists()
    assert not (root / ".source-7.fasta").exists()


def test_a_transition_the_catalog_rejects_marks_failed_and_keeps_identity(
    monkeypatch, catalog_db, tmp_path
):
    """A guarded write that the schema rejects must fail closed.

    If the catalog's build-status vocabulary and the state machine ever drift,
    the guarded UPDATE raises instead of publishing. The task then has to
    record ``failed`` and leave the previously published identity untouched —
    it must never leave a row sitting in ``publishing``.
    """
    engine, table = catalog_db
    root = tmp_path / "indexes"
    root.mkdir()
    monkeypatch.setattr(tasks, "BLAST_INDEX_ROOT", root)
    monkeypatch.setattr(tasks, "get_db", _db(engine))
    monkeypatch.setattr(tasks, "_download_source",
                        lambda ref, dest: dest.write_text(">x\nACGT\n"))
    monkeypatch.setattr(tasks, "build_index", lambda *a, **k: {
        "index_identity": "a" * 64, "reused": False,
        "manifest": {"request": {
            "source_sha256": "b" * 64, "sequence_count": 1, "letter_count": 4,
            "metadata": {"annotation_version": "v1"},
        }},
    })
    monkeypatch.setattr(tasks, "verify_index", lambda *a, **k: {
        "manifest": {"request": {
            "source_sha256": "b" * 64, "sequence_count": 1, "letter_count": 4,
            "metadata": {"annotation_version": "v1"},
        }},
    })

    def rejected_publish(*args, **kwargs):
        raise RuntimeError("new row for relation \"blast_databases\" violates "
                           "check constraint \"ck_blast_catalog_build_status\"")

    monkeypatch.setattr(tasks.BlastCatalogStore, "publish", rejected_publish)
    payload = {"database_id": 7, "db_type": "nucl", "source_object": "blast-sources/x.fa",
               "assembly_id": "42", "assembly_version": "v4", "release_id": "7",
               "annotation_version": "v1", "source_url": "https://www.soybase.org/",
               "source_version": "v1", "license": "CC0-1.0"}
    with pytest.raises(RuntimeError):
        tasks.build_blast_index.run.__func__(FakeTask(), payload)
    status, identity, error, *_ = _status(engine, table)
    assert status == state.FAILED, "a rejected publication must not stay in flight"
    assert identity is None, "no identity may be recorded for a failed publication"
    assert "check constraint" in error

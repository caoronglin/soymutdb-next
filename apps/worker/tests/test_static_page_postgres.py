"""Execute static-page scope and batching against an isolated PostgreSQL schema."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from soymutdb_worker.tasks import static_pages as sp


def _static_url_or_fail() -> str:
    """The static-page PostgreSQL URL, or a hard failure (never a skip).

    Mirrors ``_native_url_or_fail`` in the sibling suites. Skipping here made
    three release-scope and keyset-batching assertions invisible to the gate
    while ``SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`` claimed a real database was
    present. ``scripts/with-postgres-service.sh`` derives this variable, so an
    absent value is a wiring bug, not an absent database.

    No scheme check here: the value either comes from ``derive_sync_url``,
    which only emits ``postgresql+psycopg2://``, or from a caller who set the
    variable themselves. A ``startswith("postgresql")`` guard on that value
    would be unreachable, and an unreachable guard reads as protection that is
    not there.
    """
    url = os.environ.get("SOYMUTDB_STATIC_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "SOYMUTDB_STATIC_TEST_DATABASE_URL is required: scripts/with-postgres-service.sh "
            "derives it from SOYMUTDB_TEST_DATABASE_URL. This suite is a merge gate; it "
            "must fail rather than skip."
        )
    return url


@pytest.fixture
def static_page_database(monkeypatch):
    url = _static_url_or_fail()
    schema = "static_page_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE releases (id int primary key, status text)"))
            conn.execute(text("CREATE TABLE assemblies (id int primary key, release_id int)"))
            conn.execute(text("CREATE TABLE chromosomes (id int primary key, name text)"))
            conn.execute(text(
                "CREATE TABLE genes (gene_pk bigint primary key, accession text, "
                "assembly_id int, chromosome_id int, name text, biotype text, "
                'start bigint, "end" bigint, strand text, description text)'
            ))
            conn.execute(text("INSERT INTO releases VALUES (1,'published'),(2,'draft')"))
            conn.execute(text("INSERT INTO assemblies VALUES (1,1),(2,1),(3,2)"))
            conn.execute(text("INSERT INTO chromosomes VALUES (1,'Chr01')"))
            conn.execute(text(
                "INSERT INTO genes (gene_pk,accession,assembly_id,chromosome_id) "
                "VALUES (1,'shared',1,1),(2,'shared',2,1),(3,'other',1,1),"
                "(4,'last',2,1),(5,'draft-only',3,1)"
            ))
        sessions = sessionmaker(bind=engine)

        @contextmanager
        def get_db():
            with sessions.begin() as session:
                yield session

        monkeypatch.setattr(sp, "get_db", get_db)
        monkeypatch.setattr(sp, "_GENE_CHUNK", 2)
        yield engine, get_db
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_release_scope_and_keyset_batches_on_postgres(static_page_database):
    _, get_db = static_page_database
    with get_db() as session:
        assert session.execute(sp.gene_scope_count_statement(release_id=1)).scalar_one() == 4
    batches = list(sp.iter_gene_batches(release_id=1))
    assert [len(batch) for batch in batches] == [2, 2]
    assert [row.gene_pk for batch in batches for row in batch] == [1, 2, 3, 4]
    shared = list(sp.iter_gene_batches(release_id=1, gene_ids=["shared"]))
    assert [(row.accession, row.assembly_id) for batch in shared for row in batch] == [
        ("shared", 1), ("shared", 2),
    ]
    assert list(sp.iter_gene_batches(release_id=1, gene_ids=[])) == []


def test_release_validation_on_postgres(static_page_database):
    _, get_db = static_page_database
    with get_db() as session:
        sp.require_published_release(session, 1)
        with pytest.raises(ValueError, match="not 'published'"):
            sp.require_published_release(session, 2)
        with pytest.raises(ValueError, match="does not exist"):
            sp.require_published_release(session, 999)


def test_read_only_batch_snapshot_allows_independent_writer(static_page_database):
    engine, _ = static_page_database
    with sp._read_only_snapshot() as session:
        assert session.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert session.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert session.execute(text("SELECT name FROM genes WHERE gene_pk=1")).scalar_one() is None
        with engine.begin() as writer:
            writer.execute(text("SET LOCAL lock_timeout='1s'"))
            writer.execute(text("UPDATE genes SET name='updated' WHERE gene_pk=1"))
        assert session.execute(text("SELECT name FROM genes WHERE gene_pk=1")).scalar_one() is None
    with engine.connect() as conn:
        name = conn.execute(text("SELECT name FROM genes WHERE gene_pk=1")).scalar_one()
        assert name == "updated"

"""Real PostgreSQL coverage for the worker-side import manifest repository (P2-3).

Gated like the other worker integration tests (``SOYMUTDB_RUN_POSTGRES_INTEGRATION=1``
+ ``SOYMUTDB_TEST_DATABASE_URL``): it upgrades the API's actual Alembic chain so
the worker repo runs against the real migrated ``import_manifests`` schema. CI
always enables the gate; a local unit run without it skips (never a false green),
and once requested, a missing database is a hard failure.

Asserts the shared ADR-0005 contract end-to-end on the worker side: idempotent
start by fingerprint, guarded transitions, FAILED -> CREATED retry, publish
visibility (PUBLISHED only), release isolation, and worker-table/migration parity.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from soymutdb_import_protocol import ImportManifestStatus
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from soymutdb_worker.tasks.import_manifest_repo import (
    InvalidManifestTransition,
    get,
    is_published,
    manifest_lock,
    record_counts,
    start_or_resume,
    transition,
)

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
POSTGRES_INTEGRATION_ENV = "SOYMUTDB_RUN_POSTGRES_INTEGRATION"


def _upgrade(database_url: str) -> None:
    environment = os.environ.copy()
    environment["SOYMUTDB_DATABASE_URL"] = database_url
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(API_ROOT), environment.get("PYTHONPATH", "")) if value
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=API_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Alembic upgrade failed:\n{result.stderr[-4000:]}")


@pytest.fixture(scope="module")
def session_factory() -> Iterator[sessionmaker[Session]]:
    if os.environ.get(POSTGRES_INTEGRATION_ENV) != "1":
        pytest.skip(f"set {POSTGRES_INTEGRATION_ENV}=1 to run PostgreSQL integration")
    external_url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if not external_url:
        pytest.fail(f"{POSTGRES_INTEGRATION_ENV}=1 requires SOYMUTDB_TEST_DATABASE_URL here")
    if not external_url.startswith("postgresql+asyncpg://"):
        pytest.fail("SOYMUTDB_TEST_DATABASE_URL must use the postgresql+asyncpg:// scheme")
    sync_url = make_url(external_url).set(drivername="postgresql+psycopg2").render_as_string(
        hide_password=False
    )
    _upgrade(external_url)
    engine = create_engine(sync_url)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


RUN = uuid.uuid4().hex


def _fields(tag: str, *, release: int = 1, assembly: int = 2) -> dict:
    # Run-unique fingerprints keep the shared fixture DB safe to reuse across
    # manual runs (the same fingerprint must still be identical within a run).
    source = uuid.uuid5(uuid.NAMESPACE_URL, f"{RUN}:{tag}").hex
    return {
        "source_sha256": source,
        "release_id": release,
        "assembly_id": assembly,
        "importer_version": "imp-1",
        "schema_version": "sch-1",
        "normalization_version": "norm-1",
        "config_hash": "cfg-1",
    }


def test_start_is_idempotent_by_fingerprint(session_factory) -> None:
    with session_factory() as session:
        first, created1 = start_or_resume(session, import_id=f"{RUN}-w1", **_fields("a"))
        second, created2 = start_or_resume(session, import_id=f"{RUN}-w1b", **_fields("a"))
        assert created1 is True
        assert created2 is False
        assert second.import_id == first.import_id
        assert first.status == ImportManifestStatus.CREATED.value


def test_distinct_release_is_an_independent_manifest(session_factory) -> None:
    with session_factory() as session:
        a, _ = start_or_resume(session, import_id=f"{RUN}-w2a", **_fields("b"))
        b, _ = start_or_resume(session, import_id=f"{RUN}-w2b", **_fields("b", release=99))
        assert a.import_id != b.import_id
        assert a.fingerprint != b.fingerprint


def test_full_publish_flow_and_visibility(session_factory) -> None:
    with session_factory() as session:
        manifest, _ = start_or_resume(session, import_id=f"{RUN}-w3", **_fields("c"))
        for state in (
            ImportManifestStatus.PARSING,
            ImportManifestStatus.WRITING,
            ImportManifestStatus.VERIFYING,
        ):
            manifest = transition(session, manifest, state)
        assert is_published(manifest) is False
        record_counts(session, manifest, written_rows=42)
        manifest = get(session, manifest.import_id)
        assert manifest["written_rows"] == 42
        manifest = transition(session, manifest, ImportManifestStatus.PUBLISHED)
        assert is_published(manifest) is True
        assert manifest["completed_at"] is not None
        with pytest.raises(InvalidManifestTransition):
            transition(session, manifest, ImportManifestStatus.PARSING)


def test_failed_then_retry_keeps_one_logical_import(session_factory) -> None:
    with session_factory() as session:
        manifest, _ = start_or_resume(session, import_id=f"{RUN}-w4", **_fields("d"))
        manifest = transition(session, manifest, ImportManifestStatus.FAILED)
        assert is_published(manifest) is False
        manifest = transition(session, manifest, ImportManifestStatus.CREATED)
        again, created = start_or_resume(session, import_id=f"{RUN}-w4b", **_fields("d"))
        assert created is False
        assert again.import_id == manifest.import_id


def test_illegal_transition_is_rejected(session_factory) -> None:
    with session_factory() as session:
        manifest, _ = start_or_resume(session, import_id=f"{RUN}-w5", **_fields("e"))
        with pytest.raises(InvalidManifestTransition):
            transition(session, manifest, ImportManifestStatus.PUBLISHED)


def test_manifest_lock_serializes_same_fingerprint_deliveries(session_factory) -> None:
    """A second delivery of the same fingerprint waits, then proceeds.

    The lock is what makes "at most one active writer/finalizer per semantic
    fingerprint" true instead of hoping Celery will not redeliver (review R1 /
    plan G3.3).
    """
    with session_factory() as first:
        manifest, _ = start_or_resume(first, import_id=f"{RUN}-lock", **_fields("lock"))
        fingerprint = manifest.fingerprint
        order: list[str] = []
        started = threading.Event()

        def contender() -> None:
            with session_factory() as second:
                started.set()
                with manifest_lock(second, fingerprint):
                    order.append("second")

        with manifest_lock(first, fingerprint):
            # A manifest transition commits the business session; the lock must
            # survive on its dedicated connection (regression: SQLAlchemy returns
            # the session's connection to the pool at commit, so a lock taken
            # through the session was unlocked from a different connection).
            first.commit()
            thread = threading.Thread(target=contender)
            thread.start()
            assert started.wait(timeout=10), "contender never started"
            # The contender is now blocked on pg_advisory_lock; releasing the
            # first holder must let it through afterwards.
            time.sleep(0.5)
            order.append("first")
        thread.join(timeout=10)
        assert not thread.is_alive(), "contender did not acquire the lock after release"
        assert order == ["first", "second"]


def test_worker_core_table_matches_migrated_schema(session_factory) -> None:
    from soymutdb_worker.tables import import_manifests as table

    with session_factory() as session:
        columns = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'import_manifests'"
                )
            )
        }
    assert {column.name for column in table.c} == columns

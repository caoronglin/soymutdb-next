"""The export claim and finalisation against a real PostgreSQL.

The unit tests drive :class:`VariantExportStore` through a fake session that
answers every UPDATE with ``rowcount=1``.  That cannot show whether the
guarded predicates really hold, so these tests run the same store against
PostgreSQL: two deliveries of one command, a lost lease, and a late
success/failure all have to end in exactly one state.

The table is created by the actual API migration in a throwaway schema.
Only its prerequisite users table is minimal; the export enum, constraints,
indexes and server defaults are the real production DDL.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from soymutdb_jobs.export_artifact import build_export_artifact_key, build_export_filename
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from soymutdb_worker.repositories import EXPORT_CLAIM_LEASE_SECONDS, VariantExportStore
from soymutdb_worker.tables import variant_exports

MIGRATION_0049 = (
    Path(__file__).resolve().parents[3]
    / "apps/api/migrations/versions/0049_variant_exports.py"
)
MIGRATION_0056 = (
    Path(__file__).resolve().parents[3]
    / "apps/api/migrations/versions/0056_download_provenance.py"
)


def _native_url_or_fail() -> str:
    """The native PostgreSQL URL, or a hard failure.

    Fail-closed on purpose. The backend gate exports
    ``SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`` to say "a real database is
    available"; a suite that then *skips* because its own URL is missing
    reports the same pytest verdict as a suite that ran and passed. These tests
    cover variant identity, atomic publication and assembly scoping -- skipping
    them is a merge-gate hole, not an opt-out.

    ``scripts/with-postgres-service.sh`` exports this variable, so an absent
    value means the resolver or the caller dropped it, never "no database".
    """
    url = os.environ.get("SOYMUTDB_NATIVE_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "SOYMUTDB_NATIVE_TEST_DATABASE_URL is required: scripts/with-postgres-service.sh "
            "derives it from SOYMUTDB_TEST_DATABASE_URL. This suite is a merge gate; it "
            "must fail rather than skip."
        )
    return url


@pytest.fixture
def export_database():
    """A throwaway schema with a real ``variant_exports`` table."""
    url = _native_url_or_fail()
    schema = "export_claim_" + uuid.uuid4().hex[:12]
    admin = create_engine(url)
    options = {"options": f"-csearch_path={schema},public"}
    engine = create_engine(
        url, connect_args=options, pool_size=2, max_overflow=0, pool_timeout=5
    )
    observer = create_engine(url, connect_args=options)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.begin() as connection:
            # 0049 adds only this FK dependency; 0056 also alters download_files.
            # No API ORM/create_all shortcut.
            connection.execute(text("CREATE TABLE users (id UUID PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE download_files (id UUID PRIMARY KEY)"))
            for module_name, migration_path in (
                ("export_claim_migration_0049", MIGRATION_0049),
                ("export_claim_provenance_0056", MIGRATION_0056),
            ):
                spec = spec_from_file_location(module_name, migration_path)
                assert spec is not None and spec.loader is not None
                migration = module_from_spec(spec)
                spec.loader.exec_module(migration)
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
        factory = sessionmaker(engine)

        @contextmanager
        def get_db():
            with factory() as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        yield get_db, observer
    finally:
        observer.dispose()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def _insert(get_db, export_id: str, status: str = "pending", started_at=None) -> str:
    """Insert required API-owned fields, relying on real migration defaults."""
    with get_db() as session:
        session.execute(
            text(
                "INSERT INTO variant_exports (id, status, release_key, format) "
                "VALUES (:id, :status, 'test-release', 'tsv')"
            ),
            {"id": export_id, "status": status},
        )
        if started_at is not None:
            session.execute(
                text("UPDATE variant_exports SET started_at = :started_at WHERE id = :id"),
                {"started_at": started_at, "id": export_id},
            )
    return export_id


def _status(observer, export_id: str):
    with observer.connect() as connection:
        return connection.execute(
            text("SELECT status, artifact_path, record_count, updated_at "
                 "FROM variant_exports WHERE id = :id"),
            {"id": export_id},
        ).one()


def test_only_one_delivery_claims_a_pending_export(export_database):
    """The second delivery of the same command must not start a second run."""
    get_db, _observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))

    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "run"
    with get_db() as session:
        # The record is now running: a duplicate dispatch is refused while
        # the first attempt still holds its lease.
        assert VariantExportStore(session).begin_run(export_id) == "skip"


@pytest.mark.parametrize("status,missing_timestamp", [
    ("pending", False), ("running", False), ("running", True),
])
def test_concurrent_deliveries_have_one_claim_winner(export_database, status, missing_timestamp):
    """Both deliveries read the same state before either issues its UPDATE."""
    get_db, _observer = export_database
    stale = datetime.now(UTC) - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS + 60)
    export_id = _insert(
        get_db, str(uuid.uuid4()), status=status,
        started_at=None if missing_timestamp else stale,
    )
    barrier = Barrier(2, timeout=10)

    class RacingStore(VariantExportStore):
        def get_claim_state(self, export_id):
            state = super().get_claim_state(export_id)
            barrier.wait()
            return state

    def claim():
        with get_db() as session:
            return RacingStore(session).begin_run(export_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(decisions) == sorted(["run" if status == "pending" else "expired", "skip"])


def test_a_live_lease_is_not_taken_over(export_database):
    get_db, _observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))
    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "run"

    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "skip"


def test_an_expired_lease_fails_without_reexecution(export_database):
    """Expiry is not proof of process death; late success must not publish."""
    get_db, observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))
    stale = datetime.now(UTC) - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS + 60)
    with get_db() as session:
        session.execute(
            text(
                "UPDATE variant_exports SET status='running', started_at=:started_at "
                "WHERE id=:id"
            ),
            {"started_at": stale, "id": export_id},
        )

    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "expired"
    assert _status(observer, export_id)[0] == "failed"
    with get_db() as session:
        assert VariantExportStore(session).mark_succeeded(
            export_id, artifact_path="exports/late.tsv", record_count=1, file_size=2,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        ) is False
    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "skip"
    assert _status(observer, export_id)[1] is None


def test_expiration_does_not_overwrite_intervening_success(export_database):
    get_db, observer = export_database
    stale = datetime.now(UTC) - timedelta(seconds=EXPORT_CLAIM_LEASE_SECONDS + 60)
    export_id = _insert(get_db, str(uuid.uuid4()), status="running", started_at=stale)

    class FinishingStore(VariantExportStore):
        def get_claim_state(self, export_id):
            observed = super().get_claim_state(export_id)
            # The original attempt finishes after the duplicate's SELECT,
            # before its guarded expiry UPDATE.
            with get_db() as other:
                assert VariantExportStore(other).mark_succeeded(
                    export_id, artifact_path="exports/original.tsv", record_count=1,
                    file_size=2, expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            return observed

    with get_db() as session:
        assert FinishingStore(session).begin_run(export_id) == "skip"
    assert _status(observer, export_id)[0:2] == ("succeeded", "exports/original.tsv")


def test_a_missing_record_is_reported_instead_of_being_skipped(export_database):
    get_db, _observer = export_database
    with get_db() as session:
        assert VariantExportStore(session).begin_run(str(uuid.uuid4())) == "missing"


def test_a_failed_export_is_never_claimed_again(export_database):
    get_db, _observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()), status="failed")
    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "skip"


def test_a_finished_export_is_never_rebuilt(export_database):
    get_db, _observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()), status="succeeded")
    with get_db() as session:
        assert VariantExportStore(session).begin_run(export_id) == "skip"


def test_a_late_success_cannot_overwrite_a_failure(export_database):
    get_db, observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))
    with get_db() as session:
        store = VariantExportStore(session)
        assert store.begin_run(export_id) == "run"
    with get_db() as session:
        store = VariantExportStore(session)
        assert store.mark_failed(export_id, error="boom") is True
    with get_db() as session:
        store = VariantExportStore(session)
        assert (
            store.mark_succeeded(
                export_id,
                artifact_path="exports/x.tsv",
                record_count=1,
                file_size=2,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            is False
        )
    status, artifact_path, record_count, _updated = _status(observer, export_id)
    assert status == "failed"
    assert artifact_path is None
    assert record_count is None


def test_a_late_failure_cannot_overwrite_a_success(export_database):
    get_db, observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))
    with get_db() as session:
        store = VariantExportStore(session)
        assert store.begin_run(export_id) == "run"
    with get_db() as session:
        store = VariantExportStore(session)
        assert (
            store.mark_succeeded(
                export_id,
                artifact_path="exports/x.tsv",
                record_count=3,
                file_size=4,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            is True
        )
    with get_db() as session:
        store = VariantExportStore(session)
        assert store.mark_failed(export_id, error="late boom") is False
    status, artifact_path, record_count, _updated = _status(observer, export_id)
    assert status == "succeeded"
    assert artifact_path == "exports/x.tsv"
    assert record_count == 3


def test_store_roundtrips_shared_artifact_key(export_database):
    """Store and reload the shared key; this does not invoke API signing/S3."""
    get_db, observer = export_database
    export_id = _insert(get_db, str(uuid.uuid4()))
    filename = build_export_filename(export_id, "tsv", True)
    key = build_export_artifact_key(export_id, filename)

    with get_db() as session:
        store = VariantExportStore(session)
        assert store.begin_run(export_id) == "run"
    with get_db() as session:
        store = VariantExportStore(session)
        assert (
            store.mark_succeeded(
                export_id,
                artifact_path=key,
                record_count=7,
                file_size=8,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            is True
        )

    _status_value, artifact_path, _count, _updated = _status(observer, export_id)
    assert artifact_path == key
    assert artifact_path == f"exports/{export_id}/{filename}"


def test_the_worker_columns_exist_in_the_migrated_table(export_database):
    """Reflect executed migration DDL rather than matching source substrings."""
    _get_db, observer = export_database
    columns = {
        column["name"]: column for column in inspect(observer).get_columns("variant_exports")
    }
    assert set(variant_exports.c.keys()) <= columns.keys()
    assert columns["status"]["type"].enums == ["pending", "running", "succeeded", "failed"]
    assert columns["release_key"]["nullable"] is False
    assert columns["format"]["nullable"] is False
    assert "now()" in columns["updated_at"]["default"]


def test_migration_constraints_and_defaults_are_real(export_database):
    get_db, observer = export_database
    with pytest.raises(IntegrityError):
        with get_db() as session:
            session.execute(text("INSERT INTO variant_exports (id) VALUES (:id)"),
                            {"id": str(uuid.uuid4())})
    export_id = _insert(get_db, str(uuid.uuid4()))
    with observer.connect() as connection:
        row = connection.execute(
            text("SELECT compress, filters, created_at, updated_at "
                 "FROM variant_exports WHERE id=:id"), {"id": export_id},
        ).one()
    assert row.compress is True
    assert row.filters == {}
    assert row.created_at is not None
    assert row.updated_at is not None

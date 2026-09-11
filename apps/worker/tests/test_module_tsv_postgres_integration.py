"""Real PostgreSQL coverage for transactional module TSV batch imports.

The unit suite exercises parser and adapter contracts with fakes. With its
explicit opt-in environment gate this test starts PostgreSQL through
Testcontainers, upgrades the API's actual Alembic chain, then checks the 10k
batch boundary and transaction rollback against the worker's real database
driver/schema contract. CI always enables the gate; local unit runs stay fast.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from soymutdb_worker.tables import data_sets, module_data_rows
from soymutdb_worker.tasks.data_adapters import ImportContext, get_adapter

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
POSTGRES_INTEGRATION_ENV = "SOYMUTDB_RUN_POSTGRES_INTEGRATION"


def _upgrade_test_database(database_url: str) -> None:
    """Run the API-owned migration chain, failing with its real diagnostics."""
    environment = os.environ.copy()
    environment["SOYMUTDB_DATABASE_URL"] = database_url
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(API_ROOT), existing_pythonpath) if value
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
        pytest.fail(
            "Alembic upgrade for worker PostgreSQL integration failed:\n"
            f"{result.stderr[-4000:]}"
        )


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[object]:
    """Provide an Alembic-upgraded disposable PostgreSQL engine.

    The only skip is the explicit local opt-in gate. Once requested (as in
    CI), missing Testcontainers, Docker, an image pull, migration failure, or
    sync driver failure are all hard test failures rather than skip-green.

    When ``SOYMUTDB_TEST_DATABASE_URL`` is set (a ``postgresql+asyncpg://``
    URL, mirroring ``apps/api/tests/conftest.py``), it bypasses Testcontainers
    and targets that explicitly provisioned disposable PostgreSQL database.
    Callers must use a fresh fixture database per run: the suite asserts
    against the Alembic schema and commits seed data.
    """
    if os.environ.get(POSTGRES_INTEGRATION_ENV) != "1":
        pytest.skip(f"set {POSTGRES_INTEGRATION_ENV}=1 to run PostgreSQL integration")

    external_url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if external_url:
        if not external_url.startswith("postgresql+asyncpg://"):
            pytest.fail(
                "SOYMUTDB_TEST_DATABASE_URL must use the postgresql+asyncpg:// "
                "scheme"
            )
        async_url = external_url
        sync_url = (
            make_url(external_url)
            .set(drivername="postgresql+psycopg2")
            .render_as_string(hide_password=False)
        )
        _upgrade_test_database(async_url)
        engine = create_engine(sync_url)
        try:
            yield engine
        finally:
            engine.dispose()
        return

    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError as exc:
        pytest.fail(
            "testcontainers-postgres is required when "
            f"{POSTGRES_INTEGRATION_ENV}=1: {exc}"
        )

    container = PostgresContainer("postgres:16-alpine")
    engine = None
    try:
        container.start()
        sync_url = container.get_connection_url()
        async_url = make_url(sync_url).set(
            drivername="postgresql+asyncpg"
        ).render_as_string(hide_password=False)
        _upgrade_test_database(async_url)
        engine = create_engine(sync_url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        container.stop()


@pytest.fixture
def worker_session_factory(postgres_engine, monkeypatch):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)

    @contextmanager
    def test_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    from soymutdb_worker.utils import db as worker_db

    monkeypatch.setattr(worker_db, "get_db", test_get_db)
    return factory


def _write_genes(path, count: int, *, duplicate_final_row: bool = False) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("gene_id\tchromosome\tstart\tend\n")
        for index in range(count):
            start = index + 1
            handle.write(f"G{index}\tChr01\t{start}\t{start}\n")
        if duplicate_final_row:
            handle.write("G0\tChr01\t1\t1\n")


def _seed_dataset(session_factory, data_set_id: int, release_id: int) -> None:
    with session_factory.begin() as session:
        session.execute(
            data_sets.insert().values(
                id=data_set_id,
                type="module_tsv",
                release_id=release_id,
                status="uploading",
            )
        )


def _seed_release(session_factory, release_id: int, *, status: str = "draft") -> None:
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO releases (id, name, version, status) "
                "VALUES (:id, :name, :version, CAST(:status AS release_status_enum))"
            ),
            {
                "id": release_id,
                "name": f"Worker integration release {release_id}",
                "version": f"worker-integration-{release_id}",
                "status": status,
            },
        )


def _expected_alembic_head() -> str:
    """Derive the head from the real migration chain, not a pinned revision."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        pytest.fail("Alembic migration chain has no head revision")
    return head


def test_module_tsv_integration_schema_matches_release_and_uniqueness_contract(postgres_engine):
    """The worker must exercise the Alembic schema, not a look-alike Core DDL."""
    inspector = inspect(postgres_engine)

    assert inspector.has_table("alembic_version")
    with postgres_engine.connect() as connection:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one()
    assert revision == _expected_alembic_head()

    enum_labels = {item["name"]: item["labels"] for item in inspector.get_enums()}
    assert enum_labels["release_status_enum"] == [
        "draft",
        "validated",
        "ready",
        "published",
        "rolled_back",
    ]
    assert "ready" in enum_labels["import_status_enum"]

    data_set_columns = {
        column["name"]: column["type"] for column in inspector.get_columns("data_sets")
    }
    module_row_columns = {
        column["name"]: column["type"]
        for column in inspector.get_columns("module_data_rows")
    }
    assert isinstance(data_set_columns["source_objects"], JSONB)
    assert isinstance(data_set_columns["validation_evidence"], JSONB)
    assert isinstance(data_set_columns["manifest"], JSONB)
    assert isinstance(module_row_columns["data"], JSONB)

    foreign_keys = inspector.get_foreign_keys("module_data_rows")
    unique_constraints = inspector.get_unique_constraints("module_data_rows")

    assert any(
        foreign_key["referred_table"] == "releases"
        and foreign_key["constrained_columns"] == ["release_id"]
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in foreign_keys
    )
    assert any(
        constraint["name"] == "uq_module_data_rows_module_release_row"
        and constraint["column_names"] == ["module_key", "release_id", "row_key"]
        for constraint in unique_constraints
    )


def _module_row_count(session_factory, release_id: int) -> int:
    with session_factory() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(module_data_rows)
                .where(module_data_rows.c.module_key == "genes")
                .where(module_data_rows.c.release_id == release_id)
            ).scalar_one()
        )


def test_module_tsv_batches_persist_and_late_validation_failure_rolls_back(
    tmp_path,
    worker_session_factory,
):
    """A flush at row 10,000 is durable only if the entire input is valid."""
    good_path = tmp_path / "good-genes.tsv"
    bad_path = tmp_path / "bad-genes.tsv"
    _write_genes(good_path, 10_001)
    _write_genes(bad_path, 10_000, duplicate_final_row=True)
    _seed_release(worker_session_factory, release_id=1)
    _seed_release(worker_session_factory, release_id=2)
    _seed_dataset(worker_session_factory, data_set_id=1, release_id=1)
    _seed_dataset(worker_session_factory, data_set_id=2, release_id=2)

    good_result = get_adapter("module_tsv").run(
        ImportContext(
            import_task_id=1,
            data_set_id=1,
            release_id="1",
            file_key=str(good_path),
            module_key="genes",
            filename=good_path.name,
        )
    )

    assert good_result.inserted == 10_001
    assert good_result.evidence["batch_size"] == 10_000
    assert _module_row_count(worker_session_factory, release_id=1) == 10_001

    with pytest.raises(ValueError, match="duplicate_key"):
        get_adapter("module_tsv").run(
            ImportContext(
                import_task_id=2,
                data_set_id=2,
                release_id="2",
                file_key=str(bad_path),
                module_key="genes",
                filename=bad_path.name,
            )
        )

    # The second import had already flushed 10,000 rows before its duplicate
    # was parsed. PostgreSQL rollback must nevertheless leave release 2 empty.
    assert _module_row_count(worker_session_factory, release_id=2) == 0


def test_module_tsv_rejects_non_draft_release_without_deleting_existing_rows(
    tmp_path,
    worker_session_factory,
):
    """The status lock protects releases that changed after API command creation."""
    source = tmp_path / "published-genes.tsv"
    _write_genes(source, 1)
    _seed_release(worker_session_factory, release_id=3, status="published")
    _seed_dataset(worker_session_factory, data_set_id=3, release_id=3)
    with worker_session_factory.begin() as session:
        session.execute(
            module_data_rows.insert().values(
                id=uuid.uuid4(),
                module_key="genes",
                release_id=3,
                row_key="existing",
                data={"gene_id": "existing"},
            )
        )

    with pytest.raises(ValueError, match="draft release"):
        get_adapter("module_tsv").run(
            ImportContext(
                import_task_id=3,
                data_set_id=3,
                release_id="3",
                file_key=str(source),
                module_key="genes",
                filename=source.name,
            )
        )

    assert _module_row_count(worker_session_factory, release_id=3) == 1

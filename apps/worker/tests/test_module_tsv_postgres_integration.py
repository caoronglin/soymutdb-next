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


def _seed_release(session_factory, release_id: int, *, status: str = "draft") -> int:
    """Insert a release plus its canonical assembly; returns the assembly id.

    ADR-0004 promotion resolves the release's assembly, so every release
    fixture needs one; `releases.assembly_id` pins it explicitly.
    """
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
        assembly_id = session.execute(
            text(
                "INSERT INTO assemblies (name, version, release_id, species) "
                "VALUES (:name, :version, :release_id, 'Glycine max') RETURNING id"
            ),
            {
                "name": f"Worker assembly {release_id}",
                "version": f"asm-{release_id}",
                "release_id": release_id,
            },
        ).scalar_one()
        session.execute(
            text("UPDATE releases SET assembly_id = :assembly_id WHERE id = :id"),
            {"assembly_id": assembly_id, "id": release_id},
        )
    return int(assembly_id)


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


def _canonical_genes(session_factory, *, assembly_id: int) -> list[tuple]:
    with session_factory() as session:
        return list(
            session.execute(
                text(
                    'SELECT accession, chromosome_id, start, "end", strand, biotype, '
                    "attributes FROM genes WHERE assembly_id = :assembly_id "
                    "ORDER BY accession"
                ),
                {"assembly_id": assembly_id},
            ).all()
        )


def _canonical_chromosomes(session_factory, *, assembly_id: int) -> list[tuple]:
    with session_factory() as session:
        return list(
            session.execute(
                text(
                    'SELECT name, length, "order" FROM chromosomes '
                    'WHERE assembly_id = :assembly_id ORDER BY "order", name'
                ),
                {"assembly_id": assembly_id},
            ).all()
        )


def _write_promotion_genes(path, rows: list[tuple[str, str, int, int, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("gene_id\tchromosome\tstart\tend\tmutation_feature\n")
        for gene_id, chromosome, start, end, mutation_feature in rows:
            handle.write(f"{gene_id}\t{chromosome}\t{start}\t{end}\t{mutation_feature}\n")


def test_genes_import_promotes_into_canonical_genes_and_chromosomes(
    tmp_path, worker_session_factory
):
    """ADR-0004: staged module rows reach the canonical read tables."""
    source = tmp_path / "promote-genes.tsv"
    _write_promotion_genes(
        source,
        [
            ("G1", "Chr01", 100, 200, "EMS"),
            ("G2", "Chr01", 300, 500, ""),
            ("G3", "Chr02", 50, 90, ""),
        ],
    )
    assembly_id = _seed_release(worker_session_factory, release_id=10)
    _seed_dataset(worker_session_factory, data_set_id=10, release_id=10)

    result = get_adapter("module_tsv").run(
        ImportContext(
            import_task_id=10,
            data_set_id=10,
            release_id="10",
            file_key=str(source),
            module_key="genes",
            filename=source.name,
        )
    )

    assert result.inserted == 3
    promotion = result.evidence["promotion"]
    assert promotion["target"] == "genes"
    assert promotion["promoted_rows"] == 3
    assert promotion["chromosomes_created"] == 2

    genes = _canonical_genes(worker_session_factory, assembly_id=assembly_id)
    assert [row[0] for row in genes] == ["G1", "G2", "G3"]
    first = genes[0]
    assert first[2] == 100 and first[3] == 200
    assert first[4] == "+" and first[5] == "protein_coding"
    assert first[6] == {"mutation_feature": "EMS"}
    # Provisional chromosome length = the longest observed gene end.
    assert [(row[0], row[1]) for row in _canonical_chromosomes(
        worker_session_factory, assembly_id=assembly_id
    )] == [("Chr01", 500), ("Chr02", 90)]


def test_genes_promotion_is_idempotent_and_updates_coordinates(
    tmp_path, worker_session_factory
):
    """A re-import replaces the snapshot: upserts update, missing genes go."""
    first_source = tmp_path / "promote-first.tsv"
    second_source = tmp_path / "promote-second.tsv"
    _write_promotion_genes(
        first_source,
        [("G1", "Chr01", 100, 200, ""), ("G2", "Chr01", 300, 400, "")],
    )
    # The second snapshot keeps G1 with new coordinates and drops G2 entirely.
    _write_promotion_genes(second_source, [("G1", "Chr01", 150, 500, "")])
    assembly_id = _seed_release(worker_session_factory, release_id=11)
    _seed_dataset(worker_session_factory, data_set_id=11, release_id=11)

    for index, source in enumerate((first_source, second_source)):
        result = get_adapter("module_tsv").run(
            ImportContext(
                import_task_id=11 + index,
                data_set_id=11,
                release_id="11",
                file_key=str(source),
                module_key="genes",
                filename=source.name,
            )
        )
    assert result.evidence["promotion"]["genes_removed"] == 1

    genes = _canonical_genes(worker_session_factory, assembly_id=assembly_id)
    assert [row[0] for row in genes] == ["G1"]
    assert genes[0][2] == 150 and genes[0][3] == 500
    # Staging is replaced by the retry as well, not appended to.
    assert _module_row_count(worker_session_factory, release_id=11) == 1


def test_genes_import_without_assembly_fails_closed(tmp_path, worker_session_factory):
    """Promotion cannot guess an assembly; the whole import rolls back."""
    source = tmp_path / "no-assembly.tsv"
    _write_promotion_genes(source, [("G1", "Chr01", 100, 200, "")])
    with worker_session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO releases (id, name, version, status) "
                "VALUES (12, 'release without assembly', 'no-asm-12', "
                "CAST('draft' AS release_status_enum))"
            )
        )
    _seed_dataset(worker_session_factory, data_set_id=12, release_id=12)

    with pytest.raises(RuntimeError, match="has no assembly"):
        get_adapter("module_tsv").run(
            ImportContext(
                import_task_id=12,
                data_set_id=12,
                release_id="12",
                file_key=str(source),
                module_key="genes",
                filename=source.name,
            )
        )

    # The staging write rolled back with the promotion failure.
    assert _module_row_count(worker_session_factory, release_id=12) == 0


def test_unmapped_module_key_is_rejected_by_promotion(worker_session_factory) -> None:
    from soymutdb_worker.tasks.module_promotion import PromotionError, promote_module_rows

    _seed_release(worker_session_factory, release_id=13)
    with worker_session_factory() as session:
        with pytest.raises(PromotionError, match="no canonical promotion target"):
            promote_module_rows(session, module_key="pathways", release_id=13)


def test_promoted_genes_follow_portal_release_visibility(
    tmp_path, worker_session_factory
):
    """Promoted genes are joined through assemblies.release_id like the portal.

    `ReleaseContext` resolves only PUBLISHED releases, and `GeneService` joins
    genes via `Assembly.release_id`. This mirrors both conditions: a draft
    release's promoted rows are invisible, publishing the release exposes them.
    """
    source = tmp_path / "visibility-genes.tsv"
    _write_promotion_genes(source, [("G1", "Chr01", 100, 200, "")])
    assembly_id = _seed_release(worker_session_factory, release_id=14)
    _seed_dataset(worker_session_factory, data_set_id=14, release_id=14)
    get_adapter("module_tsv").run(
        ImportContext(
            import_task_id=14,
            data_set_id=14,
            release_id="14",
            file_key=str(source),
            module_key="genes",
            filename=source.name,
        )
    )

    def portal_rows(session) -> list[str]:
        return [
            str(row[0])
            for row in session.execute(
                text(
                    "SELECT g.accession FROM genes g "
                    "JOIN assemblies a ON g.assembly_id = a.id "
                    "JOIN releases r ON a.release_id = r.id "
                    "WHERE a.release_id = :release_id "
                    "AND r.status::text = 'published' "
                    "AND g.accession = 'G1'"
                ),
                {"release_id": 14},
            ).all()
        ]

    with worker_session_factory() as session:
        assert portal_rows(session) == []
        session.execute(
            text(
                "UPDATE releases SET status = "
                "CAST('published' AS release_status_enum) WHERE id = 14"
            )
        )
        session.commit()
        assert portal_rows(session) == ["G1"]
    assert _canonical_genes(worker_session_factory, assembly_id=assembly_id)


def test_promotion_failure_rolls_back_earlier_batches(
    tmp_path, worker_session_factory
):
    """A failure after some rows were promoted must not commit partial state.

    Promotion upserts in batches of 5,000. The first batch here succeeds and
    the second fails at the database level (a chromosome name longer than
    chromosomes.name(64)); the whole import must roll back, leaving neither
    canonical genes nor staging rows and keeping the data set out of `ready`.
    """
    source = tmp_path / "late-promotion-failure.tsv"
    rows = [(f"G{index:04d}", "Chr01", index + 1, index + 100, "") for index in range(5000)]
    # Sorts last by row_key, so it lands in the second batch.
    rows.append(("ZZZ", "X" * 80, 1_000_000, 1_000_100, ""))
    _write_promotion_genes(source, rows)
    assembly_id = _seed_release(worker_session_factory, release_id=15)
    _seed_dataset(worker_session_factory, data_set_id=15, release_id=15)

    with pytest.raises(Exception) as raised:  # noqa: B017 - driver exception type
        get_adapter("module_tsv").run(
            ImportContext(
                import_task_id=15,
                data_set_id=15,
                release_id="15",
                file_key=str(source),
                module_key="genes",
                filename=source.name,
            )
        )
    assert "too long" in str(raised.value) or "value too long" in str(raised.value)

    # Nothing from either batch survived: canonical genes, chromosomes, staging
    # and the data set status are all rolled back together.
    assert _canonical_genes(worker_session_factory, assembly_id=assembly_id) == []
    assert _canonical_chromosomes(worker_session_factory, assembly_id=assembly_id) == []
    assert _module_row_count(worker_session_factory, release_id=15) == 0
    with worker_session_factory() as session:
        status = session.execute(
            text("SELECT status FROM data_sets WHERE id = 15")
        ).scalar_one()
    assert status != "ready"


def test_concurrent_imports_for_the_same_release_serialize(
    tmp_path, worker_session_factory
):
    """Two workers importing the same release must not interleave.

    The adapter locks `releases.status` FOR UPDATE, so the second import waits
    for the first instead of deleting/rewriting staging underneath it. The final
    staging and canonical rows must equal exactly one of the two inputs — a
    mixture (or a duplicate-key crash) would mean the lock is not doing its job.
    """
    import threading

    first = tmp_path / "concurrent-first.tsv"
    second = tmp_path / "concurrent-second.tsv"
    _write_promotion_genes(first, [("G1", "Chr01", 10, 20, ""), ("G2", "Chr01", 30, 40, "")])
    _write_promotion_genes(
        second,
        [
            ("G3", "Chr02", 50, 60, ""),
            ("G4", "Chr02", 70, 80, ""),
            ("G5", "Chr02", 90, 100, ""),
        ],
    )
    assembly_id = _seed_release(worker_session_factory, release_id=16)
    _seed_dataset(worker_session_factory, data_set_id=16, release_id=16)

    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def run_import(source: Path, task_id: int) -> None:
        try:
            barrier.wait(timeout=10)
            get_adapter("module_tsv").run(
                ImportContext(
                    import_task_id=task_id,
                    data_set_id=16,
                    release_id="16",
                    file_key=str(source),
                    module_key="genes",
                    filename=source.name,
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [
        threading.Thread(target=run_import, args=(first, 16)),
        threading.Thread(target=run_import, args=(second, 17)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "imports did not finish"
    assert errors == []

    with worker_session_factory() as session:
        row_keys = [
            str(row[0])
            for row in session.execute(
                text(
                    "SELECT row_key FROM module_data_rows "
                    "WHERE module_key = 'genes' AND release_id = 16 ORDER BY row_key"
                )
            ).all()
        ]
    accessions = sorted(row[0] for row in _canonical_genes(
        worker_session_factory, assembly_id=assembly_id
    ))
    # Exactly one import owns the final state; the other's rows are gone.
    assert len(row_keys) == len(set(row_keys))
    assert accessions in (["G1", "G2"], ["G3", "G4", "G5"])


def test_empty_staging_does_not_delete_canonical_genes(worker_session_factory):
    """An empty snapshot is not a delete instruction (ADR-0004 rule)."""
    from soymutdb_worker.tasks.module_promotion import promote_module_rows

    assembly_id = _seed_release(worker_session_factory, release_id=17)
    with worker_session_factory.begin() as session:
        chromosome_id = session.execute(
            text(
                'INSERT INTO chromosomes (assembly_id, name, length, "order") '
                "VALUES (:assembly_id, 'Chr01', 500, 0) RETURNING id"
            ),
            {"assembly_id": assembly_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO genes (accession, assembly_id, chromosome_id, start, "
                '"end", strand, biotype) '
                "VALUES ('KEEP', :assembly_id, :chromosome_id, 1, 10, '+', "
                "'protein_coding')"
            ),
            {"assembly_id": assembly_id, "chromosome_id": chromosome_id},
        )

    with worker_session_factory() as session:
        result = promote_module_rows(session, module_key="genes", release_id=17)
        session.commit()

    assert result.promoted_rows == 0
    assert result.genes_removed == 0
    assert [
        row[0]
        for row in _canonical_genes(worker_session_factory, assembly_id=assembly_id)
    ] == ["KEEP"]

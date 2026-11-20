"""Real PostgreSQL coverage for the expression/homolog CSV writers.

The unit suite fakes the session. With the explicit opt-in gate this suite
starts PostgreSQL (or uses ``SOYMUTDB_TEST_DATABASE_URL``), upgrades the API's
Alembic chain, and exercises the real constraints: assembly-scoped gene
resolution, ``ON CONFLICT`` idempotency, and whole-import rollback.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from soymutdb_worker.tables import data_sets, expression_data, gene_homologs
from soymutdb_worker.tasks.data_adapters import ImportContext, get_adapter

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
POSTGRES_INTEGRATION_ENV = "SOYMUTDB_RUN_POSTGRES_INTEGRATION"


def _upgrade_test_database(database_url: str) -> None:
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
    if os.environ.get(POSTGRES_INTEGRATION_ENV) != "1":
        pytest.skip(f"set {POSTGRES_INTEGRATION_ENV}=1 to run PostgreSQL integration")

    external_url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if external_url:
        if not external_url.startswith("postgresql+asyncpg://"):
            pytest.fail(
                "SOYMUTDB_TEST_DATABASE_URL must use the postgresql+asyncpg:// scheme"
            )
        sync_url = (
            make_url(external_url)
            .set(drivername="postgresql+psycopg2")
            .render_as_string(hide_password=False)
        )
        _upgrade_test_database(external_url)
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

    container = PostgresContainer("postgres:18.6-alpine")
    engine = None
    try:
        container.start()
        sync_url = container.get_connection_url()
        async_url = (
            make_url(sync_url)
            .set(drivername="postgresql+asyncpg")
            .render_as_string(hide_password=False)
        )
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


@pytest.fixture(autouse=True)
def _clean_shared_database(worker_session_factory) -> Iterator[None]:
    """Leave the shared test database empty for the next test module."""
    _reset(worker_session_factory)
    try:
        yield
    finally:
        _reset(worker_session_factory)


def _reset(session_factory) -> None:
    with session_factory.begin() as session:
        session.execute(text("DELETE FROM gene_homologs"))
        session.execute(text("DELETE FROM expression_data"))
        session.execute(text("DELETE FROM expression_libraries"))
        session.execute(text("DELETE FROM genes"))
        session.execute(text("DELETE FROM chromosomes"))
        session.execute(text("DELETE FROM data_sets"))
        session.execute(text("DELETE FROM assemblies"))
        session.execute(text("DELETE FROM releases"))


def _seed_scope(session_factory) -> dict[str, int]:
    """Two assemblies sharing accession G1; libraries in each assembly."""
    with session_factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO releases (id, name, version, status) "
                "VALUES (1, 'CSV release', 'csv-r1', "
                "CAST('draft' AS release_status_enum))"
            )
        )
        assembly_ids: dict[str, int] = {}
        for assembly_id, label in ((11, "v4"), (12, "v5")):
            session.execute(
                text(
                    "INSERT INTO assemblies (id, name, version, release_id, species) "
                    "VALUES (:id, :label, :label, 1, 'Glycine max')"
                ),
                {"id": assembly_id, "label": label},
            )
            assembly_ids[label] = assembly_id
        chromosome_ids: dict[str, int] = {}
        for index, label in enumerate(("v4", "v5"), start=1):
            chromosome_ids[label] = session.execute(
                text(
                    "INSERT INTO chromosomes (assembly_id, name, length, \"order\") "
                    "VALUES (:assembly_id, 'Chr01', 50000000, 1) RETURNING id"
                ),
                {"assembly_id": assembly_ids[label]},
            ).scalar_one()
        gene_pks: dict[str, int] = {}
        for label in ("v4", "v5"):
            gene_pks[label] = session.execute(
                text(
                    "INSERT INTO genes "
                    "(accession, assembly_id, chromosome_id, start, \"end\", strand) "
                    "VALUES ('G1', :assembly_id, :chromosome_id, 1, 100, '+') "
                    "RETURNING gene_pk"
                ),
                {
                    "assembly_id": assembly_ids[label],
                    "chromosome_id": chromosome_ids[label],
                },
            ).scalar_one()
        library_ids: dict[str, int] = {}
        for label in ("v4", "v5"):
            library_ids[label] = session.execute(
                text(
                    "INSERT INTO expression_libraries "
                    "(sample_id, library_name, tissue, treatment, assembly_id) "
                    "VALUES (:sample_id, :library_name, "
                    "CAST('leaf' AS expression_tissue_enum), "
                    "CAST('control' AS expression_treatment_enum), :assembly_id) "
                    "RETURNING id"
                ),
                {
                    "sample_id": f"sample-{label}",
                    "library_name": f"library-{label}",
                    "assembly_id": assembly_ids[label],
                },
            ).scalar_one()
    return {
        "v4_assembly": assembly_ids["v4"],
        "v5_assembly": assembly_ids["v5"],
        "v4_gene": gene_pks["v4"],
        "v5_gene": gene_pks["v5"],
        "v4_library": library_ids["v4"],
        "v5_library": library_ids["v5"],
    }


def _seed_dataset(session_factory, *, data_set_id: int, kind: str) -> None:
    with session_factory.begin() as session:
        session.execute(
            data_sets.insert().values(
                id=data_set_id, type=kind, release_id=1, status="uploading"
            )
        )


def _count(session_factory, table, **filters) -> int:
    with session_factory() as session:
        statement = select(func.count()).select_from(table)
        for name, value in filters.items():
            statement = statement.where(table.c[name] == value)
        return int(session.execute(statement).scalar_one())


def test_expression_csv_upserts_rows_scoped_to_the_requested_assembly(
    tmp_path, worker_session_factory
):
    _reset(worker_session_factory)
    scope = _seed_scope(worker_session_factory)
    _seed_dataset(worker_session_factory, data_set_id=1, kind="expression_csv")
    source = tmp_path / "expression.csv"
    source.write_text(
        "gene_id,library_id,fpkm,tpm,raw_count\n"
        f"G1,{scope['v5_library']},1.5,2.5,10\n"
        f"G1,{scope['v5_library']},1.7,2.7,11\n"
    )

    result = get_adapter("expression_csv").run(
        ImportContext(
            import_task_id=1,
            data_set_id=1,
            release_id="1",
            file_key=str(source),
            assembly="v5",
            filename=source.name,
        )
    )

    assert result.inserted == 1
    assert result.evidence["rows_seen"] == 2
    assert result.evidence["rows_duplicate"] == 1
    assert _count(worker_session_factory, expression_data) == 1
    assert (
        _count(
            worker_session_factory,
            expression_data,
            gene_id=scope["v5_gene"],
            library_id=scope["v5_library"],
        )
        == 1
    )
    with worker_session_factory() as session:
        row = session.execute(select(expression_data)).one()
        assert row.fpkm == 1.7
        assert row.raw_count == 11
        status = session.execute(
            select(data_sets.c.status).where(data_sets.c.id == 1)
        ).scalar_one()
        assert status == "ready"

    # A second delivery of the same file is idempotent, not a duplicate insert.
    rerun = get_adapter("expression_csv").run(
        ImportContext(
            import_task_id=1,
            data_set_id=1,
            release_id="1",
            file_key=str(source),
            assembly="v5",
            filename=source.name,
        )
    )
    assert rerun.inserted == 1
    assert _count(worker_session_factory, expression_data) == 1


def test_expression_csv_rejects_a_library_from_another_assembly_and_rolls_back(
    tmp_path, worker_session_factory
):
    _reset(worker_session_factory)
    scope = _seed_scope(worker_session_factory)
    _seed_dataset(worker_session_factory, data_set_id=1, kind="expression_csv")
    source = tmp_path / "expression.csv"
    source.write_text(
        "gene_id,library_id,fpkm\n"
        f"G1,{scope['v5_library']},1.5\n"
        f"G1,{scope['v4_library']},1.5\n"
    )

    with pytest.raises(ValueError, match="belongs to another assembly"):
        get_adapter("expression_csv").run(
            ImportContext(
                import_task_id=1,
                data_set_id=1,
                release_id="1",
                file_key=str(source),
                assembly="v5",
                filename=source.name,
            )
        )

    # The valid row was already upserted before the bad row was parsed; the
    # single transaction must roll it back.
    assert _count(worker_session_factory, expression_data) == 0


def test_expression_csv_rejects_an_unknown_assembly_loudly(
    tmp_path, worker_session_factory
):
    _reset(worker_session_factory)
    _seed_scope(worker_session_factory)
    _seed_dataset(worker_session_factory, data_set_id=1, kind="expression_csv")
    source = tmp_path / "expression.csv"
    source.write_text("gene_id,library_id,fpkm\nG1,1,1.0\n")

    with pytest.raises(RuntimeError, match="unknown assembly 'v6'"):
        get_adapter("expression_csv").run(
            ImportContext(
                import_task_id=1,
                data_set_id=1,
                release_id="1",
                file_key=str(source),
                assembly="v6",
                filename=source.name,
            )
        )


def test_homolog_csv_upserts_by_natural_key(tmp_path, worker_session_factory):
    _reset(worker_session_factory)
    scope = _seed_scope(worker_session_factory)
    _seed_dataset(worker_session_factory, data_set_id=1, kind="homolog_csv")
    source = tmp_path / "homolog.csv"
    source.write_text(
        "gene_id,homolog_species,homolog_gene_id,homolog_type,source\n"
        "G1,Glycine soja,GS01,ortholog,phytozome\n"
        "G1,Glycine soja,GS01,ORTHOLOG,phytozome-v2\n"
    )

    result = get_adapter("homolog_csv").run(
        ImportContext(
            import_task_id=1,
            data_set_id=1,
            release_id="1",
            file_key=str(source),
            assembly="v5",
            filename=source.name,
        )
    )

    assert result.inserted == 1
    assert result.evidence["rows_duplicate"] == 1
    assert _count(worker_session_factory, gene_homologs) == 1
    with worker_session_factory() as session:
        row = session.execute(select(gene_homologs)).one()
        assert row.gene_id == scope["v5_gene"]
        assert row.homolog_type == "ortholog"
        assert row.source == "phytozome-v2"

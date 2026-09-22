"""P2-3 import_vcf wiring: flag gating, VCF row extraction, end-to-end protocol.

The end-to-end test drives the protocol-driven import against REAL PostgreSQL
(the manifest + release/assembly resolution) and REAL embedded ClickHouse (the
fact/summary schema), gated on ``SOYMUTDB_RUN_POSTGRES_INTEGRATION`` +
``SOYMUTDB_TEST_DATABASE_URL``. The flag defaults OFF, so a bare run reproduces
the fail-closed behaviour (no publish); the gated run proves the ON path.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import chdb.session  # noqa: F401  (hard dep: acceptance engine lives in worker[dev])
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from soymutdb_worker.tasks import ingest
from soymutdb_worker.tasks.clickhouse_engine import ChdbEngine
from soymutdb_worker.tasks.data_adapters import UnsupportedImportError
from soymutdb_worker.tasks.ingest import compute_variant_id
from soymutdb_worker.tasks.variant_finalize import BASE_COLUMNS
from tests.chdb_harness import prepare_schema, session_path, unique_db

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps" / "api"
GATE = "SOYMUTDB_RUN_POSTGRES_INTEGRATION"

_SCHEMA = (
    Path(__file__).parent / "fixtures" / "variant_facts_schema.sql"
).read_text(encoding="utf-8")
_STATEMENTS = [s.strip() for s in _SCHEMA.split(";") if s.strip()]


def _vcf_text() -> str:
    cols = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", "sample1"]
    header = "\n".join(
        [
            "##fileformat=VCFv4.2",
            "##contig=<ID=Chr01,length=100000>",
            "\t".join(cols),
        ]
    )
    ann1 = (
        "ANN=G|missense_variant|MODERATE|Glyma.01G000100|Glyma.01G000100"
        "|transcript|tx1|protein_coding|1/1000|c.1A>G|p.Met1Val|1/1000"
    )
    ann2 = (
        "ANN=T|synonymous_variant|LOW|Glyma.01G000100|Glyma.01G000100"
        "|transcript|tx1|protein_coding|1/900|c.2C>T|p.Ser2Ser|1/900"
    )
    row1 = "\t".join(["Chr01", "100", ".", "A", "G", "50", "PASS", ann1, "GT", "0/1"])
    row2 = "\t".join(["Chr01", "200", ".", "C", "T", "60", "PASS", ann2, "GT", "0/1"])
    return "\n".join([header, row1, row2]) + "\n"


def _write_vcf(tmp_path: Path) -> str:
    path = tmp_path / "tiny.vcf"
    path.write_text(_vcf_text(), encoding="utf-8")
    return str(path)


def test_import_vcf_fails_closed_when_flag_off(monkeypatch) -> None:
    monkeypatch.delenv("SOYMUTDB_ENABLE_VCF_IMPORT", raising=False)
    with pytest.raises(UnsupportedImportError):
        ingest.import_vcf("REL", "some/object.vcf", "asm-v5")


def test_vcf_rows_are_extracted_in_canonical_order(tmp_path: Path) -> None:
    rows = list(
        ingest._iter_vcf_base_rows(_write_vcf(tmp_path), "REL", "asm-v5", "fk")
    )
    assert len(rows) == 2
    for row in rows:
        assert len(row) == len(BASE_COLUMNS)
        index = BASE_COLUMNS.index
        assert row[index("release_key")] == "REL"
        assert row[index("assembly_key")] == "asm-v5"
    first_variant_id = compute_variant_id("REL", "fk", "Chr01", 100, "A", "G")
    assert rows[0][BASE_COLUMNS.index("variant_id")] == first_variant_id


@pytest.fixture(scope="module")
def pg() -> dict:
    if os.environ.get(GATE) != "1":
        pytest.skip(f"set {GATE}=1 to run PostgreSQL integration")
    url = os.environ.get("SOYMUTDB_TEST_DATABASE_URL")
    if not url:
        pytest.fail(f"{GATE}=1 requires SOYMUTDB_TEST_DATABASE_URL here")
    sync_url = make_url(url).set(drivername="postgresql+psycopg2").render_as_string(
        hide_password=False
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=API_ROOT,
        env={**os.environ, "SOYMUTDB_DATABASE_URL": url, "PYTHONPATH": str(API_ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )
    yield {"sync_url": sync_url}


def test_protocol_driven_import_end_to_end(
    pg: dict, tmp_path: Path, monkeypatch
) -> None:
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(pg["sync_url"])
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    run = uuid.uuid4().hex
    release_version = f"rel-{run}"
    assembly_name = f"asm-{run}"
    from sqlalchemy import text

    with factory() as session:
        release_id = session.execute(
            text(
                "INSERT INTO releases (name, version, status) "
                "VALUES (:n, :v, 'draft') RETURNING id"
            ),
            {"n": release_version, "v": release_version},
        ).scalar_one()
        assembly_id = session.execute(
            text("INSERT INTO assemblies (name, version) VALUES (:n, :v) RETURNING id"),
            {"n": assembly_name, "v": f"{assembly_name}-Wm82"},
        ).scalar_one()
        session.commit()

    @contextmanager
    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(ingest, "get_db", _db)

    clickhouse = ChdbEngine.open(session_path())
    prepare_schema(clickhouse, unique_db(), _STATEMENTS)

    source_sha256 = uuid.uuid4().hex  # any 64-hex; distinct per run
    result = ingest._import_vcf_via_protocol(
        clickhouse,
        release_id=release_version,
        assembly_key=assembly_name,
        local_vcf_path=_write_vcf(tmp_path),
        file_key=f"fk-{run}",
        batch_size=1000,
        source_sha256=source_sha256,
        release_id_int=release_id,
        assembly_id_int=assembly_id,
    )
    assert result["status"] == "published"
    assert clickhouse.scalar("SELECT count() FROM variant_facts") == 2
    assert (
        clickhouse.scalar(
            "SELECT sum(cnt) FROM gene_impact_summary FINAL "
            f"WHERE release_key = '{release_version}'"
        )
        == 2
    )
    # Recalled input -> idempotent: the same fingerprint does not re-publish.
    again = ingest._import_vcf_via_protocol(
        clickhouse,
        release_id=release_version,
        assembly_key=assembly_name,
        local_vcf_path=_write_vcf(tmp_path),
        file_key=f"fk-{run}",
        batch_size=1000,
        source_sha256=source_sha256,
        release_id_int=release_id,
        assembly_id_int=assembly_id,
    )
    assert again["idempotent"] is True
    assert clickhouse.scalar("SELECT count() FROM variant_facts") == 2
    engine.dispose()

import os
import time
from contextlib import contextmanager, nullcontext
from dataclasses import replace

import pytest

from soymutdb_worker.tasks.data_adapters import (
    ImportContext,
    get_adapter,
    registered_kinds,
)


class _BoundedReadStream:
    """Network-like source that rejects whole-file ``read()`` calls."""

    def __init__(self, data: bytes, *, chunk_size: int = 13) -> None:
        self._data = data
        self._chunk_size = chunk_size
        self._offset = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "streaming import must never request an unbounded read"
        self.read_sizes.append(size)
        if self._offset >= len(self._data):
            return b""
        end = min(self._offset + min(size, self._chunk_size), len(self._data))
        chunk = self._data[self._offset : end]
        self._offset = end
        return chunk

    def close(self) -> None:
        self.closed = True


class _GeneratedGenesTsvStream:
    """Produce a large valid TSV without allocating its complete source fixture."""

    def __init__(self, rows: int) -> None:
        self._rows = rows
        self._next_row = -1
        self._pending = b""
        self.read_sizes: list[int] = []
        self._read_calls = 0
        self.initial_rss_bytes = _current_rss_bytes()
        self.peak_rss_bytes = self.initial_rss_bytes

    def read(self, size: int = -1) -> bytes:
        assert size > 0, "streaming validation must never request the complete source"
        self.read_sizes.append(size)
        self._read_calls += 1
        if self._read_calls % 16 == 0:
            self.peak_rss_bytes = max(self.peak_rss_bytes, _current_rss_bytes())
        output = bytearray()
        while len(output) < size:
            if not self._pending:
                if self._next_row == -1:
                    self._pending = b"gene_id\tchromosome\tstart\tend\n"
                    self._next_row = 0
                elif self._next_row < self._rows:
                    # Keep the 2M tier below the separate 50 MiB source-file
                    # safety cap while still exercising every required column
                    # and unique-key validation path.
                    self._pending = f"G{self._next_row}\tC\t1\t1\n".encode()
                    self._next_row += 1
                else:
                    break
            take = min(size - len(output), len(self._pending))
            output.extend(self._pending[:take])
            self._pending = self._pending[take:]
        self.peak_rss_bytes = max(self.peak_rss_bytes, _current_rss_bytes())
        return bytes(output)


def _current_rss_bytes() -> int:
    """Read current resident memory without adding a profiling dependency."""
    try:
        with open("/proc/self/status", encoding="utf-8") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


@pytest.mark.parametrize(
    "kind",
    [
        "fasta",
        "gff3",
        "vcf",
        "blast_db",
        "seed_data",
        "expression_csv",
        "homolog_csv",
        "module_tsv",
    ],
)
def test_all_approved_types_are_registered(kind):
    assert get_adapter(kind).kind == kind


def test_registry_contains_only_approved_types():
    assert registered_kinds() == (
        "blast_db",
        "expression_csv",
        "fasta",
        "gff3",
        "homolog_csv",
        "module_tsv",
        "seed_data",
        "vcf",
    )


@pytest.mark.parametrize("kind", ["fasta", "gff3", "vcf", "blast_db"])
def test_adapter_without_durable_writer_fails_closed(kind, tmp_path):
    path = tmp_path / f"input-{kind}.txt"
    path.write_text(">chr1\nACGT\n")

    with pytest.raises(
        RuntimeError,
        match=rf"{kind} import is disabled.*durable persistence",
    ):
        get_adapter(kind).run(ImportContext(1, 2, "r1", str(path), "a1"))


@pytest.mark.parametrize("kind", ["seed_data", "expression_csv", "homolog_csv"])
def test_csv_adapter_without_writer_fails_closed(kind, tmp_path):
    path = tmp_path / f"{kind}.csv"
    path.write_text("id,value\n1,example\n")

    with pytest.raises(RuntimeError, match=rf"{kind} import is disabled.*persistence writer"):
        get_adapter(kind).run(ImportContext(1, 2, "r1", str(path)))


@pytest.mark.parametrize("kind", ["seed_data", "expression_csv", "homolog_csv"])
def test_import_task_marks_csv_without_writer_failed_not_ready(kind, tmp_path, monkeypatch):
    from soymutdb_worker.tasks import ingest

    path = tmp_path / f"{kind}.csv"
    path.write_text("id,value\n1,example\n")
    updates = []
    monkeypatch.setattr(
        ingest,
        "update_import_progress",
        lambda import_task_id, **values: updates.append((import_task_id, values)),
    )
    monkeypatch.setattr(
        ingest,
        "import_execution_guard",
        lambda import_task_id: nullcontext(True),
    )

    with pytest.raises(RuntimeError, match=rf"{kind} import is disabled.*persistence writer"):
        ingest.run_import_adapter.run(1, 2, kind, "r1", str(path))

    status_updates = [values for _, values in updates if "status" in values]
    assert [values["status"] for values in status_updates] == ["ingesting", "failed"]
    assert "persistence writer" in status_updates[-1]["error_detail"]


def test_duplicate_import_delivery_is_skipped_before_adapter_execution(monkeypatch):
    from soymutdb_worker.tasks import ingest

    monkeypatch.setattr(
        ingest,
        "import_execution_guard",
        lambda import_task_id: nullcontext(False),
    )
    monkeypatch.setattr(
        ingest,
        "get_adapter",
        lambda kind: pytest.fail("duplicate delivery must not execute an adapter"),
    )
    monkeypatch.setattr(
        ingest,
        "update_import_progress",
        lambda *args, **kwargs: pytest.fail("duplicate delivery must not change state"),
    )

    result = ingest.run_import_adapter.run(1, 2, "vcf", "r1", "input.vcf")

    assert result == {
        "import_task_id": 1,
        "skipped": True,
        "reason": "duplicate_or_completed",
    }


def test_import_execution_guard_uses_postgres_advisory_lock(monkeypatch):
    from contextlib import contextmanager

    from soymutdb_worker.tasks import ingest

    statements = []

    class Result:
        def __init__(self, *, scalar=None, row=None):
            self._scalar = scalar
            self._row = row

        def scalar_one(self):
            return self._scalar

        def first(self):
            return self._row

    class Session:
        def execute(self, statement, params=None):
            sql = str(statement)
            statements.append((sql, params))
            if "pg_try_advisory_lock" in sql:
                return Result(scalar=True)
            if "SELECT status FROM import_tasks" in sql:
                return Result(row=("ready",))
            if "pg_advisory_unlock" in sql:
                return Result(scalar=True)
            raise AssertionError(sql)

    @contextmanager
    def fake_db():
        yield Session()

    monkeypatch.setattr(ingest, "get_db", fake_db, raising=False)

    with ingest.import_execution_guard(42) as should_run:
        assert should_run is False

    assert "pg_try_advisory_lock" in statements[0][0]
    assert "SELECT status FROM import_tasks" in statements[1][0]
    assert "pg_advisory_unlock" in statements[2][0]
    assert statements[0][1] == statements[2][1]


def test_module_tsv_adapter_accepts_csv(tmp_path):
    get_adapter("module_tsv")  # ensure registered
    path = tmp_path / "genes.csv"
    path.write_bytes(b"gene_id,chromosome,start,end\nG1,Chr01,1,9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.csv")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["module_key"] == "genes"
    assert result["rows"] == 1


def test_module_tsv_adapter_accepts_txt(tmp_path):
    path = tmp_path / "genes.txt"
    path.write_bytes(b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.txt")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["rows"] == 1


def test_module_tsv_adapter_accepts_xlsx(tmp_path):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip("openpyxl not installed in worker venv")

    from io import BytesIO

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(["gene_id", "chromosome", "start", "end"])
    sheet.append(["G1", "Chr01", 1, 9])
    buf = BytesIO()
    book.save(buf)

    path = tmp_path / "genes.xlsx"
    path.write_bytes(buf.getvalue())
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.xlsx")
    result = get_adapter("module_tsv").validate(ctx)
    assert result["rows"] == 1


def test_module_tsv_adapter_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "genes.pdf"
    path.write_bytes(b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    ctx = ImportContext(1, 2, "1", str(path), module_key="genes", filename="genes.pdf")
    with pytest.raises(ValueError, match="Unsupported module file format"):
        get_adapter("module_tsv").validate(ctx)


def test_module_tsv_adapter_reads_s3_source_in_bounded_chunks(monkeypatch):
    """S3 module imports must parse the body directly, never download it first."""
    from soymutdb_worker.utils import s3

    body = _BoundedReadStream(
        b"gene_id\tchromosome\tstart\tend\n"
        b"G1\tChr01\t1\t9\n"
        b"G2\tChr02\t10\t20\n"
    )

    opened_paths: list[str] = []

    @contextmanager
    def stream_source(key: str):
        opened_paths.append(key)
        try:
            yield body
        finally:
            body.close()

    def forbid_full_download(*_args, **_kwargs):
        raise AssertionError("module import must not download the entire S3 object")

    monkeypatch.setattr(s3, "stream_s3_file", stream_source)
    monkeypatch.setattr(s3, "download_file", forbid_full_download)

    result = get_adapter("module_tsv").validate(
        ImportContext(
            1,
            2,
            "1",
            "s3://genomic-data/imports/genes.tsv",
            module_key="genes",
            filename="genes.tsv",
        )
    )

    assert result["rows"] == 2
    assert opened_paths == ["s3://genomic-data/imports/genes.tsv"]
    assert body.read_sizes
    assert body.closed is True


def test_module_tsv_adapter_reads_bare_data_object_key_from_analyses_bucket(monkeypatch):
    """Direct multipart object keys are in the configured analyses bucket."""
    from soymutdb_worker.utils import s3

    body = _BoundedReadStream(
        b"gene_id\tchromosome\tstart\tend\n"
        b"G1\tChr01\t1\t9\n"
    )
    opened_paths: list[str] = []

    @contextmanager
    def stream_source(key: str):
        opened_paths.append(key)
        try:
            yield body
        finally:
            body.close()

    monkeypatch.setenv("SOYMUTDB_S3_ANALYSES_BUCKET", "module-uploads")
    monkeypatch.setattr(s3, "stream_s3_file", stream_source)

    result = get_adapter("module_tsv").validate(
        ImportContext(
            1,
            2,
            "1",
            "data/2/immutable-genes.tsv",
            module_key="genes",
            filename="genes.tsv",
        )
    )

    assert result["rows"] == 1
    assert opened_paths == ["module-uploads/data/2/immutable-genes.tsv"]
    assert body.closed is True


def test_module_tsv_adapter_rejects_a_legacy_bare_key_from_another_dataset_before_db_access(
    monkeypatch,
):
    """Old queued messages cannot read one data set while attesting another."""
    from soymutdb_worker.utils import db as worker_db

    def fail_if_database_is_opened():
        pytest.fail("an invalid browser object key must fail before database writes")

    monkeypatch.setattr(worker_db, "get_db", fail_if_database_is_opened)

    with pytest.raises(ValueError, match="does not belong to this data set"):
        get_adapter("module_tsv").run(
            ImportContext(
                1,
                2,
                "1",
                "data/1/immutable-genes.tsv",
                module_key="genes",
                filename="genes.tsv",
            )
        )


def test_module_tsv_adapter_rejects_a_traversal_shaped_bare_key_before_db_access(
    monkeypatch,
):
    """A matching prefix must not make ``data/<id>/../...`` an owned key."""
    from soymutdb_worker.utils import db as worker_db

    def fail_if_database_is_opened():
        pytest.fail("a traversal-shaped browser object key must fail before database writes")

    monkeypatch.setattr(worker_db, "get_db", fail_if_database_is_opened)

    with pytest.raises(ValueError, match="traversal segments"):
        get_adapter("module_tsv").run(
            ImportContext(
                1,
                2,
                "1",
                "data/2/../1/immutable-genes.tsv",
                module_key="genes",
                filename="genes.tsv",
            )
        )


def test_module_tsv_adapter_locks_and_rejects_non_draft_release_before_delete(
    tmp_path,
    monkeypatch,
):
    """A queued import must not replace rows after the release became immutable."""
    from soymutdb_worker.utils import db as worker_db

    source = tmp_path / "genes.tsv"
    source.write_text("gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    statements: list[str] = []

    class Result:
        def scalar_one_or_none(self):
            return "published"

    class Session:
        def execute(self, statement, _params=None):
            rendered = str(statement)
            statements.append(rendered)
            if "SELECT releases.status" in rendered:
                return Result()
            pytest.fail(f"non-draft release must not mutate rows: {rendered}")

    @contextmanager
    def fake_db():
        yield Session()

    monkeypatch.setattr(worker_db, "get_db", fake_db)

    with pytest.raises(ValueError, match="draft release"):
        get_adapter("module_tsv").run(
            ImportContext(
                1,
                2,
                "1",
                str(source),
                module_key="genes",
                filename=source.name,
            )
        )

    assert statements and "FOR UPDATE" in statements[0]
    assert not any("DELETE" in statement for statement in statements)


@pytest.mark.parametrize(
    ("data_set_type", "bound_release_id", "expected_error"),
    [
        ("module_tsv", 99, "not bound to this release"),
        ("vcf", 1, "requires a module_tsv data set"),
    ],
)
def test_module_tsv_adapter_locks_and_validates_dataset_binding_before_delete(
    tmp_path,
    monkeypatch,
    data_set_type,
    bound_release_id,
    expected_error,
):
    """Legacy queue payloads cannot target a different release or data-set kind."""
    from soymutdb_worker.utils import db as worker_db

    source = tmp_path / "genes.tsv"
    source.write_text("gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n")
    statements: list[str] = []

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def one_or_none(self):
            return self.value

    class Session:
        def execute(self, statement, _params=None):
            rendered = str(statement)
            statements.append(rendered)
            if "SELECT releases.status" in rendered:
                return Result("draft")
            if "SELECT data_sets.type, data_sets.release_id" in rendered:
                return Result((data_set_type, bound_release_id))
            pytest.fail(f"invalid dataset binding must not mutate rows: {rendered}")

    @contextmanager
    def fake_db():
        yield Session()

    monkeypatch.setattr(worker_db, "get_db", fake_db)

    with pytest.raises(ValueError, match=expected_error):
        get_adapter("module_tsv").run(
            ImportContext(
                1,
                2,
                "1",
                str(source),
                module_key="genes",
                filename=source.name,
            )
        )

    assert len(statements) == 2
    assert all("FOR UPDATE" in statement for statement in statements)
    assert not any("DELETE" in statement for statement in statements)


def test_module_tsv_adapter_preserves_legacy_bare_bucket_key(monkeypatch):
    """Only platform-generated ``data/...`` keys receive a bucket prefix."""
    from soymutdb_worker.utils import s3

    body = _BoundedReadStream(
        b"gene_id\tchromosome\tstart\tend\n"
        b"G1\tChr01\t1\t9\n"
    )
    opened_paths: list[str] = []

    @contextmanager
    def stream_source(key: str):
        opened_paths.append(key)
        try:
            yield body
        finally:
            body.close()

    monkeypatch.setenv("SOYMUTDB_S3_ANALYSES_BUCKET", "module-uploads")
    monkeypatch.setattr(s3, "stream_s3_file", stream_source)

    get_adapter("module_tsv").validate(
        ImportContext(
            1,
            2,
            "1",
            "legacy-bucket/imports/genes.tsv",
            module_key="genes",
            filename="genes.tsv",
        )
    )

    assert opened_paths == ["legacy-bucket/imports/genes.tsv"]


@pytest.mark.parametrize("release_id", ["", "not-a-release", "0", "-1"])
def test_module_tsv_adapter_rejects_invalid_release_before_opening_a_source(
    monkeypatch, release_id
):
    """Old outbox messages fail clearly instead of leaking an ``int`` conversion error."""
    from soymutdb_worker.utils import db as worker_db

    def fail_if_database_is_opened():
        pytest.fail("release validation must happen before opening a database transaction")

    monkeypatch.setattr(worker_db, "get_db", fail_if_database_is_opened)

    with pytest.raises(ValueError, match="release_id must be a positive integer"):
        get_adapter("module_tsv").run(
            ImportContext(
                1,
                2,
                release_id,
                "data/2/immutable-genes.tsv",
                module_key="genes",
                filename="genes.tsv",
            )
        )


def test_streamed_row_limit_keeps_the_2m_contract_without_a_large_fixture(monkeypatch):
    """The production schema supports 2M rows; the same guard is exercised cheaply."""
    from soymutdb_jobs import module_schema

    schema = module_schema.get_schema("genes")
    assert schema is not None
    assert schema.max_rows == 2_000_000
    monkeypatch.setitem(
        module_schema.MODULE_SCHEMAS,
        "genes",
        replace(schema, max_rows=2),
    )

    rows = list(
        module_schema.iter_module_rows(
            "genes",
            "genes.tsv",
            b"gene_id\tchromosome\tstart\tend\n"
            b"G1\tChr01\t1\t9\n"
            b"G2\tChr01\t10\t20\n"
            b"G3\tChr01\t21\t30\n",
        )
    )

    assert [row for row, error in rows if error is None] == [
        {"gene_id": "G1", "chromosome": "Chr01", "start": 1, "end": 9, "mutation_feature": None},
        {"gene_id": "G2", "chromosome": "Chr01", "start": 10, "end": 20, "mutation_feature": None},
    ]
    assert rows[-1][0] is None
    assert rows[-1][1] is not None
    assert rows[-1][1].code == "max_rows"


@pytest.mark.slow
@pytest.mark.parametrize(
    ("row_count", "max_seconds", "max_rss_growth_mib", "max_total_rss_mib"),
    [
        (100_000, 10.0, 128, 512),
        pytest.param(
            2_000_000,
            180.0,
            512,
            1024,
            marks=pytest.mark.skipif(
                os.environ.get("SOYMUTDB_RUN_2M_IMPORT_PERF") != "1",
                reason="set SOYMUTDB_RUN_2M_IMPORT_PERF=1 to run the 2M-row acceptance tier",
            ),
        ),
    ],
)
def test_streamed_module_import_performance_contract(
    row_count: int,
    max_seconds: float,
    max_rss_growth_mib: int,
    max_total_rss_mib: int,
):
    """Measure row count, elapsed time, and peak RSS without a giant fixture."""
    from soymutdb_jobs.module_schema import (
        STREAM_READ_CHUNK_BYTES,
        validate_module_file_streaming_from_stream,
    )

    source = _GeneratedGenesTsvStream(rows=row_count)
    started = time.perf_counter()

    summary = validate_module_file_streaming_from_stream("genes", "genes.tsv", source)
    elapsed_seconds = time.perf_counter() - started
    initial_rss_mib = source.initial_rss_bytes / 1024 / 1024
    peak_rss_mib = source.peak_rss_bytes / 1024 / 1024

    print(
        "module_import_performance "
        f"rows={row_count} elapsed_seconds={elapsed_seconds:.3f} "
        f"initial_rss_mib={initial_rss_mib:.1f} peak_rss_mib={peak_rss_mib:.1f}"
    )

    assert summary.ok is True
    assert summary.row_count == row_count
    assert summary.error_count == 0
    assert source.read_sizes
    assert all(0 < size <= STREAM_READ_CHUNK_BYTES for size in source.read_sizes)
    assert elapsed_seconds <= max_seconds
    # ``VmRSS`` includes the worker runtime as well as the de-duplication set.
    # Track both the import-attributable growth and the total process envelope.
    # Non-Linux runners return 0 and retain the time/row contract.
    assert source.peak_rss_bytes - source.initial_rss_bytes <= max_rss_growth_mib * 1024 * 1024
    assert source.peak_rss_bytes <= max_total_rss_mib * 1024 * 1024

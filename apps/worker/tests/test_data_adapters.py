import hashlib
import io
import multiprocessing
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


class _GeneratedGenesTsvStream(io.RawIOBase):
    """Produce a large valid TSV without allocating its complete source fixture.

    Subclasses :class:`io.RawIOBase` so it is a real binary stream: the shared
    validator's streaming entry points are typed ``BinaryIO``, and a read()-only
    duck type does not satisfy that contract for a type checker even though the
    runtime path works. ``name``/``mode`` match what a file object exposes.
    """

    name = "<generated-genes-tsv>"
    mode = "rb"

    def __init__(self, rows: int) -> None:
        super().__init__()
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


@pytest.mark.parametrize("kind", ["blast_db"])
def test_adapter_without_durable_writer_fails_closed(kind, tmp_path):
    # Only blast_db is left in this set. `vcf` has a durable writer behind the
    # ADR-0005 protocol (flag-gated OFF, covered by test_vcf_import.py); `fasta`
    # and `gff3` gained real writers in annotation_writers.py, and their own
    # fail-closed behaviour is asserted below.
    path = tmp_path / f"input-{kind}.txt"
    path.write_text(">chr1\nACGT\n")

    with pytest.raises(
        RuntimeError,
        match=rf"{kind} import is disabled.*durable persistence",
    ):
        get_adapter(kind).run(ImportContext(1, 2, "r1", str(path), "a1"))


def test_fasta_adapter_requires_the_faidx_index(tmp_path):
    """A reference without its `.fai` sidecar cannot state its lengths.

    The writer reads the index, not the FASTA, so a missing index is the one
    failure mode that would otherwise produce a silently empty chromosome table.
    """
    path = tmp_path / "reference.fa"
    path.write_text(">chr1\nACGT\n")

    with pytest.raises(RuntimeError, match=r"needs the faidx index"):
        get_adapter("fasta").run(ImportContext(1, 2, "r1", str(path), "a1"))


def test_gff3_parser_rejects_a_row_that_is_not_nine_columns(tmp_path):
    """The GFF3 reader fails closed on a malformed row instead of skipping it.

    A skipped row is how a truncated annotation imports "successfully" with
    fewer genes than the file claims, which is the failure the counting stub
    could not detect. The reader is exercised directly: it needs no database,
    and the row-shape contract is the part that has to hold.
    """
    from soymutdb_worker.tasks.annotation_writers import (
        AnnotationWriteError,
        _iter_gff3_rows,
    )

    path = tmp_path / "annotation.gff3"
    path.write_text("chr1\ttest\tgene\t1\t10\n")

    with pytest.raises(AnnotationWriteError, match="must contain 9 fields"):
        list(_iter_gff3_rows(path))


@pytest.mark.parametrize("kind", ["seed_data"])
def test_csv_adapter_without_writer_fails_closed(kind, tmp_path):
    path = tmp_path / f"{kind}.csv"
    path.write_text("id,value\n1,example\n")

    with pytest.raises(RuntimeError, match=rf"{kind} import is disabled.*persistence writer"):
        get_adapter(kind).run(ImportContext(1, 2, "r1", str(path)))


@pytest.mark.parametrize("kind", ["seed_data"])
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


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RecordingSession:
    """Minimal session for the data-set lock and the final status update."""

    def __init__(self, data_set_type):
        self.data_set_type = data_set_type
        self.updates = []

    def execute(self, statement, params=None):
        rendered = str(statement)
        if "SELECT data_sets.type" in rendered:
            return _ScalarResult(self.data_set_type)
        if rendered.startswith("UPDATE data_sets"):
            self.updates.append((statement, params))
            return _ScalarResult(None)
        pytest.fail(f"unexpected statement: {rendered}")

    def commit(self):
        return None


def _patch_session(monkeypatch, session):
    from soymutdb_worker.utils import db as worker_db

    @contextmanager
    def fake_db():
        yield session

    monkeypatch.setattr(worker_db, "get_db", fake_db)
    return session


def _updated_values(statement):
    return {
        getattr(column, "key", str(column)): value.value
        for column, value in statement._values.items()
    }


@pytest.mark.parametrize(
    ("kind", "filename", "header", "row"),
    [
        (
            "expression_csv",
            "expression.csv",
            "gene_id,library_id,fpkm,tpm,raw_count\n",
            "G1,3,1.5,2.5,10\n",
        ),
        (
            "homolog_csv",
            "homolog.csv",
            "gene_id,homolog_species,homolog_gene_id,homolog_type,source\n",
            "G1,Glycine soja,GS01,ortholog,phytozome\n",
        ),
    ],
)
def test_csv_adapters_require_an_explicit_assembly(kind, filename, header, row, tmp_path):
    path = tmp_path / filename
    path.write_text(header + row)
    adapter = get_adapter(kind)

    with pytest.raises(ValueError, match="require an explicit assembly"):
        adapter.validate(ImportContext(1, 2, "r1", str(path), filename=filename))
    with pytest.raises(ValueError, match="require an explicit assembly"):
        adapter.run(ImportContext(1, 2, "r1", str(path), filename=filename))


@pytest.mark.parametrize(
    ("kind", "filename", "header"),
    [
        ("expression_csv", "expression.csv", "gene_id,fpkm\nG1,1.0\n"),
        ("homolog_csv", "homolog.csv", "gene_id,homolog_type\nG1,ortholog\n"),
    ],
)
def test_csv_adapters_reject_missing_columns(kind, filename, header, tmp_path):
    path = tmp_path / filename
    path.write_text(header)
    adapter = get_adapter(kind)

    with pytest.raises(ValueError, match="missing required columns"):
        adapter.validate(
            ImportContext(1, 2, "r1", str(path), assembly="v5", filename=filename)
        )


def test_expression_csv_validate_streams_the_stored_bytes(tmp_path):
    content = (
        "gene_id,library_id,fpkm,tpm,raw_count\n"
        "G1,3,1.5,2.5,10\n"
    )
    path = tmp_path / "expression.csv"
    path.write_text(content)
    expected_checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

    result = get_adapter("expression_csv").validate(
        ImportContext(
            1,
            2,
            "r1",
            str(path),
            assembly="v5",
            filename=path.name,
            checksum=expected_checksum,
        )
    )

    assert result == {
        "kind": "expression_csv",
        "assembly": "v5",
        "checksum": expected_checksum,
        "checksum_verified": True,
    }


def test_expression_csv_run_upserts_assembly_scoped_rows(tmp_path, monkeypatch):
    from soymutdb_worker.tasks import data_adapters

    path = tmp_path / "expression.csv"
    path.write_text(
        "gene_id,library_id,fpkm,tpm,raw_count\n"
        "G1,3,1.5,2.5,10\n"
        "G1,3,1.7,2.7,11\n"
        "# comment,row,is,ignored\n"
        "\n"
    )
    session = _patch_session(monkeypatch, _RecordingSession("expression_csv"))
    adapter = get_adapter("expression_csv")
    monkeypatch.setattr(
        adapter,
        "_references",
        lambda _session, assembly: data_adapters._ExpressionReferences(
            assembly, 7, {"G1": 11}, {3: 7}
        ),
    )
    upserts = []
    monkeypatch.setattr(
        adapter,
        "_upsert",
        lambda _session, payloads: upserts.append(list(payloads)) or len(payloads),
    )

    result = adapter.run(
        ImportContext(1, 2, "r1", str(path), assembly="v5", filename=path.name)
    )

    # The duplicate natural key keeps the last row and is counted, never sent
    # twice in one PostgreSQL upsert statement.
    assert upserts == [
        [
            {
                "gene_id": 11,
                "library_id": 3,
                "fpkm": 1.7,
                "tpm": 2.7,
                "raw_count": 11,
            }
        ]
    ]
    assert result.inserted == 1
    assert result.evidence["rows_seen"] == 2
    assert result.evidence["rows_duplicate"] == 1
    assert result.evidence["assembly_id"] == 7
    values = _updated_values(session.updates[-1][0])
    assert values["status"] == "ready"
    assert values["validation_evidence"]["on_conflict"] == "upsert"


def test_expression_csv_run_rejects_a_library_from_another_assembly(tmp_path, monkeypatch):
    from soymutdb_worker.tasks import data_adapters

    path = tmp_path / "expression.csv"
    path.write_text("gene_id,library_id,fpkm\nG1,3,1.5\n")
    _patch_session(monkeypatch, _RecordingSession("expression_csv"))
    adapter = get_adapter("expression_csv")
    monkeypatch.setattr(
        adapter,
        "_references",
        lambda _session, assembly: data_adapters._ExpressionReferences(
            assembly, 7, {"G1": 11}, {3: 8}
        ),
    )
    monkeypatch.setattr(
        adapter, "_upsert", lambda _session, payloads: pytest.fail("must not write")
    )

    with pytest.raises(ValueError, match="belongs to another assembly"):
        adapter.run(
            ImportContext(1, 2, "r1", str(path), assembly="v5", filename=path.name)
        )


def test_homolog_csv_run_fails_closed_on_an_unknown_gene(tmp_path, monkeypatch):
    from soymutdb_worker.tasks import data_adapters

    path = tmp_path / "homolog.csv"
    path.write_text(
        "gene_id,homolog_species,homolog_gene_id,homolog_type\n"
        "G9,glycine_soja,GS01,ortholog\n"
    )
    _patch_session(monkeypatch, _RecordingSession("homolog_csv"))
    adapter = get_adapter("homolog_csv")
    monkeypatch.setattr(
        adapter,
        "_references",
        lambda _session, assembly: data_adapters._HomologReferences(
            assembly, 7, {"G1": 11}
        ),
    )
    monkeypatch.setattr(
        adapter, "_upsert", lambda _session, payloads: pytest.fail("must not write")
    )

    with pytest.raises(ValueError, match="unknown gene accession 'G9'"):
        adapter.run(
            ImportContext(1, 2, "r1", str(path), assembly="v5", filename=path.name)
        )


@pytest.mark.parametrize(
    ("kind", "filename", "header"),
    [
        (
            "expression_csv",
            "expression.csv",
            "gene_id,library_id,fpkm\nG1,3,1.5\n",
        ),
        (
            "homolog_csv",
            "homolog.csv",
            "gene_id,homolog_species,homolog_gene_id,homolog_type\n"
            "G1,glycine_soja,GS01,ortholog\n",
        ),
    ],
)
def test_csv_adapters_reject_a_mismatched_data_set_kind(
    kind, filename, header, tmp_path, monkeypatch
):
    path = tmp_path / filename
    path.write_text(header)
    _patch_session(monkeypatch, _RecordingSession("module_tsv"))
    adapter = get_adapter(kind)
    monkeypatch.setattr(
        adapter, "_references", lambda _session, assembly: pytest.fail("must not resolve")
    )

    with pytest.raises(ValueError, match=f"requires a {kind} data set"):
        adapter.run(
            ImportContext(1, 2, "r1", str(path), assembly="v5", filename=filename)
        )


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


def test_module_tsv_adapter_records_the_streamed_object_checksum(monkeypatch):
    """Validation evidence must use the bytes read from S3, not caller input."""
    from soymutdb_worker.utils import s3

    content = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"
    body = _BoundedReadStream(content)

    @contextmanager
    def stream_source(_key: str):
        try:
            yield body
        finally:
            body.close()

    monkeypatch.setattr(s3, "stream_s3_file", stream_source)

    result = get_adapter("module_tsv").validate(
        ImportContext(
            1,
            2,
            "1",
            "s3://genomic-data/imports/genes.tsv",
            module_key="genes",
            filename="genes.tsv",
            checksum=hashlib.sha256(content).hexdigest().upper(),
        )
    )

    assert result["checksum"] == hashlib.sha256(content).hexdigest()
    assert result["checksum_verified"] is True


def test_module_tsv_adapter_rejects_a_mismatched_s3_checksum(monkeypatch):
    from soymutdb_worker.utils import s3

    body = _BoundedReadStream(
        b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"
    )

    @contextmanager
    def stream_source(_key: str):
        try:
            yield body
        finally:
            body.close()

    monkeypatch.setattr(s3, "stream_s3_file", stream_source)

    with pytest.raises(ValueError, match="checksum mismatch"):
        get_adapter("module_tsv").validate(
            ImportContext(
                1,
                2,
                "1",
                "s3://genomic-data/imports/genes.tsv",
                module_key="genes",
                filename="genes.tsv",
                checksum="a" * 64,
            )
        )


def test_module_tsv_run_persists_the_streamed_checksum_not_the_caller_value(
    tmp_path, monkeypatch
):
    """The durable evidence written by a module import is source-derived."""
    from soymutdb_worker.tasks import module_promotion
    from soymutdb_worker.utils import db as worker_db

    # The unit test drives the adapter against a fake session; canonical
    # promotion is real SQL and is covered by the PostgreSQL integration suite
    # (test_module_tsv_postgres_integration.py). Stub it here so this test stays
    # scoped to the checksum evidence it asserts.
    monkeypatch.setattr(
        module_promotion,
        "promote_module_rows",
        lambda session, *, module_key, release_id: module_promotion.PromotionResult(
            module_key=module_key,
            target="genes",
            promoted_rows=0,
            genes_removed=0,
            chromosomes_created=0,
            chromosomes_extended=0,
        ),
    )

    content = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"
    source = tmp_path / "genes.tsv"
    source.write_bytes(content)
    updates: list[object] = []

    class Result:
        def __init__(self, value=None):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

        def one_or_none(self):
            return self.value

    class Session:
        def execute(self, statement, _params=None):
            rendered = str(statement)
            if "SELECT releases.status" in rendered:
                return Result("draft")
            if "SELECT data_sets.type, data_sets.release_id" in rendered:
                return Result(("module_tsv", 1))
            if rendered.startswith("UPDATE data_sets"):
                updates.append(statement)
            return Result()

    @contextmanager
    def fake_db():
        yield Session()

    monkeypatch.setattr(worker_db, "get_db", fake_db)

    result = get_adapter("module_tsv").run(
        ImportContext(
            1,
            2,
            "1",
            str(source),
            module_key="genes",
            filename=source.name,
            checksum=hashlib.sha256(content).hexdigest().upper(),
        )
    )

    values = {
        getattr(column, "key", str(column)): value.value
        for column, value in updates[-1]._values.items()
    }
    assert result.evidence["checksum"] == hashlib.sha256(content).hexdigest()
    assert result.evidence["checksum_verified"] is True
    assert values["validation_evidence"]["checksum"] == hashlib.sha256(content).hexdigest()
    assert values["validation_evidence"]["checksum_verified"] is True


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


def _measure_stream_import_performance(row_count: int) -> dict:
    """Measure the streaming import in a fresh interpreter.

    Run via a spawned process by the contract test: sibling worker tests load
    the embedded ClickHouse engine (chdb), whose resident memory is not
    attributable to this import, so sharing the interpreter made the absolute
    RSS envelope depend on test collection order.
    """
    from soymutdb_jobs.module_schema import (
        STREAM_READ_CHUNK_BYTES,
        validate_module_file_streaming_from_stream,
    )

    source = _GeneratedGenesTsvStream(rows=row_count)
    started = time.perf_counter()
    summary = validate_module_file_streaming_from_stream("genes", "genes.tsv", source)
    elapsed_seconds = time.perf_counter() - started
    return {
        "ok": summary.ok,
        "row_count": summary.row_count,
        "error_count": summary.error_count,
        "elapsed_seconds": elapsed_seconds,
        "initial_rss_bytes": source.initial_rss_bytes,
        "peak_rss_bytes": source.peak_rss_bytes,
        "read_sizes_valid": bool(source.read_sizes)
        and all(0 < size <= STREAM_READ_CHUNK_BYTES for size in source.read_sizes),
    }


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
    """Measure row count, elapsed time, and peak RSS without a giant fixture.

    The measurement runs in a spawned interpreter so the RSS envelope reflects
    the import alone. The worker suite also loads chdb (embedded ClickHouse),
    whose resident memory would otherwise count against the import and make the
    absolute limit order-dependent (it failed at 591 MiB in CI).
    """
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=1) as pool:
        measured = pool.apply(_measure_stream_import_performance, (row_count,))

    elapsed_seconds = measured["elapsed_seconds"]
    initial_rss_mib = measured["initial_rss_bytes"] / 1024 / 1024
    peak_rss_mib = measured["peak_rss_bytes"] / 1024 / 1024
    print(
        "module_import_performance "
        f"rows={row_count} elapsed_seconds={elapsed_seconds:.3f} "
        f"initial_rss_mib={initial_rss_mib:.1f} peak_rss_mib={peak_rss_mib:.1f}"
    )

    assert measured["ok"] is True
    assert measured["row_count"] == row_count
    assert measured["error_count"] == 0
    assert measured["read_sizes_valid"] is True
    assert elapsed_seconds <= max_seconds
    # ``VmRSS`` includes the worker runtime as well as the de-duplication set.
    # Track both the import-attributable growth and the total process envelope.
    # Non-Linux runners return 0 and retain the time/row contract.
    assert (
        measured["peak_rss_bytes"] - measured["initial_rss_bytes"]
        <= max_rss_growth_mib * 1024 * 1024
    )
    assert measured["peak_rss_bytes"] <= max_total_rss_mib * 1024 * 1024

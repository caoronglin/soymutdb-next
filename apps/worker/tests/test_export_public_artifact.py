"""Public-artifact contract of the variant export task.

The review found every export (VCF/TSV/CSV/JSON/BED) carried the internal
ClickHouse join keys ``gene_surrogate_id`` and ``mutant_line_surrogate_id``.
A published export is a public artifact, so it must carry public locators
instead, plus the release/assembly provenance that tells a reader which
coordinate namespace the file belongs to.

``MAX_RECORDS_EXPORT`` was also declared but never enforced, so a broad filter
could materialise an unbounded result set in the worker.

These are pure unit tests — no ClickHouse engine and no S3 are needed.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import pytest

from soymutdb_worker.tasks import export as export_task


def _row(**overrides) -> tuple:
    """A row in EXPORT_COLUMNS order, with plausible published values."""
    values = {
        "release_key": "7",
        "assembly_key": "Wm82.a4.v1",
        "chromosome": "chr01",
        "position": 1000,
        "variant_id": "12610413239088682210",
        "ref_allele": "A",
        "alt_allele": "G",
        "variant_type": "SNP",
        "variant_subtype": "SNV",
        "impact": "MODERATE",
        "quality_score": 99.0,
        "allele_frequency": 0.25,
        "zygosity": "het",
        "gene_id": "Glyma.01G000100",
        "gene_symbol": "Glyma.01G000100",
        "mutant_public_id": "MUT-000042",
        "hgvs_c": "c.1A>G",
        "hgvs_p": "p.Met1Val",
        "read_depth": 42,
        "filter_status": "PASS",
    }
    values.update(overrides)
    return tuple(values[column] for column in export_task.EXPORT_COLUMNS)


# ---------------------------------------------------------------------------
# 1. No surrogate keys anywhere in the published column set or the SQL.
# ---------------------------------------------------------------------------


def test_export_columns_never_include_internal_surrogate_ids():
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        assert forbidden not in export_task.EXPORT_COLUMNS


def test_export_columns_carry_public_locators_and_provenance():
    assert "gene_id" in export_task.EXPORT_COLUMNS
    assert "mutant_public_id" in export_task.EXPORT_COLUMNS
    # A downloaded file must state its release and assembly.
    assert "release_key" in export_task.EXPORT_COLUMNS
    assert "assembly_key" in export_task.EXPORT_COLUMNS


def test_export_query_selects_only_public_columns():
    query, params = export_task.build_export_query({"release_key": "7"})

    assert params["release_id"] == 7
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        # The surrogate may still appear as an internal *filter* predicate, but
        # never in the SELECT list.
        select_list = query.split("FROM", 1)[0]
        assert forbidden not in select_list, select_list
    assert "gene_id" in query
    assert "assembly_key" in query


# ---------------------------------------------------------------------------
# 2. Writers address columns by name (a reorder cannot mislabel a file).
# ---------------------------------------------------------------------------


def test_json_export_labels_every_column_by_name():
    rows = [_row()]
    output = io.StringIO()

    count = export_task._write_json(output, rows)

    assert count == 1
    record = json.loads(output.getvalue().strip())
    assert record["release_key"] == "7"
    assert record["assembly_key"] == "Wm82.a4.v1"
    assert record["gene_id"] == "Glyma.01G000100"
    assert record["mutant_public_id"] == "MUT-000042"
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        assert forbidden not in record
        assert forbidden not in output.getvalue()
    # No surrogate *value* leaks either.
    assert "853938470" not in output.getvalue()


def test_tsv_export_writes_the_public_header():
    output = io.StringIO()

    export_task._write_tsv_csv(output, [_row()], "\t")

    header = output.getvalue().splitlines()[0].split("\t")
    assert header == export_task.EXPORT_COLUMNS
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        assert forbidden not in header


def test_vcf_export_stamps_release_and_assembly_provenance():
    output = io.StringIO()

    export_task._write_vcf(
        output, [_row()], {"release_key": "7", "assembly_key": "Wm82.a4.v1"}
    )

    text = output.getvalue()
    assert "##soymutdb_release_key=7" in text
    assert "##soymutdb_assembly_key=Wm82.a4.v1" in text
    # The variant row still carries the public gene locator.
    assert "GENE=Glyma.01G000100" in text
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        assert forbidden not in text


def test_bed_export_names_the_public_gene_not_a_surrogate():
    output = io.StringIO()

    count = export_task._write_bed(output, [_row()])

    assert count == 1
    fields = output.getvalue().strip().split("\t")
    assert fields[0] == "chr01"
    # BED is 0-based half-open: position 1000 -> start 999.
    assert fields[1] == "999"
    assert fields[3].startswith("Glyma.01G000100|")
    for forbidden in sorted(export_task.FORBIDDEN_EXPORT_COLUMNS):
        assert forbidden not in output.getvalue()


def test_record_mapping_follows_the_declared_column_order():
    record = export_task._record(_row(position=555))

    assert record["position"] == 555
    assert record["chromosome"] == "chr01"
    assert set(record) == set(export_task.EXPORT_COLUMNS)


# ---------------------------------------------------------------------------
# 3. The record budget is enforced before any bytes are written.
# ---------------------------------------------------------------------------


def test_record_budget_is_enforced(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(export_task, "MAX_RECORDS_EXPORT", 1)
    monkeypatch.setattr(export_task, "get_setting", lambda *a, **k: "exports")
    monkeypatch.setattr(export_task, "generate_presigned_url", lambda *a, **k: "https://x")

    class _Result:
        rows = [_row(), _row(position=2000)]

        def __iter__(self):
            return iter(self.rows)

        def close(self):
            pass

    class _Database:
        def execute(self, query, parameters=None, **kwargs):
            return _Result()

    from contextlib import contextmanager

    @contextmanager
    def database():
        yield _Database()

    monkeypatch.setattr(export_task, "get_db", database)
    # If the budget were not enforced these would run and write the file.
    monkeypatch.setattr(
        export_task, "upload_large_file", lambda *a, **k: pytest.fail("must not upload")
    )

    with pytest.raises(ValueError) as excinfo:
        export_task.export_variants.run(
            "export-budget", {"release_key": "7"}, "json", False
        )

    assert "budget" in str(excinfo.value).lower()


def test_export_writes_a_gzipped_public_artifact(monkeypatch, tmp_path: Path):
    captured: dict = {}

    class _Result:
        rows = [_row()]

        def __iter__(self):
            return iter(self.rows)

        def close(self):
            pass

    class _Database:
        def execute(self, query, parameters=None, **kwargs):
            return _Result()

    def _upload(local_path: str, s3_path: str) -> None:
        captured["s3_path"] = s3_path
        with open(local_path, "rb") as handle:
            captured["bytes"] = handle.read()

    from contextlib import contextmanager

    @contextmanager
    def database():
        yield _Database()

    monkeypatch.setattr(export_task, "get_db", database)
    monkeypatch.setattr(export_task, "get_setting", lambda *a, **k: "exports")
    monkeypatch.setattr(export_task, "upload_large_file", _upload)
    monkeypatch.setattr(
        export_task, "generate_presigned_url", lambda *a, **k: "https://example/x"
    )
    monkeypatch.setattr(export_task.tempfile, "TemporaryDirectory", lambda: _TmpDir(tmp_path))
    # `bind=True` tasks report progress through the Celery result backend, which
    # needs a live broker; the assertion here is on the artifact, not progress.
    monkeypatch.setattr(export_task.export_variants, "update_state", lambda **k: None)

    result = export_task.export_variants.run(
        "export-ok", {"release_key": "7", "assembly": "Wm82.a4.v1"}, "json", True
    )

    assert result["record_count"] == 1
    payload = gzip.decompress(captured["bytes"]).decode("utf-8")
    record = json.loads(payload.strip())
    assert record["release_key"] == "7"
    assert record["assembly_key"] == "Wm82.a4.v1"
    assert record["gene_id"] == "Glyma.01G000100"


class _TmpDir:
    """Minimal TemporaryDirectory stand-in so the artifact survives the call."""

    def __init__(self, path: Path) -> None:
        self.name = str(path)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *exc: object) -> bool:
        return False

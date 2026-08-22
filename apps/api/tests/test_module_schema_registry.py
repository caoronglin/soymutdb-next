"""Unit tests for the strict module TSV schema registry."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.module_schema_registry import validate_tsv


def test_gene_module_rejects_wrong_headers() -> None:
    result = validate_tsv("genes", b"gene\tchromosome\nG1\tChr01\n")
    assert result.ok is False
    assert result.errors[0].code == "header_mismatch"


def test_gene_module_reports_duplicate_key() -> None:
    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\nG1\tChr01\t10\t20\n"
    result = validate_tsv("genes", data)
    assert result.errors[0].row == 3
    assert result.errors[0].code == "duplicate_key"


def test_gene_module_accepts_valid_rows_and_converts_integers() -> None:
    data = b"gene_id\tchromosome\tstart\tend\tmutation_feature\nG1\tChr01\t1\t9\tSNP\n"
    result = validate_tsv("genes", data)
    assert result.ok is True
    assert result.rows == [
        {
            "gene_id": "G1",
            "chromosome": "Chr01",
            "start": 1,
            "end": 9,
            "mutation_feature": "SNP",
        }
    ]


def test_gene_module_rejects_end_before_start() -> None:
    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t10\t9\n"
    result = validate_tsv("genes", data)
    assert result.ok is False
    assert result.errors[0].code == "end_before_start"


def test_gene_module_rejects_nul_bytes_and_invalid_utf8() -> None:
    assert validate_tsv("genes", b"\x00gene").errors[0].code == "nul_byte"
    assert validate_tsv("genes", b"\xff\xfe").errors[0].code == "invalid_utf8"


def test_unknown_schema_is_rejected() -> None:
    result = validate_tsv("not_a_module", b"a\nb\n")
    assert result.ok is False
    assert result.errors[0].code == "unknown_schema"


def test_supported_formats_and_format_detection() -> None:
    from app.services.module_schema_registry import (
        SUPPORTED_MODULE_FORMATS,
        detect_format,
    )

    assert SUPPORTED_MODULE_FORMATS == (".txt", ".tsv", ".csv", ".xlsx")
    assert detect_format("genes.tsv") == ".tsv"
    assert detect_format("genes.CSV") == ".csv"
    assert detect_format("genes.xlsx") == ".xlsx"
    assert detect_format("genes.txt") == ".txt"
    assert detect_format("genes.pdf") is None
    assert detect_format("noext") is None


def test_csv_module_is_accepted() -> None:
    from app.services.module_schema_registry import validate_module_file

    data = b"gene_id,chromosome,start,end\nG1,Chr01,1,9\n"
    result = validate_module_file("genes", "genes.csv", data)
    assert result.ok is True
    assert result.rows[0]["gene_id"] == "G1"
    assert result.rows[0]["start"] == 1


def test_txt_module_is_accepted_as_tsv() -> None:
    from app.services.module_schema_registry import validate_module_file

    data = b"gene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"
    result = validate_module_file("genes", "genes.txt", data)
    assert result.ok is True


def test_unsupported_format_is_rejected() -> None:
    from app.services.module_schema_registry import validate_module_file

    result = validate_module_file("genes", "genes.pdf", b"whatever")
    assert result.ok is False
    assert result.errors[0].code == "unsupported_format"


def test_xlsx_module_is_accepted_and_round_trips() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip("openpyxl not installed")

    from app.services.module_schema_registry import (
        render_module_template,
        validate_module_file,
    )

    content, media_type, filename = render_module_template("genes", "xlsx")
    assert filename == "genes.xlsx"
    assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    result = validate_module_file("genes", filename, content)
    assert result.ok is True
    assert result.rows[0]["gene_id"] == "Glyma.01G000100"


def test_xlsx_template_has_header_and_example_row() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        pytest.skip("openpyxl not installed")

    from io import BytesIO

    from openpyxl import load_workbook

    from app.services.module_schema_registry import render_module_template

    content, _, _ = render_module_template("genes", "xlsx")
    book = load_workbook(BytesIO(content), read_only=True)
    sheet = book.worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("gene_id", "chromosome", "start", "end", "mutation_feature")
    assert rows[1][0] == "Glyma.01G000100"


def test_template_text_formats_have_correct_delimiter() -> None:
    from app.services.module_schema_registry import render_module_template

    tsv, _, _ = render_module_template("genes", "tsv")
    csv_, _, _ = render_module_template("genes", "csv")
    assert "\t" in tsv and "," not in tsv.splitlines()[0]
    assert "," in csv_ and "\t" not in csv_.splitlines()[0]


def test_template_unknown_format_raises() -> None:
    from app.services.module_schema_registry import render_module_template

    with pytest.raises(ValueError):
        render_module_template("genes", "pdf")


def test_preflight_rejects_legacy_and_signature_mismatch() -> None:
    from app.services.module_schema_registry import preflight_module_file

    assert preflight_module_file("genes.xlsm", b"PK\x03\x04").errors[0].code == "unsupported_format"
    assert preflight_module_file("genes.xlsx", b"not-a-zip").errors[0].code == "format_signature_mismatch"
    assert preflight_module_file("genes.csv", b"PK\x03\x04bad").errors[0].code == "format_signature_mismatch"


def test_preflight_accepts_utf8_bom_and_streaming_rows() -> None:
    from app.services.module_schema_registry import (
        iter_module_rows,
        validate_module_file_streaming,
    )

    data = b"\xef\xbb\xbfgene_id\tchromosome\tstart\tend\nG1\tChr01\t1\t9\n"
    summary = validate_module_file_streaming("genes", "genes.tsv", data)
    assert summary.ok is True
    assert summary.row_count == 1
    rows = list(iter_module_rows("genes", "genes.tsv", data))
    assert rows[0][0]["gene_id"] == "G1"
    assert rows[0][1] is None


def test_streaming_stops_at_physical_row_limit_before_tracking_unbounded_invalid_keys(
    monkeypatch,
) -> None:
    """Invalid unique rows must not bypass the schema's import-row resource cap."""
    from soymutdb_jobs import module_schema

    from app.services.module_schema_registry import iter_module_rows

    schema = module_schema.get_schema("genes")
    assert schema is not None
    monkeypatch.setitem(module_schema.MODULE_SCHEMAS, "genes", replace(schema, max_rows=2))

    data = (
        b"gene_id\tchromosome\tstart\tend\n"
        b"invalid-1\tChr01\t10\t9\n"
        b"invalid-2\tChr01\t10\t9\n"
        b"invalid-3\tChr01\t10\t9\n"
    )

    outcomes = list(iter_module_rows("genes", "genes.tsv", data))

    assert [error.code for _row, error in outcomes if error is not None] == [
        "end_before_start",
        "end_before_start",
        "max_rows",
    ]


def test_preflight_rejects_control_character() -> None:
    from app.services.module_schema_registry import validate_module_file

    result = validate_module_file("genes", "genes.csv", b"gene_id,chromosome,start,end\nG1,Chr01,1,9\x01\n")
    assert result.ok is False
    assert result.errors[0].code == "control_character"

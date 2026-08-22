"""Resource-boundary regressions for shared module-file validation."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable

import pytest
from soymutdb_jobs import module_schema


def _error_code(result: object) -> str:
    errors = getattr(result, "errors")
    assert errors
    return errors[0].code


def _xlsx_archive(*members: tuple[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


def _xlsx_workbook(*rows: list[object]) -> bytes:
    """Build a minimal workbook without putting a fixture on disk."""
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _with_stale_xlsx_dimension(data: bytes, dimension: bytes) -> bytes:
    """Rewrite only worksheet metadata so parsers must inspect real cells."""
    source = io.BytesIO(data)
    output = io.BytesIO()
    with zipfile.ZipFile(source) as input_archive, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as output_archive:
        for member in input_archive.infolist():
            content = input_archive.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                content = re.sub(
                    br'<dimension ref="[^"]+"',
                    b'<dimension ref="' + dimension + b'"',
                    content,
                    count=1,
                )
            output_archive.writestr(member, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.csv", io.BytesIO(data)
        ),
    ],
)
def test_delimited_validation_rejects_overlong_physical_lines(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[bytes], object],
) -> None:
    monkeypatch.setattr(module_schema, "MAX_DELIMITED_PHYSICAL_LINE_CHARACTERS", 32)
    data = b"gene_id,chromosome,start,end\n" + b"x" * 33

    result = validate(data)

    assert _error_code(result) == "line_too_long"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.csv", io.BytesIO(data)
        ),
    ],
)
def test_delimited_validation_rejects_oversized_quoted_fields_across_lines(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[bytes], object],
) -> None:
    monkeypatch.setattr(module_schema, "MAX_DELIMITED_PHYSICAL_LINE_CHARACTERS", 64)
    monkeypatch.setattr(module_schema, "MAX_DELIMITED_FIELD_CHARACTERS", 8)
    data = b'gene_id,chromosome,start,end\n"12345\n6789",Chr01,1,9\n'

    result = validate(data)

    assert _error_code(result) == "field_too_large"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.csv", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.csv", io.BytesIO(data)
        ),
    ],
)
def test_invalid_csv_is_returned_as_a_structured_diagnostic(
    validate: Callable[[bytes], object],
) -> None:
    data = b'gene_id,chromosome,start,end\n"unterminated,Chr01,1,9\n'

    result = validate(data)

    assert _error_code(result) == "invalid_csv"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_rejects_excessive_uncompressed_archive_content(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[bytes], object],
) -> None:
    monkeypatch.setattr(module_schema, "MAX_XLSX_MEMBER_UNCOMPRESSED_BYTES", 64)
    monkeypatch.setattr(module_schema, "MAX_XLSX_UNCOMPRESSED_BYTES", 16)
    data = _xlsx_archive(("xl/worksheets/sheet1.xml", b"x" * 17))

    result = validate(data)

    assert _error_code(result) == "xlsx_archive_too_large"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_rejects_an_oversized_archive_member(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[bytes], object],
) -> None:
    monkeypatch.setattr(module_schema, "MAX_XLSX_MEMBER_UNCOMPRESSED_BYTES", 16)
    monkeypatch.setattr(module_schema, "MAX_XLSX_UNCOMPRESSED_BYTES", 64)
    data = _xlsx_archive(("xl/worksheets/sheet1.xml", b"x" * 17))

    result = validate(data)

    assert _error_code(result) == "xlsx_member_too_large"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_rejects_excessive_compression_ratio(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[bytes], object],
) -> None:
    monkeypatch.setattr(module_schema, "MAX_XLSX_MEMBER_UNCOMPRESSED_BYTES", 1_024)
    monkeypatch.setattr(module_schema, "MAX_XLSX_UNCOMPRESSED_BYTES", 1_024)
    monkeypatch.setattr(module_schema, "MAX_XLSX_COMPRESSION_RATIO", 2)
    data = _xlsx_archive(("xl/worksheets/sheet1.xml", b"x" * 128))

    result = validate(data)

    assert _error_code(result) == "xlsx_compression_ratio_exceeded"


def test_xlsx_validation_rejects_excessive_archive_member_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module_schema, "MAX_XLSX_ARCHIVE_MEMBERS", 1)
    data = _xlsx_archive(
        ("xl/worksheets/sheet1.xml", b"one"),
        ("xl/worksheets/sheet2.xml", b"two"),
    )

    result = module_schema.validate_module_file_streaming_from_stream(
        "genes", "genes.xlsx", io.BytesIO(data)
    )

    assert _error_code(result) == "xlsx_archive_too_many_members"


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.tsv", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.tsv", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.tsv", io.BytesIO(data)
        ),
    ],
)
def test_delimited_validation_rejects_data_rows_with_extra_cells(
    validate: Callable[[bytes], object],
) -> None:
    """A fifth cell must not be silently discarded behind a four-cell header."""
    data = (
        b"gene_id\tchromosome\tstart\tend\n"
        b"G1\tChr01\t1\t9\tignored\n"
    )

    result = validate(data)

    assert _error_code(result) == "row_width_mismatch"
    assert getattr(result, "errors")[0].row == 2


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_rejects_data_rows_with_extra_cells(
    validate: Callable[[bytes], object],
) -> None:
    """XLSX's padded tuples must still expose a non-empty extra cell."""
    data = _xlsx_workbook(
        ["gene_id", "chromosome", "start", "end"],
        ["G1", "Chr01", 1, 9, "ignored"],
    )

    result = validate(data)

    assert _error_code(result) == "row_width_mismatch"
    assert getattr(result, "errors")[0].row == 2


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_rejects_an_extra_cell_hidden_by_stale_dimension(
    validate: Callable[[bytes], object],
) -> None:
    """The worksheet dimension attribute cannot conceal non-empty extra cells."""
    data = _with_stale_xlsx_dimension(
        _xlsx_workbook(
            ["gene_id", "chromosome", "start", "end"],
            ["G1", "Chr01", 1, 9, "ignored"],
        ),
        b"A1:D2",
    )

    result = validate(data)

    assert _error_code(result) == "row_width_mismatch"
    assert getattr(result, "errors")[0].row == 2


def test_xlsx_validation_does_not_misread_trailing_none_padding_as_an_extra_cell() -> None:
    """The header's worksheet width can pad an otherwise valid row with None."""
    data = _xlsx_workbook(
        ["gene_id", "chromosome", "start", "end"],
        ["G1", "Chr01", 1, 9],
    )

    result = module_schema.validate_module_file_streaming("genes", "genes.xlsx", data)

    assert result.ok is True
    assert result.row_count == 1


@pytest.mark.parametrize(
    "validate",
    [
        lambda data: module_schema.validate_module_file("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming("genes", "genes.xlsx", data),
        lambda data: module_schema.validate_module_file_streaming_from_stream(
            "genes", "genes.xlsx", io.BytesIO(data)
        ),
    ],
)
def test_xlsx_validation_allows_an_omitted_optional_trailing_cell(
    validate: Callable[[bytes], object],
) -> None:
    """Workbook padding must not turn an absent optional tail into a bad row width."""
    data = _xlsx_workbook(
        ["gene_id", "chromosome", "start", "end", "mutation_feature"],
        ["G1", "Chr01", 1, 9],
    )

    result = validate(data)

    assert getattr(result, "ok") is True

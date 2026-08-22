"""Bounded, read-only inspection for registered module data files."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import zipfile
from typing import Any

from ..schemas.data_publishing import (
    ImportInspectionErrorResponse,
    ImportInspectionResponse,
    ImportInspectionValidationResponse,
)
from .module_schema_registry import detect_format, get_schema, iter_module_rows

MAX_INSPECTION_BYTES = 256 * 1024
MAX_PREVIEW_ROWS = 100
MAX_PREVIEW_CELL_CHARACTERS = 256
MAX_INSPECTION_ERRORS = 200
MAX_XLSX_ARCHIVE_MEMBERS = 1_000
MAX_XLSX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 100

_MACRO_ENTRIES = frozenset({"xl/vbaproject.bin"})


class ImportInspectionError(ValueError):
    """The inspection envelope cannot be processed safely."""


def decode_inspection_content(content_base64: str) -> bytes:
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImportInspectionError("content_base64 must be valid base64") from exc
    if not data:
        raise ImportInspectionError("inspection content must not be empty")
    if len(data) > MAX_INSPECTION_BYTES:
        raise ImportInspectionError(
            f"inspection content exceeds the {MAX_INSPECTION_BYTES}-byte limit"
        )
    return data


def _inspect_xlsx_archive(data: bytes) -> None:
    """Reject encrypted, macro-enabled, or expansion-heavy XLSX containers."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as workbook:
            members = workbook.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ImportInspectionError("xlsx content is not a valid ZIP archive") from exc
    if len(members) > MAX_XLSX_ARCHIVE_MEMBERS:
        raise ImportInspectionError("xlsx archive contains too many members")
    uncompressed = 0
    for member in members:
        if member.flag_bits & 0x1:
            raise ImportInspectionError("encrypted xlsx archives are not accepted")
        if member.filename.lower() in _MACRO_ENTRIES:
            raise ImportInspectionError("macro-enabled xlsx files are not accepted")
        uncompressed += member.file_size
        compressed_size = max(member.compress_size, 1)
        if member.file_size / compressed_size > MAX_XLSX_COMPRESSION_RATIO:
            raise ImportInspectionError("xlsx archive exceeds the compression-ratio limit")
    if uncompressed > MAX_XLSX_UNCOMPRESSED_BYTES:
        raise ImportInspectionError("xlsx archive exceeds the uncompressed-size limit")


def _safe_preview_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    sanitized = value[:MAX_PREVIEW_CELL_CHARACTERS]
    if len(value) > MAX_PREVIEW_CELL_CHARACTERS:
        sanitized += "…"
    if sanitized.lstrip().startswith(("=", "+", "-", "@")):
        sanitized = "'" + sanitized
    return sanitized


def _metadata(filename: str, data: bytes) -> tuple[list[str], str | None]:
    file_format = detect_format(filename)
    if file_format in {".txt", ".tsv", ".csv"}:
        try:
            text = data.decode("utf-8-sig")
            delimiter = "," if file_format == ".csv" else "\t"
            headers = next(csv.reader(io.StringIO(text), delimiter=delimiter), [])
        except (UnicodeDecodeError, csv.Error):
            return [], None
        return [str(header)[:256] for header in headers], None
    if file_format == ".xlsx":
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheet = workbook.worksheets[0]
            for values in sheet.iter_rows(values_only=True):
                if values and any(value is not None and str(value).strip() for value in values):
                    return [
                        "" if value is None else str(value).strip()[:256]
                        for value in values
                    ], sheet.title
        except Exception:
            return [], None
    return [], None


def inspect_module_file(
    *, module_key: str, filename: str, content_base64: str
) -> ImportInspectionResponse:
    """Inspect one small module file without persistence or task dispatch."""
    schema = get_schema(module_key)
    if schema is None:
        raise ImportInspectionError(f"Unknown module schema '{module_key}'")
    data = decode_inspection_content(content_base64)
    file_format = detect_format(filename)
    if file_format == ".xlsx":
        _inspect_xlsx_archive(data)

    headers, sheet_name = _metadata(filename, data)
    rows: list[dict[str, Any]] = []
    errors: list[ImportInspectionErrorResponse] = []
    row_count = 0
    error_count = 0
    for typed_row, error in iter_module_rows(module_key, filename, data):
        if error is not None:
            error_count += 1
            if len(errors) < MAX_INSPECTION_ERRORS:
                errors.append(
                    ImportInspectionErrorResponse(
                        code=error.code,
                        row=error.row,
                        message=error.message[:1_000],
                    )
                )
            continue
        if typed_row is None:
            continue
        row_count += 1
        if len(rows) < MAX_PREVIEW_ROWS:
            rows.append(
                {
                    key: _safe_preview_value(value)
                    for key, value in typed_row.items()
                    if key in {column.name for column in schema.columns}
                }
            )

    delimiter = None
    encoding = None
    if file_format in {".txt", ".tsv"}:
        delimiter = "\t"
        encoding = "utf-8"
    elif file_format == ".csv":
        delimiter = ","
        encoding = "utf-8"

    return ImportInspectionResponse(
        module_key=module_key,
        filename=filename,
        format=file_format.lstrip(".") if file_format else "unknown",
        encoding=encoding,
        delimiter=delimiter,
        sheet_name=sheet_name,
        headers=headers,
        row_count=row_count,
        rows=rows,
        truncated=row_count > len(rows),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        validation=ImportInspectionValidationResponse(
            ok=error_count == 0,
            error_count=error_count,
            errors=errors,
        ),
    )


__all__ = [
    "ImportInspectionError",
    "MAX_INSPECTION_BYTES",
    "MAX_PREVIEW_ROWS",
    "decode_inspection_content",
    "inspect_module_file",
]

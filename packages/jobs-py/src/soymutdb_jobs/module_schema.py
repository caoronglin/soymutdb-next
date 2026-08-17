"""Server-owned module schema registry and strict tabular validation.

This module intentionally contains no ORM imports: it is a pure validator
used by both the API import service and the worker adapter.  Schema
definitions are immutable Python constants; administrators cannot add or
edit schemas through the API.

Supported input formats (``SUPPORTED_MODULE_FORMATS``): ``.txt`` / ``.tsv``
(tab-delimited), ``.csv`` (comma-delimited) and ``.xlsx`` (Excel, first
worksheet, header row).  The tab/CSV parsers are stdlib-only; the ``.xlsx``
parser lazily imports ``openpyxl`` so that environments without the optional
Excel dependency can still validate every other format.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ScalarType = Literal["string", "integer"]

#: File extensions accepted for a module import, in canonical order.
SUPPORTED_MODULE_FORMATS: tuple[str, ...] = (".txt", ".tsv", ".csv", ".xlsx")

#: Delimiter per text-based format; ``.xlsx`` is handled by openpyxl.
_FORMAT_DELIMITERS: dict[str, str] = {
    ".txt": "\t",
    ".tsv": "\t",
    ".csv": ",",
}

#: Canonical media type per downloadable template format.
_TEMPLATE_MEDIA_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".tsv": "text/tab-separated-values",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ---------------------------------------------------------------------------
# Phase A — file security preflight limits
# ---------------------------------------------------------------------------

#: Maximum accepted module file size in bytes (50 MiB).  Oversized uploads are
#: rejected before any parsing to bound memory usage.
MAX_MODULE_FILE_BYTES: int = 50 * 1024 * 1024

#: Maximum length (in characters) of a single header name.
MAX_HEADER_LENGTH: int = 256

#: Maximum accepted worksheet count in an ``.xlsx`` workbook.
MAX_XLSX_WORKSHEETS: int = 16

#: ZIP local-file-header signature (required for a real ``.xlsx``).
_ZIP_MAGIC: bytes = b"PK\x03\x04"

#: OLE2 compound-document magic (legacy binary ``.xls``) — never accepted.
_OLE_MAGIC: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: Macro-enabled / legacy-binary Excel extensions rejected outright.
FORBIDDEN_MODULE_FORMATS: tuple[str, ...] = (
    ".xlsm",
    ".xlsb",
    ".xls",
    ".xltm",
    ".xlam",
    ".xltx",
    ".xlt",
)

#: A macro-enabled ZIP entry name that must never appear in an import.
_MACRO_SHEET_NAMES: tuple[str, ...] = ("xl/vbaProject.bin",)


@dataclass(frozen=True)
class TsvColumn:
    name: str
    type: ScalarType = "string"
    required: bool = True
    minimum: int | None = None


@dataclass(frozen=True)
class ModuleTsvSchema:
    key: str
    columns: tuple[TsvColumn, ...]
    unique_key: tuple[str, ...]
    max_rows: int = 2_000_000


@dataclass
class ValidationError:
    code: str
    row: int | None
    message: str


@dataclass
class ValidationResult:
    ok: bool
    errors: list[ValidationError] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)

    def first_error(self) -> str | None:
        return self.errors[0].message if self.errors else None


MODULE_SCHEMAS: dict[str, ModuleTsvSchema] = {
    "genes": ModuleTsvSchema(
        key="genes",
        columns=(
            TsvColumn("gene_id", "string", required=True),
            TsvColumn("chromosome", "string", required=True),
            TsvColumn("start", "integer", required=True, minimum=1),
            TsvColumn("end", "integer", required=True, minimum=1),
            TsvColumn("mutation_feature", "string", required=False),
        ),
        unique_key=("gene_id",),
        max_rows=2_000_000,
    ),
}


def get_schema(module_key: str) -> ModuleTsvSchema | None:
    return MODULE_SCHEMAS.get(module_key)


def _convert(value: str, column: TsvColumn, row_number: int, errors: list[ValidationError]) -> Any:
    if value is None or value == "":
        if column.required:
            errors.append(
                ValidationError(
                    "missing_required",
                    row_number,
                    f"Missing required column '{column.name}'",
                )
            )
            return None
        return None
    if column.type == "integer":
        try:
            converted = int(value)
        except ValueError:
            errors.append(
                ValidationError(
                    "invalid_integer", row_number, f"Column '{column.name}' must be an integer"
                )
            )
            return None
        if column.minimum is not None and converted < column.minimum:
            errors.append(
                ValidationError(
                    "below_minimum",
                    row_number,
                    f"Column '{column.name}' must be >= {column.minimum}",
                )
            )
            return None
        return converted
    return value


def detect_format(filename: str) -> str | None:
    """Return the canonical lowercase file extension for *filename*.

    Returns ``None`` when the extension is not in :data:`SUPPORTED_MODULE_FORMATS`.
    """
    if not isinstance(filename, str) or not filename:
        return None
    rl_dot = filename.rfind(".")
    rl_ext = filename[rl_dot:].lower() if rl_dot >= 0 else ""
    return rl_ext if rl_ext in SUPPORTED_MODULE_FORMATS else None


def detect_forbidden_format(filename: str) -> str | None:
    """Return the macro/binary extension if *filename* uses one, else ``None``."""
    if not isinstance(filename, str) or not filename:
        return None
    rl_dot = filename.rfind(".")
    rl_ext = filename[rl_dot:].lower() if rl_dot >= 0 else ""
    return rl_ext if rl_ext in FORBIDDEN_MODULE_FORMATS else None


def preflight_module_file(filename: str | None, data: bytes) -> ValidationResult | None:
    """Run size + extension + magic-number preflight checks.

    Returns a :class:`ValidationResult` describing the first failing check, or
    ``None`` when the bytes pass preflight.  This is intentionally format-aware
    but schema-agnostic: it does not know the columns, only the file envelope.
    """
    if not isinstance(data, (bytes, bytearray)):
        return ValidationResult(
            False, [ValidationError("invalid_input", None, "module data must be bytes")]
        )
    rl_size = len(data)
    if rl_size > MAX_MODULE_FILE_BYTES:
        return ValidationResult(
            False,
            [
                ValidationError(
                    "file_too_large",
                    None,
                    f"module file is {rl_size} bytes, above limit {MAX_MODULE_FILE_BYTES}",
                )
            ],
        )

    rl_fmt = detect_format(filename or "")
    rl_forbidden = detect_forbidden_format(filename or "")
    if rl_forbidden is not None:
        return ValidationResult(
            False,
            [
                ValidationError(
                    "unsupported_format",
                    None,
                    f"macro/legacy format '{rl_forbidden}' is not accepted",
                )
            ],
        )

    # Magic-number vs extension mismatch: an .xlsx must be a ZIP, never OLE2.
    if rl_fmt == ".xlsx":
        if data[:8] == _OLE_MAGIC:
            return ValidationResult(
                False,
                [
                    ValidationError(
                        "format_signature_mismatch",
                        None,
                        "file is a legacy OLE2 workbook, not .xlsx",
                    )
                ],
            )
        if data[:4] != _ZIP_MAGIC and not data.startswith(b"PK"):
            return ValidationResult(
                False,
                [
                    ValidationError(
                        "format_signature_mismatch",
                        None,
                        "file does not start with a ZIP signature",
                    )
                ],
            )
    elif rl_fmt in (".txt", ".tsv", ".csv"):
        # A text format that actually contains a ZIP/OLE2 payload is a mismatch.
        if data[:8] == _OLE_MAGIC or data[:4] == _ZIP_MAGIC:
            return ValidationResult(
                False,
                [
                    ValidationError(
                        "format_signature_mismatch",
                        None,
                        "text module file contains a binary container payload",
                    )
                ],
            )
    return None


def _read_text_rows(
    data: bytes, delimiter: str
) -> tuple[list[str], list[dict[str, str]], ValidationResult | None]:
    """Decode ``data`` and split into ``(fieldnames, rows, error)`` for a
    text format with the given delimiter.  Returns ``error`` on any header /
    encoding problem."""
    if b"\x00" in data:
        return (
            [],
            [],
            ValidationResult(
                False, [ValidationError("nul_byte", None, "module data contains NUL bytes")]
            ),
        )
    # Accept an optional UTF-8 BOM (utf-8-sig) and strip it before parsing.
    try:
        rl_text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return (
            [],
            [],
            ValidationResult(
                False, [ValidationError("invalid_utf8", None, "module data must be UTF-8 encoded")]
            ),
        )

    # Reject control characters (other than \t/\n/\r) anywhere in the body:
    # spreadsheet cells must never embed NUL or other C0/C1 controls that Excel
    # could mis-handle.
    for rl_ch in rl_text:
        rl_ord = ord(rl_ch)
        if rl_ord == 9 or rl_ord == 10 or rl_ord == 13:
            continue
        if rl_ord < 32 or 0x7F <= rl_ord <= 0x9F:
            return (
                [],
                [],
                ValidationResult(
                    False,
                    [
                        ValidationError(
                            "control_character", None, "module data contains control characters"
                        )
                    ],
                ),
            )

    rl_reader = csv.DictReader(io.StringIO(rl_text), delimiter=delimiter)
    if rl_reader.fieldnames is None:
        return (
            [],
            [],
            ValidationResult(False, [ValidationError("empty_file", None, "module data is empty")]),
        )
    rl_fieldnames = list(rl_reader.fieldnames)
    for rl_field in rl_fieldnames:
        if len(rl_field) > MAX_HEADER_LENGTH:
            return (
                [],
                [],
                ValidationResult(
                    False,
                    [
                        ValidationError(
                            "header_too_long",
                            None,
                            f"header '{rl_field[:32]}…' exceeds {MAX_HEADER_LENGTH} chars",
                        )
                    ],
                ),
            )
    return rl_fieldnames, list(rl_reader), None


def _read_xlsx_rows(data: bytes) -> tuple[list[str], list[dict[str, str]], ValidationResult | None]:
    """Read the first worksheet of an ``.xlsx`` workbook; header = first row."""
    # Macro-enabled workbook rejection: scan the raw ZIP namelist for a VBA
    # project entry before any openpyxl parsing (openpyxl silently ignores it).
    try:
        import zipfile

        rl_zip = zipfile.ZipFile(io.BytesIO(data))
        rl_names = set(rl_zip.namelist())
    except Exception as rl_exc:
        return (
            [],
            [],
            ValidationResult(
                False,
                [ValidationError("invalid_xlsx", None, f"cannot open workbook zip: {rl_exc!s}")],
            ),
        )
    for rl_macro in _MACRO_SHEET_NAMES:
        if rl_macro in rl_names:
            return (
                [],
                [],
                ValidationResult(
                    False,
                    [
                        ValidationError(
                            "macro_enabled", None, "macro-enabled workbook is not accepted"
                        )
                    ],
                ),
            )

    try:
        from openpyxl import load_workbook
    except ImportError:
        return (
            [],
            [],
            ValidationResult(
                False,
                [ValidationError("invalid_xlsx", None, "openpyxl is required for xlsx import")],
            ),
        )
    try:
        rl_book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return (
            [],
            [],
            ValidationResult(
                False, [ValidationError("invalid_xlsx", None, "cannot open workbook")]
            ),
        )
    try:
        rl_sheets = rl_book.worksheets
        if len(rl_sheets) > MAX_XLSX_WORKSHEETS:
            return (
                [],
                [],
                ValidationResult(
                    False,
                    [
                        ValidationError(
                            "too_many_worksheets", None, f"workbook has {len(rl_sheets)} worksheets"
                        )
                    ],
                ),
            )
        rl_sheet = rl_sheets[0]
    except (IndexError, AttributeError):
        return (
            [],
            [],
            ValidationResult(
                False, [ValidationError("empty_workbook", None, "workbook has no worksheet")]
            ),
        )
    # 为什么：隐藏 sheet 可能是透视/宏/辅助数据载体，导入只接受首个显式可见 sheet。
    if getattr(rl_sheet, "sheet_state", "visible") != "visible":
        return (
            [],
            [],
            ValidationResult(
                False, [ValidationError("hidden_sheet", None, "first worksheet is hidden")]
            ),
        )

    rl_grid: list[tuple[Any, ...]] = []
    for rl_row in rl_sheet.iter_rows(values_only=True):
        rl_values = tuple(rl_row)
        if rl_values and any(rl_v is not None and str(rl_v).strip() != "" for rl_v in rl_values):
            rl_grid.append(rl_values)
    if not rl_grid:
        return (
            [],
            [],
            ValidationResult(False, [ValidationError("empty_file", None, "module data is empty")]),
        )

    rl_fieldnames = [str(rl_v).strip() if rl_v is not None else "" for rl_v in rl_grid[0]]
    for rl_field in rl_fieldnames:
        if len(rl_field) > MAX_HEADER_LENGTH:
            return (
                [],
                [],
                ValidationResult(
                    False,
                    [
                        ValidationError(
                            "header_too_long",
                            None,
                            f"header '{rl_field[:32]}…' exceeds {MAX_HEADER_LENGTH} chars",
                        )
                    ],
                ),
            )
    rl_rows: list[dict[str, str]] = []
    for rl_values in rl_grid[1:]:
        rl_row: dict[str, str] = {}
        for rl_idx, rl_field in enumerate(rl_fieldnames):
            rl_cell = rl_values[rl_idx] if rl_idx < len(rl_values) else None
            rl_row[rl_field] = "" if rl_cell is None else str(rl_cell).strip()
        rl_rows.append(rl_row)
    return rl_fieldnames, rl_rows, None


def _validate_rows(
    schema: ModuleTsvSchema,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> ValidationResult:
    """Run the shared header + row validation over already-parsed rows."""
    if len(fieldnames) != len(set(fieldnames)):
        return ValidationResult(
            False, [ValidationError("duplicate_header", None, "data contains duplicate headers")]
        )

    schema_columns = {col.name: col for col in schema.columns}
    unknown = [name for name in fieldnames if name not in schema_columns]
    if unknown:
        return ValidationResult(
            False,
            [ValidationError("header_mismatch", None, f"Unknown columns: {', '.join(unknown)}")],
        )

    missing = [col.name for col in schema.columns if col.required and col.name not in fieldnames]
    if missing:
        return ValidationResult(
            False,
            [
                ValidationError(
                    "header_mismatch", None, f"Missing required columns: {', '.join(missing)}"
                )
            ],
        )

    errors: list[ValidationError] = []
    out_rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row_index, raw_row in enumerate(rows, start=2):
        if len(out_rows) >= schema.max_rows:
            errors.append(
                ValidationError("max_rows", row_index, f"Exceeds maximum rows ({schema.max_rows})")
            )
            break

        typed: dict[str, Any] = {}
        row_valid = True
        for col in schema.columns:
            raw_value = raw_row.get(col.name, "") if raw_row else ""
            value = _convert(raw_value, col, row_index, errors)
            if col.required and (value is None or (isinstance(value, str) and not value.strip())):
                row_valid = False
                if not any(e.row == row_index and e.code == "missing_required" for e in errors):
                    errors.append(
                        ValidationError(
                            "missing_required", row_index, f"Missing required column '{col.name}'"
                        )
                    )
            typed[col.name] = value

        key_parts: list[str] = []
        for key_name in schema.unique_key:
            key_value = typed.get(key_name)
            if key_value is None or (isinstance(key_value, str) and not key_value.strip()):
                errors.append(
                    ValidationError(
                        "blank_key", row_index, f"Unique key column '{key_name}' is blank"
                    )
                )
                row_valid = False
            else:
                key_parts.append(str(key_value))
        row_key = "\x1f".join(key_parts)

        if row_key in seen_keys:
            errors.append(
                ValidationError(
                    "duplicate_key", row_index, f"Duplicate unique key: {' | '.join(key_parts)}"
                )
            )
            row_valid = False
        else:
            seen_keys.add(row_key)

        # Module-specific cross-field checks.
        if schema.key == "genes":
            rl_start = typed.get("start")
            rl_end = typed.get("end")
            if isinstance(rl_start, int) and isinstance(rl_end, int) and rl_end < rl_start:
                errors.append(
                    ValidationError("end_before_start", row_index, "end must be >= start")
                )
                row_valid = False

        if row_valid:
            out_rows.append(typed)

    if errors:
        return ValidationResult(False, errors=errors[:200])

    return ValidationResult(True, rows=out_rows)


def validate_module_file(module_key: str, filename: str, data: bytes) -> ValidationResult:
    """Validate a module file of any supported format against the schema.

    The format is detected from the ``filename`` extension.  Unknown formats
    yield ``unsupported_format``; ``.xlsx`` is read via openpyxl (first
    worksheet, header row).  Returns typed rows on success.
    """
    schema = get_schema(module_key)
    if schema is None:
        return ValidationResult(
            False,
            [ValidationError("unknown_schema", None, f"Unknown module schema '{module_key}'")],
        )

    rl_preflight = preflight_module_file(filename, data)
    if rl_preflight is not None:
        return rl_preflight

    rl_fmt = detect_format(filename)
    if rl_fmt is None:
        return ValidationResult(
            False,
            [
                ValidationError(
                    "unsupported_format",
                    None,
                    f"Unsupported module file format for '{filename}'",
                )
            ],
        )

    if rl_fmt == ".xlsx":
        rl_fieldnames, rl_rows, rl_error = _read_xlsx_rows(data)
    else:
        rl_fieldnames, rl_rows, rl_error = _read_text_rows(data, _FORMAT_DELIMITERS[rl_fmt])

    if rl_error is not None:
        return rl_error
    return _validate_rows(schema, rl_fieldnames, rl_rows)


def validate_tsv(module_key: str, data: bytes) -> ValidationResult:
    """Validate raw TSV bytes against the server-owned schema.

    Retained for backward compatibility; equivalent to
    ``validate_module_file(module_key, "<name>.tsv", data)``.  Returns typed
    rows on success and bounded row-level diagnostics on failure.
    """
    schema = get_schema(module_key)
    if schema is None:
        return ValidationResult(
            False,
            [ValidationError("unknown_schema", None, f"Unknown module schema '{module_key}'")],
        )

    # 为什么：validate_tsv 无 filename，但 size/文本 envelope 预检仍要执行。
    rl_preflight = preflight_module_file(None, data)
    if rl_preflight is not None:
        return rl_preflight

    rl_fieldnames, rl_rows, rl_error = _read_text_rows(data, "\t")
    if rl_error is not None:
        return rl_error
    return _validate_rows(schema, rl_fieldnames, rl_rows)


def render_module_template(module_key: str, file_format: str) -> tuple[str | bytes, str, str]:
    """Render a starter template for *module_key* in *file_format*.

    Returns ``(content, media_type, suggested_filename)``.  ``file_format``
    is one of ``tsv`` / ``csv`` / ``txt`` / ``xlsx`` (case-insensitive).
    ``.xlsx`` returns raw workbook bytes built with openpyxl; the text
    formats return a header + one example row.
    """
    schema = get_schema(module_key)
    if schema is None:
        raise ValueError(f"Unknown module schema '{module_key}'")

    rl_fmt = "." + str(file_format).lower().lstrip(".")
    if rl_fmt not in SUPPORTED_MODULE_FORMATS:
        raise ValueError(f"Unsupported template format '{file_format}'")

    rl_headers = [col.name for col in schema.columns]
    rl_example = []
    for col in schema.columns:
        if col.name == "gene_id":
            rl_example.append("Glyma.01G000100")
        elif col.name == "chromosome":
            rl_example.append("Chr01")
        elif col.name == "start":
            rl_example.append("1")
        elif col.name == "end":
            rl_example.append("1000")
        elif col.name == "mutation_feature":
            rl_example.append("")
        else:
            rl_example.append("")

    rl_filename = f"{module_key}{rl_fmt}"
    rl_media_type = _TEMPLATE_MEDIA_TYPES[rl_fmt]

    if rl_fmt == ".xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as rl_exc:
            raise ValueError("openpyxl is required for xlsx templates") from rl_exc
        rl_book = Workbook()
        rl_sheet = rl_book.active
        rl_sheet.title = module_key
        rl_sheet.append(rl_headers)
        rl_sheet.append(rl_example)
        rl_buffer = io.BytesIO()
        rl_book.save(rl_buffer)
        return rl_buffer.getvalue(), rl_media_type, rl_filename

    rl_delimiter = _FORMAT_DELIMITERS[rl_fmt]
    rl_text = rl_delimiter.join(rl_headers) + "\n" + rl_delimiter.join(rl_example) + "\n"
    return rl_text, rl_media_type, rl_filename


# ---------------------------------------------------------------------------
# Phase B: streaming readers, two-phase validation, and batched typing.
#
# The legacy ``validate_module_file`` / ``validate_tsv`` entry points above
# stay intact for small-file compatibility; they materialise typed rows into
# ``ValidationResult.rows``.  The streaming API below never materialises the
# whole file: rows are typed and yielded one at a time (B1/B2), so callers can
# batch-insert without holding millions of rows in memory.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileMetadata:
    """Structural facts about a parsed module file (B2 structural preflight)."""

    format: str
    encoding: str | None
    delimiter: str | None
    sheet_name: str | None
    fieldnames: tuple[str, ...]


@dataclass
class ValidationSummary:
    """Outcome of a two-phase streaming validation (B2).

    ``ok`` mirrors :class:`ValidationResult.ok`; ``errors`` is bounded to the
    inline diagnostics (≤ 200), while ``error_count`` / ``row_count`` report
    totals without retaining per-row detail in memory.
    """

    ok: bool
    errors: list[ValidationError] = field(default_factory=list)
    row_count: int = 0
    error_count: int = 0

    def first_error(self) -> str | None:
        return self.errors[0].message if self.errors else None


#: Upper bound on inline diagnostics retained by a streaming validation (B2).
MAX_INLINE_DIAGNOSTICS = 200


@dataclass(frozen=True)
class ParsedRow:
    """One raw data row yielded by a streaming reader."""

    row_number: int
    values: dict[str, str]


class ModuleFileReader(Protocol):
    """Streaming reader protocol (B1).

    ``iter_rows`` yields one :class:`ParsedRow` at a time; implementations must
    never call ``list(...)`` over the whole input.  ``metadata`` reports the
    resolved structural facts (format / delimiter / sheet).
    """

    metadata: FileMetadata

    def iter_rows(self) -> Iterator[ParsedRow]: ...


class DelimitedTextReader:
    """Streaming reader for ``.txt`` / ``.tsv`` (tab) and ``.csv`` (comma)."""

    def __init__(self, data: bytes, file_format: str) -> None:
        if b"\x00" in data:
            raise ValueError("module data contains NUL bytes")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("module data must be UTF-8 encoded") from exc
        delimiter = _FORMAT_DELIMITERS[file_format]
        self._csv_reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        try:
            header = next(self._csv_reader)
        except StopIteration as exc:
            raise ValueError("module data is empty") from exc
        if not header or not any(h and h.strip() for h in header):
            raise ValueError("module data is empty")
        fieldnames = tuple(h.strip() for h in header)
        self.metadata = FileMetadata(
            format=file_format,
            encoding="utf-8",
            delimiter=delimiter,
            sheet_name=None,
            fieldnames=fieldnames,
        )

    def iter_rows(self) -> Iterator[ParsedRow]:
        for row_number, values in enumerate(self._csv_reader, start=2):
            row = {
                name: (values[i] if i < len(values) else "")
                for i, name in enumerate(self.metadata.fieldnames)
            }
            yield ParsedRow(row_number=row_number, values=row)


class XlsxReader:
    """Streaming reader for ``.xlsx`` (openpyxl ``read_only=True``).

    Reads the first worksheet; the header is the first non-empty row.  No
    ``rl_grid`` full-list materialisation.
    """

    def __init__(self, data: bytes, sheet_name: str | None = None) -> None:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ValueError("openpyxl is required for xlsx import") from exc
        try:
            self._book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ValueError("cannot open workbook") from exc
        try:
            sheet = self._book[sheet_name] if sheet_name else self._book.worksheets[0]
        except (IndexError, KeyError, AttributeError) as exc:
            raise ValueError("workbook has no worksheet") from exc
        self._sheet = sheet
        self._iterator = sheet.iter_rows(values_only=True)
        self._resolved_sheet = sheet.title
        fieldnames: tuple[str, ...] = ()
        for values in self._iterator:
            if values and any(v is not None and str(v).strip() for v in values):
                fieldnames = tuple((str(v).strip() if v is not None else "") for v in values)
                break
        if not fieldnames or not any(fn for fn in fieldnames):
            raise ValueError("module data is empty")
        self.metadata = FileMetadata(
            format=".xlsx",
            encoding=None,
            delimiter=None,
            sheet_name=self._resolved_sheet,
            fieldnames=fieldnames,
        )

    def iter_rows(self) -> Iterator[ParsedRow]:
        for row_number, values in enumerate(self._iterator, start=2):
            if not values or not any(v is not None and str(v).strip() for v in values):
                continue
            row = {
                name: ("" if i >= len(values) or values[i] is None else str(values[i]).strip())
                for i, name in enumerate(self.metadata.fieldnames)
            }
            yield ParsedRow(row_number=row_number, values=row)


def _reader_for(module_key: str, filename: str, data: bytes) -> ModuleFileReader | ValidationResult:
    """Build the streaming reader for *filename*/*data*, or a terminal error.

    Mirrors the fail-closed structural preflight of ``validate_module_file``:
    unknown schema / unsupported format / NUL / bad encoding / empty file are
    rejected before any row is consumed.
    """
    schema = get_schema(module_key)
    if schema is None:
        return ValidationResult(
            False,
            [ValidationError("unknown_schema", None, f"Unknown module schema '{module_key}'")],
        )

    rl_preflight = preflight_module_file(filename, data)
    if rl_preflight is not None:
        return rl_preflight

    file_format = detect_format(filename)
    if file_format is None:
        return ValidationResult(
            False,
            [
                ValidationError(
                    "unsupported_format",
                    None,
                    f"Unsupported module file format for '{filename}'",
                )
            ],
        )

    try:
        if file_format == ".xlsx":
            return XlsxReader(data)
        return DelimitedTextReader(data, file_format)
    except ValueError as exc:
        message = str(exc)
        if "NUL" in message:
            code = "nul_byte"
        elif "UTF-8" in message:
            code = "invalid_utf8"
        elif "openpyxl" in message:
            code = "invalid_xlsx"
        elif "workbook" in message:
            code = "empty_workbook"
        else:
            code = "empty_file"
        return ValidationResult(False, [ValidationError(code, None, message)])


def iter_typed_rows(
    module_key: str, reader: ModuleFileReader
) -> Iterator[tuple[dict[str, Any] | None, ValidationError | None]]:
    """Stream structural + row validation, yielding ``(typed_row, error)``.

    For each data row this yields either a typed ``dict`` (valid) or a
    ``ValidationError`` (invalid row is skipped, error is reported).  Header
    problems (duplicate / unknown / missing required columns) are emitted once
    as a single ``(None, ValidationError)`` tuple and stop iteration, matching
    the fail-closed legacy behaviour.
    """
    schema = get_schema(module_key)
    if schema is None:
        yield None, ValidationError("unknown_schema", None, f"Unknown module schema '{module_key}'")
        return

    fieldnames = list(reader.metadata.fieldnames)
    if len(fieldnames) != len(set(fieldnames)):
        yield None, ValidationError("duplicate_header", None, "data contains duplicate headers")
        return

    schema_columns = {col.name: col for col in schema.columns}
    unknown = [name for name in fieldnames if name not in schema_columns]
    if unknown:
        yield (
            None,
            ValidationError("header_mismatch", None, f"Unknown columns: {', '.join(unknown)}"),
        )
        return

    missing = [col.name for col in schema.columns if col.required and col.name not in fieldnames]
    if missing:
        yield (
            None,
            ValidationError(
                "header_mismatch", None, f"Missing required columns: {', '.join(missing)}"
            ),
        )
        return

    seen_keys: set[str] = set()
    for parsed in reader.iter_rows():
        row_number = parsed.row_number
        row = parsed.values
        errors: list[ValidationError] = []
        typed: dict[str, Any] = {}
        row_valid = True
        for col in schema.columns:
            raw_value = row.get(col.name, "") if row else ""
            value = _convert(raw_value, col, row_number, errors)
            if col.required and (value is None or (isinstance(value, str) and not value.strip())):
                row_valid = False
                if not any(e.row == row_number and e.code == "missing_required" for e in errors):
                    errors.append(
                        ValidationError(
                            "missing_required", row_number, f"Missing required column '{col.name}'"
                        )
                    )
            typed[col.name] = value

        key_parts: list[str] = []
        for key_name in schema.unique_key:
            key_value = typed.get(key_name)
            if key_value is None or (isinstance(key_value, str) and not key_value.strip()):
                errors.append(
                    ValidationError(
                        "blank_key", row_number, f"Unique key column '{key_name}' is blank"
                    )
                )
                row_valid = False
            else:
                key_parts.append(str(key_value))
        row_key = "\x1f".join(key_parts)

        if row_key in seen_keys:
            errors.append(
                ValidationError(
                    "duplicate_key", row_number, f"Duplicate unique key: {' | '.join(key_parts)}"
                )
            )
            row_valid = False
        else:
            seen_keys.add(row_key)

        if schema.key == "genes":
            start = typed.get("start")
            end = typed.get("end")
            if isinstance(start, int) and isinstance(end, int) and end < start:
                errors.append(
                    ValidationError("end_before_start", row_number, "end must be >= start")
                )
                row_valid = False

        if row_valid:
            yield typed, None
        else:
            yield (
                None,
                errors[0] if errors else ValidationError("invalid_row", row_number, "invalid row"),
            )


def iter_module_rows(
    module_key: str, filename: str, data: bytes
) -> Iterator[tuple[dict[str, Any] | None, ValidationError | None]]:
    """Yield typed rows/errors without materialising all rows.

    This is the worker-facing streaming API. Header/envelope failures are
    yielded once and terminate; row failures are yielded individually so the
    caller can bound diagnostics and roll back its transaction.
    """
    reader_or_error = _reader_for(module_key, filename, data)
    if isinstance(reader_or_error, ValidationResult):
        if reader_or_error.errors:
            yield None, reader_or_error.errors[0]
        return
    yield from iter_typed_rows(module_key, reader_or_error)


def validate_module_file_streaming(
    module_key: str, filename: str, data: bytes
) -> ValidationSummary:
    """Streaming, two-phase validation returning a bounded :class:`ValidationSummary`.

    Equivalent contract to ``validate_module_file`` (fail-closed, same error
    codes) but does not retain typed rows or unbounded diagnostics in memory.
    """
    reader_or_error = _reader_for(module_key, filename, data)
    if isinstance(reader_or_error, ValidationResult):
        return ValidationSummary(False, errors=reader_or_error.errors)

    summary = ValidationSummary(ok=True)
    for _typed, error in iter_typed_rows(module_key, reader_or_error):
        if error is not None:
            summary.ok = False
            summary.error_count += 1
            if len(summary.errors) < MAX_INLINE_DIAGNOSTICS:
                summary.errors.append(error)
        else:
            summary.row_count += 1
    return summary


__all__ = [
    "DelimitedTextReader",
    "FileMetadata",
    "MAX_INLINE_DIAGNOSTICS",
    "ModuleFileReader",
    "ModuleTsvSchema",
    "MODULE_SCHEMAS",
    "ParsedRow",
    "SUPPORTED_MODULE_FORMATS",
    "TsvColumn",
    "ValidationError",
    "ValidationResult",
    "ValidationSummary",
    "XlsxReader",
    "detect_format",
    "get_schema",
    "iter_module_rows",
    "iter_typed_rows",
    "render_module_template",
    "validate_module_file",
    "validate_module_file_streaming",
    "validate_tsv",
]

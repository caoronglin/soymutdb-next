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
from dataclasses import dataclass, field
from typing import Any, Literal

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


def _read_text_rows(
    data: bytes, delimiter: str
) -> tuple[list[str], list[dict[str, str]], ValidationResult | None]:
    """Decode ``data`` and split into ``(fieldnames, rows, error)`` for a
    text format with the given delimiter.  Returns ``error`` on any header /
    encoding problem."""
    if b"\x00" in data:
        return [], [], ValidationResult(
            False, [ValidationError("nul_byte", None, "module data contains NUL bytes")]
        )
    try:
        rl_text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [], [], ValidationResult(
            False, [ValidationError("invalid_utf8", None, "module data must be UTF-8 encoded")]
        )

    rl_reader = csv.DictReader(io.StringIO(rl_text), delimiter=delimiter)
    if rl_reader.fieldnames is None:
        return [], [], ValidationResult(
            False, [ValidationError("empty_file", None, "module data is empty")]
        )
    rl_fieldnames = list(rl_reader.fieldnames)
    return rl_fieldnames, list(rl_reader), None


def _read_xlsx_rows(data: bytes) -> tuple[list[str], list[dict[str, str]], ValidationResult | None]:
    """Read the first worksheet of an ``.xlsx`` workbook; header = first row."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return [], [], ValidationResult(
            False, [ValidationError("invalid_xlsx", None, "openpyxl is required for xlsx import")]
        )
    try:
        rl_book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        return [], [], ValidationResult(
            False, [ValidationError("invalid_xlsx", None, "cannot open workbook")]
        )
    try:
        rl_sheet = rl_book.worksheets[0]
    except (IndexError, AttributeError):
        return [], [], ValidationResult(
            False, [ValidationError("empty_workbook", None, "workbook has no worksheet")]
        )

    rl_grid: list[tuple[Any, ...]] = []
    for rl_row in rl_sheet.iter_rows(values_only=True):
        rl_values = tuple(rl_row)
        if rl_values and any(rl_v is not None and str(rl_v).strip() != "" for rl_v in rl_values):
            rl_grid.append(rl_values)
    if not rl_grid:
        return [], [], ValidationResult(
            False, [ValidationError("empty_file", None, "module data is empty")]
        )

    rl_fieldnames = [str(rl_v).strip() if rl_v is not None else "" for rl_v in rl_grid[0]]
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

    rl_fieldnames, rl_rows, rl_error = _read_text_rows(data, "\t")
    if rl_error is not None:
        return rl_error
    return _validate_rows(schema, rl_fieldnames, rl_rows)


def render_module_template(
    module_key: str, file_format: str
) -> tuple[str | bytes, str, str]:
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


__all__ = [
    "ModuleTsvSchema",
    "MODULE_SCHEMAS",
    "SUPPORTED_MODULE_FORMATS",
    "TsvColumn",
    "ValidationError",
    "ValidationResult",
    "detect_format",
    "get_schema",
    "render_module_template",
    "validate_module_file",
    "validate_tsv",
]

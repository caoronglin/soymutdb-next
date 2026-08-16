"""Server-owned TSV schema registry and strict row validation.

This module intentionally contains no ORM imports: it is a pure validator
used by both the API import service and the worker adapter.  Schema
definitions are immutable Python constants; administrators cannot add or
edit schemas through the API.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Literal

ScalarType = Literal["string", "integer"]


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


def validate_tsv(module_key: str, data: bytes) -> ValidationResult:
    """Validate raw TSV bytes against the server-owned schema.

    Returns typed rows on success and bounded row-level diagnostics on
    failure.  No rows are returned when any error is present.
    """
    schema = get_schema(module_key)
    if schema is None:
        return ValidationResult(
            False,
            [ValidationError("unknown_schema", None, f"Unknown module schema '{module_key}'")],
        )

    if b"\x00" in data:
        return ValidationResult(
            False, [ValidationError("nul_byte", None, "TSV contains NUL bytes")]
        )

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ValidationResult(
            False, [ValidationError("invalid_utf8", None, "TSV must be UTF-8 encoded")]
        )

    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if reader.fieldnames is None:
        return ValidationResult(False, [ValidationError("empty_file", None, "TSV is empty")])

    fieldnames = list(reader.fieldnames)
    if len(fieldnames) != len(set(fieldnames)):
        return ValidationResult(
            False, [ValidationError("duplicate_header", None, "TSV contains duplicate headers")]
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
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row_number, raw_row in enumerate(reader, start=2):
        if len(rows) >= schema.max_rows:
            errors.append(
                ValidationError("max_rows", row_number, f"Exceeds maximum rows ({schema.max_rows})")
            )
            break

        typed: dict[str, Any] = {}
        row_valid = True
        for col in schema.columns:
            raw_value = raw_row.get(col.name, "") if raw_row else ""
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

        key_parts = []
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

        # Module-specific cross-field checks.
        if schema.key == "genes":
            start = typed.get("start")
            end = typed.get("end")
            if isinstance(start, int) and isinstance(end, int) and end < start:
                errors.append(
                    ValidationError("end_before_start", row_number, "end must be >= start")
                )
                row_valid = False

        if row_valid:
            rows.append(typed)

    if errors:
        return ValidationResult(False, errors=errors[:200])

    return ValidationResult(True, rows=rows)


__all__ = [
    "ModuleTsvSchema",
    "MODULE_SCHEMAS",
    "TsvColumn",
    "ValidationError",
    "ValidationResult",
    "get_schema",
    "validate_tsv",
]

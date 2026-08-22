"""Bounded import-studio validation, patch application, and manifest building.

This module intentionally keeps all security/limit decisions in pure,
DB-free functions so they can be tested without PostgreSQL.  The ORM layer
only persists validated state and must never bypass these checks.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from ..core.exceptions import ValidationError

MAX_GENERIC_ROWS = 100_000
MAX_GENERIC_COLUMNS = 50
MAX_SCIENCE_ROWS = 2_000_000
MAX_SCIENCE_COLUMNS = 256

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_DANGEROUS_RE = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|style)\b|"
    r"<\s*[a-z0-9]+\b[^>]*\bon[a-z]+\s*="
)
_URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def validate_import_shape(
    *,
    row_count: int,
    column_count: int,
    module_key: str | None,
) -> None:
    """Fail closed on generic-page limits; registered schemas may be larger."""
    if row_count < 0 or column_count < 0:
        raise ValidationError("Import row and column counts must be non-negative")
    if module_key:
        if row_count > MAX_SCIENCE_ROWS:
            raise ValidationError(
                "Registered scientific import exceeds the streaming limit",
                details={"max_rows": MAX_SCIENCE_ROWS},
            )
        if column_count > MAX_SCIENCE_COLUMNS:
            raise ValidationError(
                "Registered scientific import has too many columns",
                details={"max_columns": MAX_SCIENCE_COLUMNS},
            )
        return
    if row_count > MAX_GENERIC_ROWS:
        raise ValidationError(
            "Generic pages are limited to 100,000 rows; "
            "use a registered scientific adapter or object storage for larger data",
            details={"max_rows": MAX_GENERIC_ROWS},
        )
    if column_count > MAX_GENERIC_COLUMNS:
        raise ValidationError(
            "Generic pages are limited to 50 columns",
            details={"max_columns": MAX_GENERIC_COLUMNS},
        )


def validate_field_mapping(
    mappings: list[dict[str, Any]],
    *,
    columns: list[str] | None = None,
) -> None:
    """Reject duplicate targets, unknown source columns, and unsafe keys."""
    if len(mappings) > MAX_GENERIC_COLUMNS:
        raise ValidationError(
            "Field mapping exceeds the 50-column limit",
            details={"max_columns": MAX_GENERIC_COLUMNS},
        )
    sources: set[str] = set()
    targets: set[str] = set()
    for entry in mappings:
        source = entry.get("source_field")
        target = entry.get("target_field")
        if not isinstance(source, str) or not source:
            raise ValidationError("Each mapping must declare source_field")
        if not isinstance(target, str) or not target:
            raise ValidationError("Each mapping must declare target_field")
        if source in sources or target in targets:
            raise ValidationError("Field mapping source and target fields must be unique")
        if columns is not None and source not in columns:
            raise ValidationError(
                f"Field mapping source {source!r} is not present in the source columns",
                details={"source_field": source},
            )
        if re.match(r"(?i)^(?:on|style|class|script|href|src|url|uri)$", target):
            raise ValidationError(
                f"Field mapping target {target!r} is reserved",
                details={"target_field": target},
            )
        _reject_patch_value(entry.get("transform", {}))
        sources.add(source)
        targets.add(target)


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > 1_000:
            raise ValidationError("Cell values longer than 1,000 characters are rejected")
        if _DANGEROUS_RE.search(value):
            raise ValidationError("Cell values containing script/HTML are rejected")
        if value.lstrip().startswith(_FORMULA_PREFIXES):
            return "'" + value
        if _URL_SCHEME_RE.match(value.strip()):
            raise ValidationError("Cell values cannot contain URLs or URI schemes")
    return value


def _reject_patch_value(value: Any) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if _DANGEROUS_RE.search(value):
            raise ValidationError("Patch values cannot contain script/HTML")
        if value.lstrip().startswith(_FORMULA_PREFIXES):
            raise ValidationError("Patch values cannot contain spreadsheet formulas")
        if _URL_SCHEME_RE.match(value.strip()):
            raise ValidationError("Patch values cannot contain URLs or URI schemes")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise ValidationError("Patch value lists are too large")
        for item in value:
            _reject_patch_value(item)
        return
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValidationError("Patch value objects are too large")
        for key, item in value.items():
            if not isinstance(key, str) or re.match(
                r"(?i)^(?:script|style|href|src|url|uri|endpoint|host)$", key
            ):
                raise ValidationError("Patch value objects contain a reserved key")
            _reject_patch_value(item)
        return
    raise ValidationError("Patch values must contain JSON-compatible values")


def validate_data_patches(patches: list[dict[str, Any]]) -> None:
    """Reject unsafe or unbounded cell edits before persistence."""
    if not isinstance(patches, list):
        raise ValidationError("Patches must be a list")
    if len(patches) > 10_000:
        raise ValidationError("A draft cannot contain more than 10,000 patches")
    for patch in patches:
        row_key = patch.get("row_key")
        column = patch.get("column_name")
        if not isinstance(row_key, str) or not row_key or len(row_key) > 512:
            raise ValidationError("Each patch must declare a bounded row_key")
        if not isinstance(column, str) or not column or len(column) > 256:
            raise ValidationError("Each patch must declare a bounded column_name")
        _reject_patch_value(patch.get("old_value"))
        _reject_patch_value(patch.get("new_value"))


def apply_data_patches(
    rows: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply bounded cell patches to a mutable working copy of rows."""
    if not isinstance(rows, list) or not isinstance(patches, list):
        raise ValidationError("Rows and patches must be lists")
    if len(patches) > 10_000:
        raise ValidationError("A draft cannot contain more than 10,000 patches")

    result = [
        {key: _safe_scalar(value) for key, value in row.items()}
        for row in rows
    ]
    for patch in patches:
        row_key = patch.get("row_key")
        column = patch.get("column_name")
        if not isinstance(row_key, str) or not isinstance(column, str):
            raise ValidationError("Each patch must declare row_key and column_name")
        target = next((row for row in result if str(row.get("_row_key")) == row_key), None)
        if target is None:
            raise ValidationError(
                f"Patch row {row_key!r} was not found",
                details={"row_key": row_key},
            )
        target[column] = _safe_scalar(patch.get("new_value"))
    return result


def build_publication_manifest(
    *,
    draft_id: str,
    dataset_version_id: str,
    checksum_sha256: str,
    row_count: int,
    column_count: int,
    module_key: str | None,
) -> dict[str, Any]:
    """Build a deterministic, source-bound publication manifest."""
    payload = {
        "schema_version": 1,
        "draft_id": draft_id,
        "dataset_version_id": dataset_version_id,
        "checksum_sha256": checksum_sha256,
        "row_count": row_count,
        "column_count": column_count,
        "module_key": module_key,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    payload["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


__all__ = [
    "MAX_GENERIC_COLUMNS",
    "MAX_GENERIC_ROWS",
    "MAX_SCIENCE_COLUMNS",
    "MAX_SCIENCE_ROWS",
    "apply_data_patches",
    "build_publication_manifest",
    "validate_data_patches",
    "validate_field_mapping",
    "validate_import_shape",
]

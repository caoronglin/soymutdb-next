#!/usr/bin/env python3
"""Regenerate the committed API contract snapshot without environment noise.

``openapi-typescript`` renders two pydantic 2.14 serialization choices that are
not contract changes, so diffing a fresh export against the committed
``src/generated/openapi.d.ts`` reports debt on every run:

* An optional field with a ``None`` default loses ``default: null`` on the
  wire. The generated client then flips ``string | null`` into an optional
  ``string | null``, and the diff is a *client* regression even though the API
  response is unchanged.
* A PEP 695 union alias (``type SettingValue = str | int | bool``) used as an
  annotated ``dict`` value is hoisted into ``$defs`` and referenced by ``$ref``,
  one level deeper than the inline union the committed snapshot carries — and
  ``$defs`` entries are not part of ``components.schemas``, so a client reading
  the components table cannot resolve them.

The normalizations below restate the committed shape explicitly, so
regeneration is reproducible and a *real* contract change still shows up as a
diff.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DIR = REPO_ROOT / "apps" / "api"
for path in (str(API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

#: Inline union of the setting-value scalar kinds, as the committed snapshot
#: spells it (``additionalProperties`` of every settings document).
SETTING_VALUE = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "boolean"}]}
SETTING_VALUE_OR_NULL = {
    "anyOf": [
        {"type": "string"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "null"},
    ]
}

#: Schemas that carry ``dict[str, SettingValue]`` / ``dict[str, SettingValue | None]``.
SETTINGS_DOCUMENTS = (
    "SettingsDocumentResponse",
    "SettingsHistoryItem",
    "SettingsPatchRequest",
    "SettingsValidateRequest",
    "SettingsValidateResponse",
)

#: Fields declared ``X | None = None``. pydantic 2.14 stopped emitting the
#: ``default: null`` that tells a client the field is always present.
DEFAULT_NONE_FIELDS = {
    "GeneDetail": (
        "id",
        "gene_id",
        "assembly_id",
        "assembly_name",
        "name",
        "symbol",
        "description",
        "created_at",
        "updated_at",
        "model_evidence",
    ),
    "SequenceAvailability": ("reason", "length", "checksum", "sequence"),
}


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _with_null_default(prop: dict[str, Any]) -> dict[str, Any]:
    """``X | None = None`` -> ``anyOf: [X, null], default: null``."""

    if "anyOf" in prop:
        core = next(branch for branch in prop["anyOf"] if branch.get("type") != "null")
    else:
        core = {key: value for key, value in prop.items() if key != "default"}
    restored: dict[str, Any] = {}
    if "title" in prop:
        restored["title"] = prop["title"]
    restored["anyOf"] = [_clone(core), {"type": "null"}]
    restored["default"] = None
    return restored


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document["components"]["schemas"]

    for name in SETTINGS_DOCUMENTS:
        properties = schemas[name]["properties"]
        properties["values"]["additionalProperties"] = _clone(SETTING_VALUE)
        if "changes" in properties:
            properties["changes"]["additionalProperties"] = _clone(SETTING_VALUE_OR_NULL)
    default_field = schemas["SettingFieldSchema"]["properties"]["default"]
    default_field.clear()
    default_field.update(title="Default", **_clone(SETTING_VALUE_OR_NULL))
    # The union is inline now; the hoisted definition has no consumer.
    schemas.pop("SettingValue", None)

    for schema_name, fields in DEFAULT_NONE_FIELDS.items():
        properties = schemas[schema_name]["properties"]
        for field in fields:
            properties[field] = _with_null_default(properties[field])

    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openapi", required=True, help="Destination OpenAPI JSON.")
    parser.add_argument("--error-codes", help="Destination for the error-code catalog.")
    args = parser.parse_args()

    from app.core.exceptions import error_code_catalog
    from app.main import app

    document = normalize(app.openapi())
    openapi_path = Path(args.openapi)
    openapi_path.parent.mkdir(parents=True, exist_ok=True)
    openapi_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(f"openapi exported -> {openapi_path}")

    if args.error_codes:
        codes_path = Path(args.error_codes)
        codes_path.parent.mkdir(parents=True, exist_ok=True)
        codes_path.write_text(
            json.dumps(error_code_catalog(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"error-code catalog exported -> {codes_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

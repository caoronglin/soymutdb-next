#!/usr/bin/env python3
"""Regenerate the committed API contract snapshot without environment noise.

``openapi-typescript`` renders one pydantic serialization choice that is not a
contract change, so diffing a fresh export against the committed
``src/generated/openapi.d.ts`` would report debt on every run:

* An optional field with a ``None`` default (``x: str | None = None``) gains a
  ``default: null`` in the JSON Schema, which pydantic version and model
  configuration decide — not the API. The generated client flips
  ``string | null`` into an optional ``string | null``, and the diff is a
  *client* regression even though the API response is unchanged.

The committed snapshot chose one spelling — *no* ``default: null`` — so the
export moves every optional nullable field to that spelling. The rule is read
off the document (``anyOf`` with a ``null`` branch, not in ``required``), never
off a list of field names: the list version is what broke the frontend gate.
It named the ten ``GeneDetail`` and four ``SequenceAvailability`` fields, so a
snapshot generated while the list covered five of them carried
``default: null`` for those five and omitted it for the other five, and every
later export disagreed no matter what pydantic did.

A second, historical normalization — inlining the hoisted PEP 695 alias
``type SettingValue = str | int | bool`` — is kept because the committed
snapshot carries the inline shape. The current pydantic emits the union inline
already, so it only keeps older outputs reproducible.

``normalize`` deliberately leaves key order alone. ``openapi-typescript``
prints ``paths`` in document order unless ``--alphabetize`` is passed, and the
committed ``openapi.d.ts`` was always generated without it, so the snapshot
has to keep FastAPI's router-registration order. Inserting a route by hand in
the wrong place -- #25 added six ``/api/v1/comparative/*`` paths at their
alphabetical position -- leaves every other path in the right place while
still reshuffling the generated file, and the contract gate then reports a
diff it cannot explain. Append new paths where the router registers them.
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
SETTING_VALUE = {
    "anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "boolean"}]
}
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

#: Distinguishes "no ``default`` key" from "``default`` is ``null``".
_MISSING = object()


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _drop_null_default(prop: dict[str, Any]) -> dict[str, Any]:
    """Strip ``default: null`` from an optional nullable property.

    Only the default goes: ``anyOf`` keeps its ``null`` branch, because that
    is the field's *type*. Key order follows the committed shape (``title``,
    ``anyOf``, then the extras) so a regenerated document stays byte-stable.
    """

    restored: dict[str, Any] = {}
    if "title" in prop:
        restored["title"] = prop["title"]
    restored["anyOf"] = _clone(prop["anyOf"])
    for extra in ("description", "examples"):
        if extra in prop:
            restored[extra] = _clone(prop[extra])
    return restored


def _optional_nullable(prop: dict[str, Any]) -> bool:
    """Does this property describe ``X | None`` while not being required?

    A required nullable field is not this case: it has to stay a plain
    ``anyOf: [X, null]``. Neither is a field carrying a non-null default,
    which is a real contract statement about the value the server sends.
    """

    if "anyOf" not in prop:
        return False
    default = prop.get("default", _MISSING)
    if default is not _MISSING and default is not None:
        return False
    return any(branch.get("type") == "null" for branch in prop["anyOf"])


def _strip_null_defaults(schemas: dict[str, Any]) -> None:
    """Restate every optional nullable field in the committed spelling.

    Derived from the document rather than from a list of names: a hand-kept
    list goes stale the moment a schema gains an optional field, and the only
    symptom is the frontend contract gate failing with "CONTRACT DEBT" on a
    document nobody touched.
    """

    for schema in schemas.values():
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        required = set(schema.get("required", ()))
        for name, prop in properties.items():
            if name in required or not isinstance(prop, dict):
                continue
            if _optional_nullable(prop):
                properties[name] = _drop_null_default(prop)


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document["components"]["schemas"]

    for name in SETTINGS_DOCUMENTS:
        properties = schemas[name]["properties"]
        properties["values"]["additionalProperties"] = _clone(SETTING_VALUE)
        if "changes" in properties:
            properties["changes"]["additionalProperties"] = _clone(
                SETTING_VALUE_OR_NULL
            )
    # Keyed by name, not by the "default" *property*: a schema that happens to
    # describe a field called ``default`` must not shadow the normalizer.
    setting_default = schemas["SettingFieldSchema"]["properties"]["default"]
    setting_default.clear()
    setting_default.update(title="Default", **_clone(SETTING_VALUE_OR_NULL))
    # The union is inline now; the hoisted definition has no consumer.
    schemas.pop("SettingValue", None)

    _strip_null_defaults(schemas)

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

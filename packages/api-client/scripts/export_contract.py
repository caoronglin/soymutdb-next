#!/usr/bin/env python3
"""Regenerate the committed API contract snapshot without environment noise.

Two kinds of difference between a fresh export and the committed
``src/generated/openapi.d.ts`` are not contract changes, so they are restated
here instead of being reported as debt:

* A PEP 695 union alias (``type SettingValue = str | int | bool``) used as an
  annotated ``dict`` value is hoisted into ``$defs`` and referenced by ``$ref``,
  one level deeper than the inline union the committed snapshot carries — and
  ``$defs`` entries are not part of ``components.schemas``, so a client reading
  the components table cannot resolve them.
* pydantic decides where in a property's JSON object ``title`` goes, and the
  committed snapshot was printed by one pydantic version. Mixing dialects
  inside one schema is not a contract change either, but it *is* the reason the
  snapshot's spelling has to be restated rather than inherited — see
  ``_title_last``.

Restating ``default: null`` is deliberately *not* on that list. Its absence is
a client-visible change: ``openapi-typescript`` renders an optional field as
``field?: string | null``, so a consumer that read it without a guard starts
reading ``undefined``. The normalizer restores it for every optional nullable
field, derived from the document (``anyOf`` with a ``null`` branch, not in
``required``) rather than from a list of names — the hand-kept list drifted
once already and left one schema with both spellings.

``normalize`` deliberately leaves ``path`` order alone. ``openapi-typescript``
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


def _clone(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


#: Property keys that keep their printed order. Everything else -- ``title``
#: above all -- is re-emitted in the snapshot's spelling by ``_title_last``.
_ORDERED_KEYS = ("anyOf", "oneOf", "allOf", "$ref", "type", "items", "enum")


def _title_last(prop: dict[str, Any]) -> dict[str, Any]:
    """Re-emit one property in the committed snapshot's key order.

    The snapshot was printed by a pydantic that writes the value keywords
    first and ``title`` last, and that omits ``title`` beside a lone ``$ref``.
    ``openapi-typescript`` only reads the keywords, so this is a re-ordering,
    not a contract change -- but a *different* pydantic prints ``title`` first,
    and a document holding both spellings inside one schema can never match a
    fresh export again. That is what kept the frontend contract gate red with
    "CONTRACT DEBT" for a schema nobody edited.
    """

    ordered: dict[str, Any] = {key: prop[key] for key in _ORDERED_KEYS if key in prop}
    for key, value in prop.items():
        if key not in ordered and key != "title":
            ordered[key] = value
    # A ``$ref`` already names the definition; a sibling ``title`` is what
    # pydantic prints for an inline value, not for a reference.
    if "title" in prop and "$ref" not in prop:
        ordered["title"] = prop["title"]
    return ordered


def _is_nullable(prop: dict[str, Any]) -> bool:
    return any(branch.get("type") == "null" for branch in prop.get("anyOf", ()))


#: Object-level keys, in the order the committed snapshot prints them. pydantic
#: emits ``required`` before ``title``/``type``; the snapshot carries ``type``
#: before ``required``. ``_title_last`` only ever reordered *property* objects,
#: so a schema with no other key to shuffle kept the pydantic order and read as
#: CONTRACT DEBT against a backend that had not moved.
_OBJECT_KEY_ORDER = (
    "properties",
    "additionalProperties",
    "type",
    "required",
    "title",
    "description",
    # ``$defs`` trails the schema it is embedded in, matching the snapshot.
    "$defs",
)


def _object_last(node: dict[str, Any]) -> dict[str, Any]:
    """Re-emit one schema object in the committed snapshot's key order.

    Deliberately shallow: ``properties`` values are handled by
    ``_title_last``, and every key not listed in ``_OBJECT_KEY_ORDER`` keeps
    its relative position after the known ones, so a schema gaining a keyword
    stays put instead of being silently dropped.
    """

    ordered: dict[str, Any] = {key: node[key] for key in _OBJECT_KEY_ORDER if key in node}
    for key, value in node.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _normalize_properties(document: dict[str, Any]) -> None:
    """One spelling for every property in the document.

    Two rules, both derived from the document itself so a new schema needs no
    edit here:

    * an optional nullable field keeps ``default: null``;
    * property key order matches the snapshot (see ``_title_last``); and
    * schema object key order matches the snapshot (see ``_object_last``).
    """

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                required = set(node.get("required", ()))
                for name, prop in properties.items():
                    if not isinstance(prop, dict):
                        continue
                    if name not in required and _is_nullable(prop):
                        prop.setdefault("default", None)
                    properties[name] = _title_last(prop)
            # Schema-level key order too, not just property-level: pydantic
            # emits `required` before `title`/`type`, the snapshot carries
            # `type` before `required`, and a document holding both spellings
            # can never match a fresh export.
            #
            # Gated on `properties` on purpose: the object shapes elsewhere in
            # the document (`requestBody`, a parameter object) also carry
            # `required`, and moving that key there would rewrite the paths
            # table for no reason. `_object_last` only permutes existing keys,
            # so clearing and refilling in place is safe.
            if isinstance(properties, dict):
                reordered = _object_last(node)
                node.clear()
                node.update(reordered)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(document)


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document["components"]["schemas"]

    for name in SETTINGS_DOCUMENTS:
        properties = schemas[name]["properties"]
        properties["values"]["additionalProperties"] = _clone(SETTING_VALUE)
        if "changes" in properties:
            properties["changes"]["additionalProperties"] = _clone(SETTING_VALUE_OR_NULL)
    setting_default = schemas["SettingFieldSchema"]["properties"]["default"]
    setting_default.clear()
    setting_default.update(title="Default", **_clone(SETTING_VALUE_OR_NULL))
    # The union is inline now; the hoisted definition has no consumer.
    schemas.pop("SettingValue", None)

    _normalize_properties(document)

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

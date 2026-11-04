"""Guard the committed OpenAPI snapshot against hand edits.

``packages/api-client/openapi.json`` is an *export*, not a source file. The CI
contract gate re-exports the schema from ``app.main:app`` and diffs the
generated TypeScript against it, so any edit made by hand is reported only as
the generic "CONTRACT DEBT" — a message that names neither the file nor the
reason.

That is exactly how the Frontend verification stage died at 4975dbd: the
snapshot was regenerated on Python 3.11 with two PEP 695 declarations lowered
locally, and the lowering silently changed what pydantic emits for them. A
``type SettingValue = str | int | bool`` alias is hoisted into
``components.schemas`` and left as a ``$ref``; the hand-edit inlined the six
``$ref``s and deleted the component, so the document ended up defining nothing
while claiming otherwise.

The fourth check covers the other hand edit that survives all of the above:
reordering ``paths``. ``openapi-typescript`` prints keys in document order, so
a snapshot whose path order was rewritten still generates a file the contract
gate rejects -- again without saying which file or why. #25 did exactly that
when it spliced six ``/api/v1/comparative/*`` paths at their alphabetical
position and moved 222 of the 223 existing keys.

The second failure mode is subtler and cost a red frontend gate on main: the
snapshot and the generated client disagreed about *one* field family, because
``scripts/export_contract.py`` restated a pydantic serialization detail through
a hand-kept list of field names that had gone stale. A snapshot generated
while the list covered half of ``GeneDetail`` froze ``default: null`` on those
fields and omitted it on the rest; from then on every real export disagreed
with it, and the diff only said "CONTRACT DEBT".

The contract these tests state is the one that makes the gate meaningful:

* the normalizer is a pure function of the document — it owns exactly one
  spelling of an optional nullable field, and applying it twice changes
  nothing; and
* the snapshot and the generated client declare the same field set per
  schema, so one of them being regenerated without the other shows up here
  instead of as "CONTRACT DEBT"; and
* the snapshot is a fixed point of the normalizer, so a file frozen before
  its schemas grew cannot sit in the tree looking authoritative while every
  real export disagrees with it.

The checks below need neither Python 3.15 nor the API virtualenv, so they run
in the dependency-free contracts layer and name the actual cause.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parents[1] / "packages/api-client/openapi.json"
GENERATED = SNAPSHOT.parent / "src/generated/openapi.d.ts"
COMPONENT_PREFIX = "#/components/schemas/"


def _document() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        target = node.get("$ref")
        if isinstance(target, str):
            yield target
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _component_names(document: dict[str, Any]) -> set[str]:
    return set(document.get("components", {}).get("schemas", {}))


def _component_refs(document: dict[str, Any]) -> set[str]:
    return {
        ref[len(COMPONENT_PREFIX) :]
        for ref in _refs(document)
        if ref.startswith(COMPONENT_PREFIX)
    }


def test_every_component_ref_resolves() -> None:
    document = _document()
    dangling = sorted(_component_refs(document) - _component_names(document))
    assert dangling == [], (
        "packages/api-client/openapi.json references component(s) it does not "
        f"define: {dangling}. That file is an export, not a source file — run "
        "`pnpm --filter @soymutdb/api-client generate:api-client` under Python "
        "3.15 instead of patching the JSON."
    )


def test_generated_client_only_names_defined_components() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    named = set(re.findall(r'components\["schemas"\]\["([^"]+)"\]', text))
    missing = sorted(named - _component_names(_document()))
    assert missing == [], (
        "src/generated/openapi.d.ts names component(s) the snapshot does not "
        f"define: {missing}. Regenerate both files together."
    )


def test_hoisted_type_aliases_are_actually_referenced() -> None:
    """A pure alias component no model points at is a hand-inlined alias.

    Request and response models are referenced from ``paths``, so they are
    never orphans. A component with neither ``properties`` nor ``enum`` is a
    hoisted type alias; if nothing ``$ref``s it, something inlined it by hand.
    """
    document = _document()
    schemas = document.get("components", {}).get("schemas", {})
    aliases = {
        name
        for name, schema in schemas.items()
        if isinstance(schema, dict)
        and "properties" not in schema
        and "enum" not in schema
    }
    orphans = sorted(aliases - _component_refs(document))
    assert orphans == [], (
        f"alias component(s) {orphans} are defined but never referenced: the "
        "snapshot was hand-edited to inline them. Regenerate it."
    )


def test_generated_client_keeps_snapshot_path_order() -> None:
    """``openapi.d.ts`` must list ``paths`` in the snapshot's own order.

    ``openapi-typescript`` prints ``paths`` in document order unless
    ``--alphabetize`` is passed, so a snapshot whose path order was rewritten
    still generates a file that ``check:contract`` rejects while every key is
    present and every reference resolves. Reordering is the only hand edit that
    survives the three checks above, so it gets its own.
    """
    snapshot_paths = list(_document().get("paths", {}))
    generated_paths = re.findall(
        r'^    "(/[^"]*)": \{$', GENERATED.read_text(encoding="utf-8"), re.M
    )
    if generated_paths == snapshot_paths:
        return
    index, snapshot, generated = next(
        (
            (index, snapshot, generated)
            for index, (snapshot, generated) in enumerate(
                zip(snapshot_paths, generated_paths)
            )
            if snapshot != generated
        ),
        (None, "<end>", "<end>"),
    )
    raise AssertionError(
        f"src/generated/openapi.d.ts lists {generated!r} at position {index} "
        f"where the snapshot lists {snapshot!r}: the snapshot's path order was "
        "rewritten by hand. `openapi-typescript` prints paths in document "
        "order, so the snapshot must keep FastAPI's router-registration order "
        "-- run `pnpm --filter @soymutdb/api-client generate:api-client` under "
        "Python 3.15 instead of reordering the JSON."
    )


# ---------------------------------------------------------------------------
# The normalizer: one spelling for an optional nullable field
# ---------------------------------------------------------------------------

EXPORT_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "packages/api-client/scripts/export_contract.py"
)


def _export_module() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("export_contract", EXPORT_SCRIPT)
    assert spec and spec.loader, f"cannot load {EXPORT_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document_with_optional_fields() -> dict[str, Any]:
    """A minimal document exercising every spelling the normalizer must unify."""

    return {
        "components": {
            "schemas": {
                name: {
                    "properties": {
                        "values": {"additionalProperties": {}},
                        "changes": {"additionalProperties": {}},
                        "default": {},
                    },
                    "type": "object",
                }
                for name in (
                    "SettingsDocumentResponse",
                    "SettingsHistoryItem",
                    "SettingsPatchRequest",
                    "SettingsValidateRequest",
                    "SettingsValidateResponse",
                    "SettingFieldSchema",
                )
            }
        }
    }


def test_normalizer_owns_both_spellings_of_an_optional_nullable_field() -> None:
    """``default: null`` present or absent must land on the same shape."""

    module = _export_module()
    document = _document_with_optional_fields()
    properties = {
        "with_default": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Optional",
        },
        "without_default": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "title": "Optional",
        },
        "required_with_default": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Required",
        },
        "non_null_default": {"type": "string", "default": "x", "title": "Non Null"},
    }
    document["components"]["schemas"]["Sample"] = {
        "properties": properties,
        "required": ["required_with_default"],
        "type": "object",
    }

    normalized = module.normalize(document)["components"]["schemas"]["Sample"][
        "properties"
    ]

    assert normalized["with_default"] == normalized["without_default"], (
        "an optional nullable field keeps `default: null` depending on which "
        "export produced it — that is the drift the frontend contract gate "
        "reports as CONTRACT DEBT"
    )
    assert "default" not in normalized["without_default"]
    assert normalized["required_with_default"]["default"] is None, (
        "a required field's default is a real contract statement and must survive"
    )
    assert normalized["non_null_default"]["default"] == "x"


def test_normalizer_is_idempotent() -> None:
    """Normalizing twice must be a byte-level no-op."""

    module = _export_module()
    document = _document_with_optional_fields()
    document["components"]["schemas"]["Sample"] = {
        "properties": {
            "optional": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Optional",
                "description": "kept",
            }
        },
        "type": "object",
    }

    once = module.normalize(json.loads(json.dumps(document)))
    twice = module.normalize(json.loads(json.dumps(once)))
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


# ---------------------------------------------------------------------------
# The snapshot and the generated client agree on field shape
# ---------------------------------------------------------------------------

_TS_SCHEMA_KEY = re.compile(r"^ {8}(?P<name>[A-Za-z_][A-Za-z0-9_]*): \{$")
_TS_TOP_LEVEL_END = re.compile(r"^ {4}\};$")
_TS_FIELD_START = re.compile(r"^ {12}(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_TS_FIELD_END = re.compile(r"^ {12}.*;\s*$")


def _schema_field_shapes(text: str) -> dict[str, list[str]]:
    """Map each schema name to the fields it declares.

    A field ``F`` of a schema starts a twelve-space line ``F: ...`` and ends
    at the terminating ``;`` of that declaration. Everything between the two
    belongs to the field (a nested object body), so a member of a nested
    object is never mistaken for a field of the schema.
    """

    schemas: dict[str, list[str]] = {}
    current: str | None = None
    pending: str | None = None
    for line in text.splitlines():
        if _TS_TOP_LEVEL_END.match(line):
            current = None
            pending = None
            continue
        key = _TS_SCHEMA_KEY.match(line)
        if key:
            current = key.group("name")
            schemas.setdefault(current, [])
            pending = None
            continue
        if current is None:
            continue
        if pending is None:
            field = _TS_FIELD_START.match(line)
            if field:
                schemas[current].append(field.group("name"))
                pending = field.group("name")
        if pending is not None and _TS_FIELD_END.match(line):
            pending = None
    return schemas


def test_generated_client_declares_every_snapshot_field() -> None:
    """The snapshot and the client must describe the same field set per schema.

    This is the local, Python-only half of the frontend contract gate: it
    cannot re-export the app (no 3.15 here), but it does catch the committed
    pair disagreeing — the state that made the gate red while both files
    looked plausible.
    """

    from_snapshot = {
        name: set(schema["properties"])
        for name, schema in _document().get("components", {}).get("schemas", {}).items()
        if isinstance(schema.get("properties"), dict)
    }
    from_client = _schema_field_shapes(GENERATED.read_text(encoding="utf-8"))

    mismatched: list[str] = []
    for name, fields in from_snapshot.items():
        client_fields = set(from_client.get(name, ()))
        if not client_fields:
            continue
        missing = sorted(fields - client_fields)
        extra = sorted(client_fields - fields)
        if missing:
            mismatched.append(
                f"{name}: in the snapshot, absent from the client: {missing}"
            )
        if extra:
            mismatched.append(
                f"{name}: in the client, absent from the snapshot: {extra}"
            )
    assert mismatched == [], (
        "packages/api-client/openapi.json and src/generated/openapi.d.ts "
        "disagree about these fields:\n  "
        + "\n  ".join(mismatched[:20])
        + "\nRegenerate both files together under Python 3.15: "
        "`pnpm --filter @soymutdb/api-client generate:api-client`."
    )


# ---------------------------------------------------------------------------
# The snapshot itself obeys the normalizer's rule
# ---------------------------------------------------------------------------


def test_snapshot_has_no_frozen_null_defaults() -> None:
    """No optional nullable field in the snapshot carries ``default: null``.

    This is the third shape of #33's failure and the one the checks above
    cannot see. ``export_contract.py`` unifies optional nullable properties by
    *removing* ``default: null``; a snapshot that still spells it on some
    fields was written before the fields existed (or by a stale export), and
    from then on every real export disagrees with it on exactly those fields.
    #23 added the comparative sections to ``GeneDetail`` and the snapshot kept
    seven of them flagged, so the gate failed on a document nobody had
    touched -- 20 fields, reported as "CONTRACT DEBT" with no file named.

    Applying the normalizer to the snapshot makes that state self-evident: a
    document that is already normalized is a fixed point of it. Neither the
    re-export nor the normalizer can run here (no Python 3.15, no API
    dependencies), but this states the same contract in the layer that runs
    without either.
    """

    module = _export_module()
    snapshot = _document()
    normalized = module.normalize(json.loads(json.dumps(snapshot)))
    if normalized == snapshot:
        return

    frozen: list[str] = []
    before = snapshot["components"]["schemas"]
    after = normalized["components"]["schemas"]
    for name, schema in before.items():
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict):
            continue
        for field, prop in properties.items():
            restored = after[name]["properties"][field]
            if prop != restored:
                frozen.append(f"{name}.{field}")
    raise AssertionError(
        "packages/api-client/openapi.json is not a fixed point of its own "
        f"normalizer: {len(frozen)} field(s) differ from the spelling the "
        f"export would write, e.g. {sorted(frozen)[:8]}. Those fields were "
        "frozen before the schema grew them, or a hand edit reinstated the "
        "spelling the normalizer removes -- either way every real export then "
        "disagrees with this file. Regenerate rather than patch: "
        "`pnpm --filter @soymutdb/api-client generate:api-client` under Python 3.15."
    )

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
import sys
from pathlib import Path
from typing import Any, Iterator

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
        ref[len(COMPONENT_PREFIX):]
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
# `title` is last in the `properties` table; the exemptions are named
# ---------------------------------------------------------------------------
# ``normalize()`` emits one spelling: every property object it rewrites prints
# ``title`` last. The snapshot is an export of that function, so ``title``
# follows ``description`` in every one of them.
#
# The hand edit this replaced is #35: `GeneDetail` carried pydantic 2.13
# spelling (``title`` first) on the nine fields a hand-kept list named and
# pydantic 2.14 spelling (``title`` last, no ``title`` beside a lone ``$ref``)
# on the other nineteen, while `SequenceAvailability` carried ``default: null``
# on four of its fields and not on the same four. Every real export therefore
# disagreed with the snapshot, and regenerating the snapshot "fixed" the diff
# only until the next export.

# What the rule below can hold is narrower than "the document speaks one
# dialect". ``_title_last`` owns the objects in a ``properties`` table; it
# never runs over a schema *root*, and it cannot reorder an object with no
# value keyword in it -- ``old_value: Any`` exports as the bare
# ``{"title": ...}``, which ``normalize()`` passes through. So the guard
# measures the properties table and names the bare-``title`` objects it has to
# leave alone, instead of comparing first keys of everything it can walk.

def _property_objects(
    node: Any, path: str = ""
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every object held in a ``properties`` table, schema roots excluded.

    This is the domain ``_title_last`` actually owns: ``_normalize_properties``
    rewrites ``node["properties"]`` and nothing else, so a schema *root* is not
    a property object no matter where it prints ``title``. FastAPI's
    ``get_definitions`` rebuilds every root as ``{field_name: json_schema}``,
    which is why ``properties`` leads all of them -- that is a fact about the
    exporter, not a spelling this file can hold an export to.
    """

    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, prop in properties.items():
                if isinstance(prop, dict):
                    yield f"{path}.{name}", prop
        for key, value in node.items():
            yield from _property_objects(value, f"{path}/{key}" if path else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _property_objects(value, f"{path}[{index}]")


#: Property objects that legitimately print ``title`` first, keyed by their
#: ``Schema.field`` name and mapped to the declaration responsible. Every one is
#: ``Any``, whose JSON schema is the bare ``{"title": ...}``: no value keyword
#: for ``_title_last`` to order in front of ``title``, no ``default`` for
#: ``_normalize_properties`` to restate, so ``normalize()`` carries it through
#: unchanged. That is not a dialect, it is outside the normalizer's reach -- and
#: the guard below says so by name instead of by omission, which is how a bare
#: ``{"title": ...}`` used to stay invisible to it.
_TITLE_FIRST_WITHOUT_A_VALUE = {
    "DataPatchItem.old_value": "apps/api/app/schemas/import_studio.py `old_value: Any`",
    "DataPatchItem.new_value": "apps/api/app/schemas/import_studio.py `new_value: Any`",
    "ValidationError.input": "fastapi.exception_handlers.ValidationError `input: Any`",
}


def _title_first_properties(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``Schema.field`` -> property object, for objects printing ``title`` first."""

    schemas = document.get("components", {}).get("schemas", {})
    return {
        path.lstrip("."): prop
        for path, prop in _property_objects(schemas)
        if "title" in prop and next(iter(prop)) == "title"
    }


def test_snapshot_prints_title_last_in_every_property_object() -> None:
    """``title`` comes last in every object of a ``properties`` table.

    ``normalize()`` restates one spelling for the properties it rewrites, and
    the snapshot is an export of it, so ``title`` follows ``description``. The
    assertion is aimed at the declaration side -- the field objects a hand edit
    touches -- because that is where a pasted-in pydantic spelling lands. Schema
    roots are outside it: no export here has ever ordered one.
    """

    found = _title_first_properties(_document())
    unexpected = sorted(set(found) - set(_TITLE_FIRST_WITHOUT_A_VALUE))
    assert unexpected == [], (
        "these properties print `title` first, which no pass of the normalizer "
        f"emits: {unexpected}. Either the snapshot was edited by hand "
        "(`pnpm --filter @soymutdb/api-client generate:api-client` under Python "
        "3.15), or a field that used to be `Any` grew a value keyword and "
        "`_title_last` can now order it."
    )


def test_title_first_exemptions_are_still_bare_titles() -> None:
    """Each exemption is still present, and still a lone ``title``.

    An exemption that silently covers a property whose shape changed is how
    this guard goes blind: once one of these grows ``type``, the exclusion
    would still excuse the new object, and once one disappears the exclusion
    would excuse whatever is declared in its place. Both directions are
    asserted so the stale exemption fails here, by name, before it can hide a
    real drift.
    """

    found = _title_first_properties(_document())
    assert sorted(found) == sorted(_TITLE_FIRST_WITHOUT_A_VALUE), (
        "the `title`-first exemption list no longer matches the snapshot; "
        f"missing: {sorted(set(_TITLE_FIRST_WITHOUT_A_VALUE) - set(found))}, "
        f"unexpected: {sorted(set(found) - set(_TITLE_FIRST_WITHOUT_A_VALUE))}. "
        "Drop or replace the stale entry in `_TITLE_FIRST_WITHOUT_A_VALUE`."
    )
    for name in sorted(found):
        assert list(found[name]) == ["title"], (
            f"`{name}` ({_TITLE_FIRST_WITHOUT_A_VALUE[name]}) is exempt from "
            "the `title`-last rule only because it is `Any`, i.e. its schema "
            f"is a bare `title`. It now prints {sorted(found[name])}, so "
            "`_title_last` can order it and the exemption is hiding a drift."
        )


def test_dialect_guard_notices_a_property_edited_in_place() -> None:
    """Writing a field back in pydantic spelling is named, not tolerated."""

    document = _document()
    properties = document["components"]["schemas"]["GeneDetail"]["properties"]
    original = properties["gene_id"]
    properties["gene_id"] = {"title": original["title"], **original}

    assert "GeneDetail.gene_id" in _title_first_properties(document), (
        "the guard did not notice a property object rewritten with `title` "
        "first -- this is the hand edit #35 left behind on nine `GeneDetail` "
        "fields, and the reason this test exists"
    )


def test_dialect_guard_ignores_schema_roots() -> None:
    """Ordering the schema roots is not a property-object spelling.

    Every export here leads each root with ``properties``, but that comes from
    FastAPI rebuilding the definitions table, so a document whose roots lead
    with ``title`` is not evidence of a hand edit and must not turn the guard
    red. A guard that reports those instead is comparing the wrong domain.
    """

    document = _document()
    schemas = document["components"]["schemas"]
    rotated: dict[str, Any] = {}
    for name, schema in schemas.items():
        head = {"title": schema["title"]} if "title" in schema else {}
        rotated[name] = {**head, **{k: v for k, v in schema.items() if k != "title"}}
    document["components"]["schemas"] = rotated

    assert _title_first_properties(document) == _title_first_properties(_document()), (
        "rotating the schema roots changed what the guard reports: it is "
        "still measuring schema roots, a domain `_title_last` never touches"
    )


def test_snapshot_keeps_null_defaults_on_optional_fields() -> None:
    """Every optional nullable field must carry ``default: null``.

    ``openapi-typescript`` renders ``default: null`` as the plain
    ``string | null`` and its absence as an *optional* ``string | null``, so
    dropping it from the snapshot is a client-visible contract change: a field
    consumers read without a guard becomes possibly-undefined. A normalizer
    that restates ``default: null`` by hand gets this wrong in both directions
    once its list goes stale -- #35 restored ten of ``GeneDetail``'s twenty
    nullable fields and dropped it from the four it still knew about.
    """

    missing: list[str] = []
    for name, schema in _document().get("components", {}).get("schemas", {}).items():
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        required = set(schema.get("required", ()))
        for field, prop in properties.items():
            if field in required or not isinstance(prop, dict):
                continue
            if not any(
                branch.get("type") == "null" for branch in prop.get("anyOf", ())
            ):
                continue
            if "default" not in prop:
                missing.append(f"{name}.{field}")
    assert missing == [], (
        "optional nullable fields lost `default: null`, which the generated "
        "client renders as an optional property:\n  "
        + "\n  ".join(missing[:20])
        + "\nRegenerate the snapshot with "
        "`pnpm --filter @soymutdb/api-client generate:api-client`."
    )


# ---------------------------------------------------------------------------
# The snapshot is a fixed point of the normalizer that produces it
# ---------------------------------------------------------------------------
# ``scripts/export_contract.py`` owns one spelling of an optional nullable
# field and one key order for every property. A snapshot that a *different*
# spelling was hand-written into still passes the checks above -- every
# reference resolves, one dialect throughout, ``default: null`` on all 584
# optional fields -- while disagreeing with every real export. That is how
# ``main`` kept a red frontend gate on a backend nobody had touched, so the
# fixed point gets its own check.


def _export_module() -> Any:
    """Import the export script without needing the API virtualenv."""

    import importlib.util

    path = SNAPSHOT.parent / "scripts/export_contract.py"
    spec = importlib.util.spec_from_file_location("_export_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document_with_optional_fields() -> dict[str, Any]:
    """The minimum a normalizer needs: the settings documents it touches."""

    schemas: dict[str, Any] = {}
    for name in (
        "SettingsDocumentResponse",
        "SettingsHistoryItem",
        "SettingsPatchRequest",
        "SettingsValidateRequest",
        "SettingsValidateResponse",
        "SettingFieldSchema",
    ):
        properties: dict[str, Any] = {
            "values": {"additionalProperties": {}},
            "changes": {"additionalProperties": {}},
            "default": {},
        }
        schemas[name] = {"properties": properties, "type": "object"}
    return {"components": {"schemas": schemas}, "paths": {}}


def _export_bytes(document: dict[str, Any]) -> str:
    """Serialize exactly as ``export_contract.py:main`` writes the snapshot.

    ``check-contract.sh`` compares a fresh export against the committed file
    with ``diff -q``, i.e. as text, so key order is part of what it checks.
    ``json.dumps(..., sort_keys=True)`` calls two documents equal when only
    key order moved -- the ``_ORDERED_KEYS`` ``description`` incident drifted
    87 lines that way while every semantic guard stayed green. Fixed point
    and idempotence therefore compare these bytes, not a sorted reserialize.
    """

    return json.dumps(document, indent=2)


def test_snapshot_is_a_fixed_point_of_the_export_normalizer() -> None:
    """Re-normalizing the committed snapshot must be a byte-level no-op.

    The snapshot is an export, so it has to be the bytes the export produces.
    A snapshot carrying a spelling the normalizer would rewrite -- including
    a *key order* it would restate -- is exactly the drift ``check:contract``
    reports as CONTRACT DEBT against a backend that did not move. Comparing
    ``sort_keys=True`` here used to hide that whole class of drift.

    Mutation that must redden this test: re-adding ``description`` to
    ``_ORDERED_KEYS`` (the pre-rebase hybrid) moves 87 lines and leaves the
    parsed document semantically identical.
    """

    module = _export_module()
    document = _document()
    normalized = module.normalize(json.loads(json.dumps(document)))

    assert _export_bytes(normalized) == SNAPSHOT.read_text(encoding="utf-8"), (
        "packages/api-client/openapi.json is not what "
        "scripts/export_contract.py:normalize emits, byte for byte -- "
        "`check:contract` will report drift on a backend nobody changed. Run "
        "`pnpm --filter @soymutdb/api-client generate:api-client`."
    )


def test_export_byte_helper_sees_key_order() -> None:
    """The fixed point's byte helper must not collapse into a semantic compare.

    Pins ``_export_bytes`` itself: ``check-contract.sh`` diffs export files as
    text, so a helper that reserialized with ``sort_keys=True`` would blind the
    byte-level fixed-point check exactly as the original ``sort_keys=True``
    assertion did. A key-only reordering must therefore change these bytes.

    Mutation that must redden this test: give ``_export_bytes`` a
    ``sort_keys=True``. It does *not* police how the fixed-point test calls
    the helper -- that behaviour is pinned by re-adding ``description`` to
    ``_ORDERED_KEYS``, which reddens the fixed-point test itself (87 lines).
    """

    ordered = {"type": "string", "description": "kept"}
    moved = {"description": "kept", "type": "string"}
    assert json.dumps(ordered, sort_keys=True) == json.dumps(moved, sort_keys=True), (
        "premise: a key-only reordering is invisible under sort_keys=True"
    )
    assert _export_bytes(ordered) != _export_bytes(moved), (
        "_export_bytes collapsed key order: the fixed-point check is now "
        "semantic and `diff -q` will keep finding drift the unit tests cannot"
    )


def test_normalizer_is_idempotent() -> None:
    """Normalizing twice must be a byte-level no-op."""

    module = _export_module()
    document = _document_with_optional_fields()
    document["components"]["schemas"]["Sample"] = {
        "properties": {
            "optional": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "description": "kept",
                "title": "Optional",
            }
        },
        "type": "object",
    }

    once = module.normalize(json.loads(json.dumps(document)))
    twice = module.normalize(json.loads(json.dumps(once)))
    assert _export_bytes(once) == _export_bytes(twice)


def test_normalizer_owns_one_spelling_of_an_optional_nullable_field() -> None:
    """Present or absent, an optional nullable field lands on one shape."""

    module = _export_module()
    document = _document_with_optional_fields()
    document["components"]["schemas"]["Sample"] = {
        "properties": {
            "with_default": {
                "title": "Optional",
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "without_default": {
                "title": "Optional",
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
            "required_with_default": {
                "title": "Required",
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
            "non_null_default": {
                "type": "string",
                "default": "x",
                "title": "Non Null",
            },
        },
        "required": ["required_with_default"],
        "type": "object",
    }

    properties = module.normalize(document)["components"]["schemas"]["Sample"][
        "properties"
    ]

    assert properties["with_default"] == properties["without_default"], (
        "an optional nullable field keeps `default: null` depending on which "
        "export produced it -- the drift reported as CONTRACT DEBT"
    )


def test_normalizer_flattens_both_title_dialects_to_one_spelling() -> None:
    """``title`` last, whichever position the export printed it in.

    Restating "where this property's own export put ``title``" is not a
    contract, so it is not carried into the snapshot either: an export that
    prints ``title`` first and one that prints it last have to normalize to
    the same bytes, or the document records a dialect instead of a schema and
    every real export disagrees with half of it. The marker that used to ride
    in ``description`` for this never reached a snapshot -- nothing wrote it,
    so both directions collapsed into ``title``-last anyway; this states that
    outcome as the contract rather than leaving it to chance.
    """

    module = _export_module()
    title_first = {"title": "Extra", "type": "string", "description": "A new field."}
    title_last = {"type": "string", "description": "A new field.", "title": "Extra"}

    # ``==`` ignores key order, which is the only thing this check is about.
    def spelling(prop: dict[str, Any]) -> str:
        return json.dumps(module._title_last(dict(prop)))

    assert spelling(title_first) == spelling(title_last), (
        "the normalizer keeps the dialect each property was exported with, so "
        "two exports of one schema never agree -- the drift reported as "
        "CONTRACT DEBT"
    )
    assert spelling(title_first) == json.dumps(title_last)


def test_normalizer_prunes_unreferenced_nested_definitions() -> None:
    """A nested ``$defs`` block keeps only what the subschema ``$ref``s.

    FastAPI copies a nested ``model_json_schema()`` into the components table
    whole, ``$defs`` included, and ``_normalize_properties`` cannot reach
    inside it -- the definitions live below the ``properties`` table, and that
    walker only rewrites ``node["properties"]``. Left alone, a definition the
    schema no longer references survives into the snapshot as if it were part
    of the contract, and its key order is whatever its own export printed.
    """

    module = _export_module()
    document = _document_with_optional_fields()
    document["components"]["schemas"]["Sample"] = {
        "properties": {
            "detail": {
                "allOf": [{"$ref": "#/$defs/ErrorDetail"}],
                "title": "Detail",
            }
        },
        "$defs": {
            "ErrorDetail": {
                "properties": {
                    "message": {"title": "Message", "type": "string"},
                },
                "type": "object",
            },
            "Unreferenced": {
                "properties": {},
                "type": "object",
            },
        },
        "type": "object",
    }

    schema = module.normalize(document)["components"]["schemas"]["Sample"]

    assert sorted(schema["$defs"]) == ["ErrorDetail"], (
        "an unreferenced nested definition survived into the snapshot: it is "
        "not resolvable contract, and each one keeps its own pydantic dialect"
    )
    property_ = schema["$defs"]["ErrorDetail"]["properties"]["message"]
    assert next(reversed(property_)) == "title", (
        "a definition inside a nested `$defs` kept its exported key order -- "
        "the `properties` walker does not descend into `$defs`"
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
    assert properties["required_with_default"]["default"] is None, (
        "a required field's default is a real contract statement and must survive"
    )
    assert properties["non_null_default"]["default"] == "x"



def test_every_schema_object_carries_the_snapshot_key_order() -> None:
    """No schema may print its object keys in pydantic's order.

    Most checks above compare documents with ``sort_keys=True`` or by value,
    so a schema whose *keys* are in the wrong order but whose *content* is
    identical is invisible to them -- while ``check-contract.sh`` compares the
    two export files as text with ``diff -q``, so it does see it and reports
    CONTRACT DEBT for a schema nobody edited. The fixed-point check above is
    byte-level; this one guards the order the normalizer emits per schema.

    That is the fifth shape of the same failure. pydantic emits ``required``
    before ``title``/``type``; the snapshot carries ``type`` before
    ``required``. The normalizer only ever reordered *property* objects, so a
    schema with nothing else to shuffle kept pydantic's order.
    """

    module = _export_module()

    examples = {
        "properties": 1,
        "type": "object",
        "required": ["a"],
        "title": "Sample",
        "description": "kept last",
    }
    expected = ["properties", "type", "required", "title", "description"]
    ordered = module._object_last(dict(examples))
    assert list(ordered) == expected, (
        "the normalizer's schema key order drifted from the snapshot's: "
        f"{list(ordered)} != {expected}"
    )
    # ``dict ==`` ignores order, so this line says "the pairing survived", not
    # "the keys moved": it would pass on an ``_object_last`` that returned its
    # argument untouched, and it would pass on one that printed the very order
    # the assertion above rejects. The order question is ``list(ordered)``,
    # one line up. Keep that split when judging a failure here -- reading this
    # line as an order check costs a round of analysis, because it looks like
    # the hole this test exists to close.
    assert ordered == examples, "reordering must not change or drop a value"

    assert list(module._OBJECT_KEY_ORDER) == [
        "properties",
        "additionalProperties",
        "type",
        "required",
        "title",
        "description",
        "$defs",
    ], (
        "the normalizer's key order drifted from the order asserted above: "
        f"{list(module._OBJECT_KEY_ORDER)}"
    )

    # ``_object_last`` has to *move* keys, not merely return them. The checks
    # below ask whether a schema is already canonical, and an implementation
    # that is the identity answers "yes" for every schema -- including a
    # scrambled one. So state the behaviour on a deliberately non-canonical
    # shape first: pydantic's order (``title`` before ``required``) plus an
    # unknown keyword, which must survive in place after the known ones.
    #
    # The inputs are plain dicts on purpose: the document is read with
    # ``json.loads``, whose objects print insertion order, so the failure
    # analysis for the real snapshot is done in plain dicts too.
    scrambled = {
        "description": "kept last",
        "title": "Sample",
        "required": ["a"],
        "deprecated": True,
        "type": "object",
        "properties": 1,
    }
    permuted = module._object_last(dict(scrambled))
    assert list(permuted) != list(scrambled), (
        "`_object_last` returned its argument unchanged for a schema whose keys "
        f"are in pydantic's order ({list(scrambled)}), so it cannot tell a "
        "canonical document from a scrambled one and the check below passes "
        "whatever the snapshot holds"
    )
    assert list(permuted) == [
        "properties",
        "type",
        "required",
        "title",
        "description",
        "deprecated",
    ], f"`_object_last` put the keys in an unexpected order: {list(permuted)}"
    # Same split as above: values here, positions in the ``list(permuted)``
    # assertion. ``dict ==`` cannot fail on a reordering, so a red line in this
    # file is a moved or dropped *value*, never a moved key.
    assert permuted == scrambled, "reordering must not change or drop a value"

    # ``deprecated`` above survives because the re-emitter has a second loop
    # for keys outside the order -- so the assertion above passes for a
    # `_object_last` whose order table lists only *some* of the keywords a
    # schema can carry. The gap that leaves is not "drops an unknown key" but
    # "silently skips a known one": a keyword the table omits is copied by the
    # catch-all loop, so the value survives and only its position drifts,
    # which the per-schema check below still reads as canonical because it
    # judges by the same incomplete table.
    #
    # Ask the question directly instead of by proxy: every keyword held by a
    # schema whose own order the normalizer is responsible for has to be a
    # member. Anything else is a keyword the normalizer hoists or strands by
    # accident -- it would win a `diff -q` against a real export only for as
    # long as no schema grows it.
    #
    # No keyword is exempt, trailing ones included: ``$defs`` sits last on the
    # two error schemas that carry it, but it is still a member here and
    # dropping it from ``_OBJECT_KEY_ORDER`` reddens this assertion by name.
    #
    # That assertion is the *only* thing standing between a trailing keyword
    # and silence. ``_object_last``'s catch-all loop copies any key the table
    # omits, and ``_wrong_order`` below judges a keyword's position solely
    # against the table -- so for a key the table does not list, the value
    # survives and the order check reads "canonical" whether it is or not.
    # The two error schemas are what make this check bite for ``$defs`` today;
    # a ``$defs`` mounted somewhere the scan does not reach (a ``$ref`` alias,
    # a nested schema) would not appear in ``unlisted`` at all.
    schemas = _document().get("components", {}).get("schemas", {})
    unlisted = {
        keyword
        for schema in schemas.values()
        if isinstance(schema, dict) and "properties" in schema
        for keyword in schema
        if keyword not in module._OBJECT_KEY_ORDER
    }
    assert unlisted == set(), (
        "`_OBJECT_KEY_ORDER` does not list every keyword the snapshot prints on "
        f"a schema object: {sorted(unlisted)}. `_object_last` still keeps such a "
        "keyword (its second loop copies it), so nothing else notices -- but the "
        "key gets appended instead of placed, and whether that matches a real "
        "export is then luck rather than order. Add it to `_OBJECT_KEY_ORDER` "
        "in the position the snapshot prints it."
    )

    #: The order a schema object must print, ``additionalProperties`` included
    #: because it is what a schema with free-form values carries.
    canonical = list(module._OBJECT_KEY_ORDER)

    def _wrong_order(keys: list[str]) -> bool:
        """True when ``keys`` is not an order-preserving subsequence of ``canonical``.

        Key order is the *whole* schema object, unknown keywords included,
        exactly as ``diff -q`` reads it. This is the half of the contract that
        catches a stale snapshot, and it is written against ``canonical``
        rather than by calling ``_object_last`` so that a no-op implementation
        cannot mark everything as already ordered.

        Subsequence, not prefix: the question is whether the known keys keep
        their relative order, so a schema may skip ``additionalProperties``
        and still be canonical (most do -- only a free-form ``dict`` carries
        it). Requiring ``known`` to be a leading run of ``canonical`` would
        fail the common ``properties, type, required, title`` at the fourth
        position and redden most of the snapshot.
        """

        known = [key for key in keys if key in canonical]
        return known != [key for key in canonical if key in keys]

    def _loses_keys(node: dict[str, Any]) -> bool:
        """True when reordering drops or rewrites something.

        The normalizer runs over the whole document, so a reordering that
        silently discarded ``required`` or an unknown keyword would edit the
        contract on the way to making it print nicely.

        Compares the key *set* and the values, never the order: order is
        ``_wrong_order``'s question. Comparing key sequences here would flag
        every lossless reordering -- 320 of the snapshot's schemas -- and, since
        the check below is an ``or``, that false positive would mask whatever
        the order half found. Comparing with ``!=`` alone is the opposite
        mistake: ``dict`` equality ignores order, so a reordering can never
        make it true and this half stops meaning anything.
        """

        reordered = module._object_last(dict(node))
        return sorted(reordered) != sorted(node) or any(
            reordered[key] != node[key] for key in reordered
        )

    misplaced = [
        name
        for name, schema in schemas.items()
        if isinstance(schema, dict)
        and "properties" in schema
        and (_wrong_order(list(schema)) or _loses_keys(schema))
    ]
    assert misplaced == [], (
        "these schemas are not in the key order a fresh export prints, so "
        f"`diff -q` in check-contract.sh reports them as CONTRACT DEBT: {sorted(misplaced)}\n"
        "Regenerate rather than patch: "
        "`pnpm --filter @soymutdb/api-client generate:api-client` under Python 3.15."
    )


# ---------------------------------------------------------------------------
# The snapshot may gain paths and schemas, never lose them
# ---------------------------------------------------------------------------
# Every check above asks whether the snapshot is *well formed*: refs resolve,
# properties print one spelling, the normalizer is a fixed point. None of them
# asks how much of the API is still in it, and `check-contract.sh` cannot: it
# diffs the snapshot against an export of whatever the backend currently
# declares, so a snapshot that lost paths **together with** the backend code
# that used to serve them agrees with itself byte for byte and the gate stays
# green while the client quietly drops endpoints.
#
# That is not hypothetical here. A rebase took `packages/api-client/openapi.json`
# from 236 paths / 359 schemas back to an older 226 / 331, the whole 16-test
# guard suite above passed on it, and the loss was only visible by recounting
# the document by hand. So the counts get a floor: the snapshot may not shrink
# below what it last declared, and the floor below is raised by the same commit
# that adds API surface, never lowered to match a shrink.
#
# Numbers only, on purpose. Naming a path or a schema would make this a list to
# keep in sync with every backend change; a count floor catches the shape of the
# accident -- many entries leaving at once, which is what a bad merge looks
# like -- and cannot silently "fix" itself the way a name list can.

#: `(paths, schemas)` the snapshot must keep at least. Raise when the API grows.
#: A change that legitimately removes API surface has to edit this line, which
#: is the point: removing an endpoint becomes a decision someone writes down.
_SNAPSHOT_FLOOR = (236, 359)


def test_snapshot_does_not_lose_paths_or_schemas() -> None:
    """The snapshot may not shrink below the last declared floor.

    Reads the committed snapshot, not an export, so it fires on the artifact
    itself rather than on the difference between the artifact and a backend
    that moved with it.
    """

    document = _document()
    paths = len(document.get("paths", {}))
    schemas = len(document.get("components", {}).get("schemas", {}))
    floor_paths, floor_schemas = _SNAPSHOT_FLOOR

    assert paths >= floor_paths, (
        f"packages/api-client/openapi.json declares {paths} paths, below the "
        f"{floor_paths} it is known to have. {floor_paths - paths} endpoints "
        "left the contract. This is what a bad merge of the snapshot looks "
        "like, and `check:contract` cannot see it when the backend moved with "
        "it. Regenerate: `pnpm --filter @soymutdb/api-client "
        "generate:api-client` under Python 3.15 -- if the removal is "
        "intentional, lower `_SNAPSHOT_FLOOR` in the same commit and say why."
    )
    assert schemas >= floor_schemas, (
        f"packages/api-client/openapi.json declares {schemas} schemas, below "
        f"the {floor_schemas} it is known to have. "
        f"{floor_schemas - schemas} component types left the contract. "
        "Regenerate: `pnpm --filter @soymutdb/api-client generate:api-client` "
        "under Python 3.15."
    )


def test_snapshot_contract_is_runnable_without_pytest() -> None:
    """A direct run must execute the suite, not silently exit 0.

    ``python3 scripts/test_openapi_snapshot_contract.py`` used to print
    nothing and exit 0: with no ``__main__`` block, the module simply defined
    the tests. An empty stdout plus rc=0 reads as a pass to anything that only
    checks the exit code -- worse than a visible FAIL. Keep the runner and its
    success/failure output pinned here.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":\n    raise SystemExit(_run())' in source
    assert "print(" + "_SUCCESS_LINE)" in source
    assert 'print(f"openapi-snapshot-contract: FAIL' in source
    assert "file=sys.stderr" in source


def _run() -> int:
    """Run every ``test_*`` function directly, without pytest."""
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            problems.append(f"{test.__name__}: {exc or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"openapi-snapshot-contract: FAIL: {problem}", file=sys.stderr)
        return 1
    _SUCCESS_LINE = f"openapi-snapshot-contract: OK ({len(tests)} checks)"
    print(_SUCCESS_LINE)
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())

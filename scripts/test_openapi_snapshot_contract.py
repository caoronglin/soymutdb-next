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
# A snapshot entry may not mix pydantic serialization dialects
# ---------------------------------------------------------------------------
# The committed snapshot is an export, so every object in it was printed by the
# pydantic that produced it. Those dialect differences are not contract
# changes, and a normalizer that restates *some* fields by hand ends up with
# both dialects inside one schema.
#
# That is the state #35 left behind and the reason the frontend contract gate
# stayed red: `GeneDetail` carried pydantic 2.13 spelling (``title`` first) on
# the nine fields a hand-kept list named and pydantic 2.14 spelling
# (``title`` last, no ``title`` beside a lone ``$ref``) on the other nineteen,
# while `SequenceAvailability` carried ``default: null`` on four of its fields
# and not on the same four. Every real export therefore disagreed with the
# snapshot, and regenerating the snapshot "fixed" the diff only until the next
# export.

#: Keys whose presence means "this object describes a value", which is when
#: pydantic decides where ``title`` goes.
_VALUE_KEYS = ("anyOf", "oneOf", "allOf", "$ref", "type", "items", "enum")


def _value_objects(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        if any(key in node for key in _VALUE_KEYS):
            yield path, node
        for key, value in node.items():
            yield from _value_objects(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _value_objects(value, f"{path}[{index}]")


def test_snapshot_speaks_one_pydantic_dialect() -> None:
    """No schema may carry both ``title``-first and ``title``-last spelling.

    A document that mixes them cannot have come from one export, so the gate
    will report CONTRACT DEBT for a schema nobody edited.
    """

    schemas = _document().get("components", {}).get("schemas", {})
    mixed: list[str] = []
    for name, schema in schemas.items():
        spellings = set()
        for _, node in _value_objects(schema):
            if "title" not in node:
                continue
            spellings.add(next(iter(node)) == "title")
        if len(spellings) > 1:
            mixed.append(name)
    assert mixed == [], (
        "these schemas mix pydantic serialization dialects (some fields print "
        f"`title` first, others last): {sorted(mixed)}\n"
        "The snapshot was regenerated by hand. Run "
        "`pnpm --filter @soymutdb/api-client generate:api-client` under Python 3.15."
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


def test_snapshot_is_a_fixed_point_of_the_export_normalizer() -> None:
    """Re-normalizing the committed snapshot must change nothing.

    The snapshot is an export, so it has to be what the export produces. A
    snapshot carrying a spelling the normalizer would rewrite is exactly the
    drift ``check:contract`` reports as CONTRACT DEBT against a backend that
    did not move.
    """

    module = _export_module()
    document = _document()
    normalized = module.normalize(json.loads(json.dumps(document)))

    assert json.dumps(normalized, sort_keys=True) == json.dumps(
        document, sort_keys=True
    ), (
        "packages/api-client/openapi.json is not what "
        "scripts/export_contract.py:normalize emits -- `check:contract` will "
        "report drift on a backend nobody changed. Run "
        "`pnpm --filter @soymutdb/api-client generate:api-client`."
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
    assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True)


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

    Every check above compares documents with ``sort_keys=True``, so a schema
    whose *keys* are in the wrong order but whose *content* is identical is
    invisible to all of them -- while ``check-contract.sh`` compares the two
    export files as text with ``diff -q``, so it does see it and reports
    CONTRACT DEBT for a schema nobody edited.

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
        """

        return module._object_last(dict(node)) != node

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

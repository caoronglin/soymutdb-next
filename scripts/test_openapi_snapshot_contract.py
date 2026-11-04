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

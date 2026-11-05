#!/usr/bin/env python3
"""Pin the published schema ``required`` arrays to an independent literal.

``openapi.json`` publishes 1076 ``(schema path, required field)`` declarations
across 282 component schemas, including the seven nested ``$defs`` copies that
pydantic emits for the error envelopes. They are part of the public contract:
``openapi-typescript`` renders each one as a non-optional property in the
generated ``components["schemas"]`` interface, while every other field gets a
``?``. A client compiled against the document relies on that distinction.

No other fixed point reads requiredness:

* ``_FIELD_CONSTRAINT_DIGEST`` walks the JSON Schema *constraint keywords*
  (``minimum`` / ``maxLength`` / ...), not the ``required`` array;
* ``_OPERATION_ID_DIGEST`` / ``_PARAMETER_DIGEST`` / ``_RESPONSE_SURFACE_DIGEST``
  / ``_ANNOTATION_DIGEST`` pin operations, not component property schemas;
* ``_BODY_PAIR_DIGEST`` / ``_INLINE_BODY_BASELINE`` read which component a body
  names, not the fields inside it;
* the published-enum baseline walks value domains, the document-metadata lock
  walks top-level ``info``/``tags``;
* ``test_openapi_snapshot_contract.py`` compares *field sets* between the two
  artifacts and checks nullable defaults, but never asserts which fields are
  required -- a coordinated regenerate that moves both halves together keeps
  that equality true;
* ``_PINNED_ARTIFACTS`` records blob ids: re-pinning both is the documented
  "one deliberate reviewed action" beside a regenerate.

Decisive ablation on live bytes: byte-preserving removal of one field from a
``required`` array in the snapshot, the matching ``field: T`` -> ``field?: T``
in the generated client, and re-pinning both blob ids leaves all ten wired
OpenAPI guards, their ``--self-test`` suites and the whole contracts layer
``SMOKE PASS``. The generated TypeScript silently changes a guaranteed field
into an optional one -- a client-visible contract break nothing pins.

The same blindness covers a second, adjacent surface: the positional and
cardinality keywords ``prefixItems`` / ``minProperties`` / ``maxProperties`` /
``discriminator``. None of the fixed points above names them, because none is
a scalar in ``_FIELD_CONSTRAINT_DIGEST``'s ``_KEYS`` vocabulary:

* ``prefixItems`` renders as a **positional tuple type** --
  ``query_range: [number, number];``. Retyping the second slot to ``string``
  and regenerating emits ``[number, string]``; a caller that passed an array
  of two numbers now fails to type-check. Four published tuples carry it.
* ``minProperties`` / ``maxProperties`` bound a free-form map (``values: {}``,
  ``config: {}``) that the generator renders as an index signature, which
  cannot express the bound at all -- so no two-artifact comparison can see it
  and the runtime is the only other reader.
* ``discriminator`` names the property a client must switch on. The generator
  drops it entirely and prints a ``@constant`` note instead, so it has no
  second half either.

Decisive ablation on live bytes ``ebfa4c5f``: a byte-preserving
``query_range`` second slot ``integer -> string`` in the snapshot, the matching
``number, number`` -> ``number, string`` in the generated tuple, both
``_PINNED_ARTIFACTS`` blob ids honestly re-pinned -- all eleven wired
``check_openapi_*`` guards ``rc=0``, all wired ``test_openapi_*`` suites green,
``smoke.sh --profile contracts`` ``SMOKE PASS / 922 passed``.

This guard reads committed bytes only (``json`` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. It pins:

* ``_REQUIRED_FIELD_DIGEST`` -- a hand-written sha256 over the canonical sorted
  ``(schema path, field)`` rows, read from nowhere. Exported from the snapshot
  alone, so a co-revert of both halves still changes it;
* ``_EXPECTED_REQUIRED_ROWS`` / ``_EXPECTED_SCHEMAS`` / ``_EXPECTED_BY_SCHEMA``
  -- exact count doors that a same-count permutation cannot satisfy alone;
* the generated client's per-component optional-marker set, so a one-sided
  edit that makes a field optional in only one half is named by schema and
  field. The client half is checked against the *pinned* required rows, not
  against the snapshot, so a coordinated regenerate cannot pass by agreement.

A legitimate contract change must move the digest in the same commit as both
artifacts and say why. Re-deriving the digest from the artifact under guard
would make the pin self-referential. ``--self-test`` injects one-sided and
coordinated drifts into copies of the bytes and asserts each is caught; the
clean tree must pass.

The component-to-component ``$ref`` wiring is a third surface in the same
file: 229 property-level refs inside ``components.schemas``, across 145 owner
schemas and 140 targets. ``openapi-typescript`` renders each as a
``components["schemas"]["<target>"]`` line in that owner's generated block.
No landed fixed point reads *which* component a property points at: the
snapshot contract only checks a ref resolves, the body baselines only read
``$ref`` bodies under ``paths``, and ``_PINNED_ARTIFACTS`` is re-pinned in the
same deliberate act as a regenerate. A byte-preserving swap of two array-item
refs inside ``AdminDashboardSeries`` in BOTH halves, with both blob ids
honestly re-pinned, left every wired guard and ``SMOKE PASS`` green on live
``c3e88a49b``. It is a pure permutation: counts, owners, targets and the
``(owner, target)`` multiset are unchanged, so only a *positional* literal can
see it. ``_SCHEMA_REF_DIGEST`` (snapshot path rows) and the independent
``_CLIENT_SCHEMA_REF_DIGEST`` (client field/target rows) are those two fixed
points; Door 8 names a one-sided edit by owner, field and target.

Usage:
    python3 scripts/check_openapi_required_fields.py
    python3 scripts/check_openapi_required_fields.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
GENERATED = ROOT / "packages" / "api-client" / "src" / "generated" / "openapi.d.ts"
SELF = Path(__file__).name

# Reviewed, hand-written fixed point on the whole published required surface.
# sha256 of "\n".join(["soymutdb-required-fields/v1"] +
#   sorted(f"{path}|{field}")) over every `required` array in
#   components.schemas, including nested $defs copies. Regenerate with
# _digest() after an intentional contract change and update in the same commit,
# with a reason.
_REQUIRED_FIELD_DIGEST = (
    "2e190b58340d795b673704d4cdab0e1b0a54d20b53b77abb505b533d2f82dccc"
)
_EXPECTED_REQUIRED_ROWS = 1076
_EXPECTED_SCHEMAS = 282

# Reviewed, hand-written fixed point on the published positional/cardinality
# surface. sha256 of "\n".join(["soymutdb-tuple-and-map-bounds/v1"] +
#   sorted(f"{path}|{keyword}|{json.dumps(value, sort_keys=True)}")) over every
# `prefixItems` / `minProperties` / `maxProperties` / `discriminator` node in
# components.schemas, including nested $defs copies. Read from nowhere.
#
# Kept as its own literal, not folded into _REQUIRED_FIELD_DIGEST: requiredness
# is a set of field names, these are ordered slots and integer bounds. Folding
# them together would make "the tuple's second slot is now a string" read as
# "a required field moved", and the failure reason would lose its resolution.
# Regenerate with _value_digest() after an intentional contract change and
# update in the same commit as both artifacts, with a reason.
_VALUE_KEYWORDS: tuple[str, ...] = (
    "prefixItems",
    "minProperties",
    "maxProperties",
    "discriminator",
)
_VALUE_DIGEST = (
    "ff2adb536d60aa1174b2e4e69951826cd3376f6742aeacb7f2cac1fce19df7c2"
)
_EXPECTED_VALUE_ROWS = 9
_EXPECTED_VALUE_BY_KEYWORD: dict[str, int] = {
    "discriminator": 1,
    "maxProperties": 2,
    "minProperties": 2,
    "prefixItems": 4,
}

# A component's own required-array length, keyed by its top-level name.
# 282 exact doors: a same-count permutation that moves one field from schema
# A to schema B keeps the total and the digest's multiset shape is not enough
# on its own, so these are checked too. Kept as a literal floor.
_EXPECTED_BY_SCHEMA_TOP: dict[str, int] = {}  # filled by _by_schema_top() below

# Independent fixed point on the component-to-component ``$ref`` wiring.
# ``components.schemas`` publishes 229 property-level ``$ref`` nodes across 145
# owner schemas, naming 140 distinct targets. ``openapi-typescript`` renders
# each one as a ``components["schemas"]["<target>"]`` line inside that owner's
# block in the generated client -- the TypeScript a consumer compiles against.
# No landed fixed point reads *which* component a property points at:
# ``test_openapi_snapshot_contract.py`` only checks every ref resolves to a
# defined name, and the body-integrity baselines only pin ``$ref`` bodies under
# ``paths.*.responses`` / ``requestBody``, never the wiring inside a schema.
#
# Decisive ablation on live bytes: swap the two array-item refs inside
# ``AdminDashboardSeries`` (``ImportThroughputPoint`` <-> ``QueryLatencyPoint``)
# in BOTH artifacts and honestly re-pin the two provenance blob ids -- every
# wired ``check_openapi_*`` guard, every ``test_openapi_*`` suite and the whole
# contracts layer stay ``rc=0`` / green, while the generated client silently
# types one field as the other model. Two independent literals are the fix:
# re-pinning only the snapshot side cannot silence the client door, and a
# co-revert that makes both halves agree still moves both digests.
_SCHEMA_REF_DIGEST = (
    "9cf04fbccc712ae8a19fab2af092a60ffba16a8c98016bac0c952b0fa321cbc2"
)
_EXPECTED_SCHEMA_REF_ROWS = 229
_EXPECTED_SCHEMA_REF_OWNERS = 145
_EXPECTED_SCHEMA_REF_TARGETS = 140

# The generated half is pinned by a *second* independent literal, not derived
# from the snapshot under guard. sha256 of the canonical sorted
# ``(owner, target, occurrence index)`` rows of the client's
# ``components["schemas"]["..."]`` lines. Read from nowhere.
_CLIENT_SCHEMA_REF_DIGEST = (
    "5f08c6ae449843991de05c9a230b5160f4555708435eb4ea040dd5884b7bb8c1"
)
_EXPECTED_CLIENT_SCHEMA_REF_ROWS = 229


def rows(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Canonical (schema path, required field) rows over every required array."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            required = node.get("required")
            if isinstance(required, list):
                for field in required:
                    if isinstance(field, str):
                        out.append((path, field))
            for name, value in node.items():
                if name == "required" or not isinstance(value, (dict, list)):
                    continue
                walk(value, f"{path}/{name}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, name)
    return out


def _digest(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{path}|{field}" for path, field in rows_)
    blob = "\n".join(["soymutdb-required-fields/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def value_rows(document: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Canonical (schema path, keyword, value) rows for the value keywords.

    Walks the same tree as :func:`rows`, so a nested ``$defs`` copy is pinned
    too. A property literally *named* like a keyword is not the keyword; only a
    key that holds the keyword does, which is what a plain dict lookup gives.
    """
    out: list[tuple[str, str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for keyword in _VALUE_KEYWORDS:
                if keyword in node:
                    out.append((path, keyword, node[keyword]))
            for name, value in node.items():
                walk(value, f"{path}/{name}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, name)
    return out


def _value_digest(rows_: list[tuple[str, str, Any]]) -> str:
    canonical = sorted(
        f"{path}|{keyword}|{json.dumps(value, sort_keys=True)}"
        for path, keyword, value in rows_
    )
    blob = "\n".join(["soymutdb-tuple-and-map-bounds/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _by_keyword(rows_: list[tuple[str, str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, keyword, _ in rows_:
        counts[keyword] = counts.get(keyword, 0) + 1
    return counts


def _by_schema_top(rows_: list[tuple[str, str]]) -> dict[str, int]:
    """Count required entries by their top-level component name."""
    counts: dict[str, int] = {}
    for path, _ in rows_:
        top = path.split("/")[0]
        counts[top] = counts.get(top, 0) + 1
    return counts


# Published client-side optional markers. ``openapi-typescript`` prints every
# non-required property as ``name?:`` inside the component block. Only direct
# properties are matched (one indentation level below the block opener); nested
# inline object types are read as part of the snapshot's own rows instead.
_COMPONENT_BLOCK = re.compile(
    r"^        (?P<name>[A-Za-z_][A-Za-z0-9_]*): \{\n(?P<body>.*?)^        \};$",
    re.M | re.S,
)
_OPTIONAL_PROP = re.compile(r"^            (?P<name>[A-Za-z_][A-Za-z0-9_]*)\?:", re.M)

# A ``prefixItems`` array is rendered as a bracketed positional tuple, one
# indentation level below the property name. This shape alone is a tuple: an
# ordinary array renders as ``name: T[];`` and never matches.
_TUPLE_PROP = re.compile(
    r"^            (?P<name>[A-Za-z_][A-Za-z0-9_]*)\??: \[\n"
    r"(?P<members>(?:                [^\n]*\n)+?)"
    r"            \];$",
    re.M,
)


def client_optional(generated: str) -> dict[str, set[str]]:
    """component name -> set of fields rendered optional (``field?: T``)."""
    out: dict[str, set[str]] = {}
    for match in _COMPONENT_BLOCK.finditer(generated):
        out[match.group("name")] = set(
            _OPTIONAL_PROP.findall(match.group("body"))
        )
    return out


# JSON Schema scalar type -> the TypeScript type the generator prints. The
# map is deliberately narrow: a slot outside it renders as something this door
# does not model, and :func:`_ts_slot` says so loudly rather than guessing, so
# a new slot type cannot quietly turn Door 5 into a vacuous comparison.
_TS_SCALARS = {
    "integer": "number",
    "number": "number",
    "string": "string",
    "boolean": "boolean",
}


def _ts_slot(slot: Any) -> str:
    """The TypeScript type ``openapi-typescript`` prints for one tuple slot.

    A published ``anyOf: [T, null]`` renders as ``T | null``; a bare scalar
    renders as its TypeScript equivalent. Anything else is reported as
    ``UNMODELLED(...)`` -- distinct from every modelled type, so an unexpected
    slot always disagrees with the generated half instead of passing.
    """
    if not isinstance(slot, dict):
        return f"UNMODELLED({json.dumps(slot, sort_keys=True)})"
    branches = slot.get("anyOf")
    if isinstance(branches, list):
        rendered = []
        for branch in branches:
            if isinstance(branch, dict) and branch.get("type") == "null":
                rendered.append("null")
            else:
                rendered.append(_ts_slot(branch))
        return " | ".join(rendered)
    scalar = slot.get("type")
    if isinstance(scalar, str) and scalar in _TS_SCALARS:
        return _TS_SCALARS[scalar]
    return f"UNMODELLED({json.dumps(slot, sort_keys=True)})"


def generated_tuples(generated: str) -> dict[tuple[str, str], tuple[str, ...]]:
    """(component, field) -> rendered positional tuple members.

    ``openapi-typescript`` prints a ``prefixItems`` array as a bracketed tuple
    one indentation level below the property name. Only that exact shape is
    read, so an ordinary ``T[]`` property is never mistaken for a tuple.
    """
    out: dict[tuple[str, str], tuple[str, ...]] = {}
    for block in _COMPONENT_BLOCK.finditer(generated):
        component = block.group("name")
        for match in _TUPLE_PROP.finditer(block.group("body")):
            members = tuple(
                line.strip().rstrip(",")
                for line in match.group("members").strip().splitlines()
                if line.strip()
            )
            out[(component, match.group("name"))] = members
    return out


def schema_ref_rows(document: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Canonical (owner, dotted path, target) rows for every intra-schema ref.

    Only ``#/components/schemas/...`` refs *inside* ``components.schemas`` are
    read: the path-level body refs are owned by the body-integrity baselines,
    and folding them here would make one failure name two different surfaces.
    """
    out: list[tuple[str, str, str]] = []

    def walk(node: Any, path: str, owner: str) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                out.append((owner, path, ref.split("/")[-1]))
            for name, value in node.items():
                if name != "$ref":
                    walk(value, f"{path}/{name}" if path else name, owner)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}", owner)

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, "", name)
    return out


def _schema_ref_digest(rows_: list[tuple[str, str, str]]) -> str:
    canonical = sorted(f"{owner}|{path}|{target}" for owner, path, target in rows_)
    blob = "\n".join(["soymutdb-schema-ref-wiring/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def client_schema_ref_rows(generated: str) -> list[tuple[str, str, str, str]]:
    """Canonical (owner, field, target, occurrence index) rows from the client.

    Reads only the ``components.schemas`` interface block, so a
    ``parameters`` / ``responses`` / ``requestBody`` sub-block (also 8-space
    indented) cannot be mistaken for a component definition. Each ref line's
    property name is captured, so a same-count *permutation* that swaps two
    targets between two fields moves the client digest just as it moves the
    snapshot's positional digest -- a multiset of targets alone would be
    blind to exactly that drift.
    """
    start = generated.find("export interface components {")
    if start < 0:
        return []
    schemas_at = generated.find("    schemas: {", start)
    if schemas_at < 0:
        return []
    lines = generated[schemas_at:].splitlines(keepends=True)
    close = next(
        (i for i, line in enumerate(lines) if i > 0 and line.rstrip("\n") == "    };"),
        len(lines),
    )
    block = "".join(lines[:close])
    defs = list(re.finditer(r"^        ([A-Za-z_][A-Za-z0-9_]*): \{$", block, re.M))
    # One property line may name the target: "field?: components[...][...];",
    # "[key: string]: components[...][...];", or a union "T | null;".
    ref_line = re.compile(
        r'^[ \t]+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*)|'
        r'\[key: string\])\??:[^\n;]*?components\["schemas"\]\["([^"]+)"\]',
        re.M,
    )
    out: list[tuple[str, str, str, str]] = []
    for i, match in enumerate(defs):
        end = defs[i + 1].start() if i + 1 < len(defs) else len(block)
        body = block[match.start() : end]
        seen: dict[tuple[str, str], int] = {}
        for prop in ref_line.finditer(body):
            field = prop.group(1) or prop.group(2) or "[key: string]"
            target = prop.group(3)
            key = (field, target)
            index = seen.get(key, 0)
            seen[key] = index + 1
            out.append((match.group(1), field, target, str(index)))
    return out


def _client_schema_ref_digest(rows_: list[tuple[str, str, str, str]]) -> str:
    canonical = sorted(
        f"{owner}|{field}|{target}|{index}"
        for owner, field, target, index in rows_
    )
    blob = "\n".join(["soymutdb-client-schema-ref-wiring/v2", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _ref_field(path: str) -> str:
    """The generated client's field name for a snapshot $ref path.

    ``properties/<field>/...`` maps to ``<field>``; a free-form map's
    ``properties/<field>/additionalProperties`` renders in the client as an
    index signature ``[key: string]`` rather than the declared field name.
    """
    parts = path.split("/")
    if len(parts) > 1 and parts[0] == "properties":
        if "additionalProperties" in parts:
            return "[key: string]"
        return parts[1]
    return path


def _ref_multiset(rows_: list[tuple[str, str, str]]) -> dict[tuple[str, str], int]:
    """(owner, target) -> count, the shape both halves must agree on."""
    out: dict[tuple[str, str], int] = {}
    for owner, _path, target in rows_:
        out[(owner, target)] = out.get((owner, target), 0) + 1
    return out

def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    digest: str | None = None,
    expected_rows: int | None = None,
    expected_schemas: int | None = None,
    value_digest: str | None = None,
    expected_value_rows: int | None = None,
    value_by_keyword: dict[str, int] | None = None,
    schema_ref_digest: str | None = None,
    client_ref_digest: str | None = None,
    expected_ref_rows: int | None = None,
    expected_ref_owners: int | None = None,
    expected_ref_targets: int | None = None,
    expected_client_ref_rows: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = GENERATED.read_text(encoding="utf-8")
    try:
        document = json.loads(snapshot)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published required fields from snapshot: {exc}"]
    rows_ = rows(document)
    pinned_digest = _REQUIRED_FIELD_DIGEST if digest is None else digest
    pinned_rows = (
        _EXPECTED_REQUIRED_ROWS if expected_rows is None else expected_rows
    )
    pinned_schemas = (
        _EXPECTED_SCHEMAS if expected_schemas is None else expected_schemas
    )
    pinned_value_digest = _VALUE_DIGEST if value_digest is None else value_digest
    pinned_value_rows = (
        _EXPECTED_VALUE_ROWS if expected_value_rows is None else expected_value_rows
    )
    pinned_by_keyword = (
        _EXPECTED_VALUE_BY_KEYWORD if value_by_keyword is None else value_by_keyword
    )
    value_rows_ = value_rows(document)
    pinned_ref_digest = (
        _SCHEMA_REF_DIGEST if schema_ref_digest is None else schema_ref_digest
    )
    pinned_client_ref_digest = (
        _CLIENT_SCHEMA_REF_DIGEST
        if client_ref_digest is None
        else client_ref_digest
    )
    pinned_ref_rows = (
        _EXPECTED_SCHEMA_REF_ROWS if expected_ref_rows is None else expected_ref_rows
    )
    pinned_ref_owners = (
        _EXPECTED_SCHEMA_REF_OWNERS
        if expected_ref_owners is None
        else expected_ref_owners
    )
    pinned_ref_targets = (
        _EXPECTED_SCHEMA_REF_TARGETS
        if expected_ref_targets is None
        else expected_ref_targets
    )
    pinned_client_ref_rows = (
        _EXPECTED_CLIENT_SCHEMA_REF_ROWS
        if expected_client_ref_rows is None
        else expected_client_ref_rows
    )
    ref_rows_ = schema_ref_rows(document)
    client_ref_rows_ = client_schema_ref_rows(generated)

    # Door 1 -- independent fixed point over the whole surface.
    actual = _digest(rows_)
    if actual != pinned_digest:
        found.append(
            "published required fields drifted: _REQUIRED_FIELD_DIGEST pins "
            f"{pinned_digest} but the snapshot derives {actual}. A baseline is "
            "a fixed point for the artifact, not a place to make a guard agree "
            "with itself -- re-pin the digest in the same commit as both "
            "artifacts, with a reason."
        )

    # Door 2 -- exact shape doors. These name a drop/add without relying on the
    # digest alone, and make a same-count permutation visible in the counts.
    if len(rows_) != pinned_rows:
        found.append(
            f"published required row count is {len(rows_)}, "
            f"_EXPECTED_REQUIRED_ROWS pins {pinned_rows}: a required field was "
            "added or dropped without moving the fixed point"
        )
    observed = _by_schema_top(rows_)
    if len(observed) != pinned_schemas:
        found.append(
            f"required fields span {len(observed)} component schemas, "
            f"_EXPECTED_SCHEMAS pins {pinned_schemas}"
        )

    # Door 3 -- the generated client half. Check it against the *pinned* rows,
    # not against the snapshot, so a coordinated regenerate cannot pass by
    # making both halves agree on a drift.
    required_by_component: dict[str, set[str]] = {}
    for path, field in rows_:
        if "/" in path:  # nested $defs copies have no standalone TS block
            continue
        required_by_component.setdefault(path, set()).add(field)
    optional = client_optional(generated)
    for name, required in sorted(required_by_component.items()):
        if name not in optional and required:
            continue  # a component with no optional fields renders no `?` lines
        wrongly_optional = optional.get(name, set()) & required
        if wrongly_optional:
            found.append(
                f"generated client renders required field(s) optional in "
                f"{name}: {', '.join(sorted(wrongly_optional))}"
            )

    # Door 4 -- independent fixed point over the positional/cardinality
    # keywords no other pin names. A tuple slot retyped, a map bound moved, or
    # a discriminator dropped moves this digest; a coordinated regenerate of
    # both artifacts (with the blob ids honestly re-pinned) does not save it.
    actual_value = _value_digest(value_rows_)
    if actual_value != pinned_value_digest:
        found.append(
            "published tuple/map keywords drifted: _VALUE_DIGEST pins "
            f"{pinned_value_digest} but the snapshot derives {actual_value}. "
            "A prefixItems slot, a minProperties/maxProperties bound or a "
            "discriminator is part of the client contract -- re-pin the digest "
            "in the same commit as both artifacts, with a reason."
        )
    if len(value_rows_) != pinned_value_rows:
        found.append(
            f"published tuple/map keyword row count is {len(value_rows_)}, "
            f"_EXPECTED_VALUE_ROWS pins {pinned_value_rows}"
        )
    observed_by_keyword = _by_keyword(value_rows_)
    if observed_by_keyword != pinned_by_keyword:
        changed = [
            f"{keyword} {pinned_by_keyword.get(keyword, 0)}"
            f"->{observed_by_keyword.get(keyword, 0)}"
            for keyword in sorted(
                set(pinned_by_keyword) | set(observed_by_keyword)
            )
            if pinned_by_keyword.get(keyword, 0)
            != observed_by_keyword.get(keyword, 0)
        ]
        found.append(
            "published tuple/map keyword counts changed: " + ", ".join(changed)
        )

    # Door 5 -- the generated half must agree with the *snapshot* tuple arity
    # and member order. Checked against the snapshot rather than a pinned
    # literal because the snapshot side is already frozen by Door 4: this door
    # exists to name a one-sided edit, and to prove the tuple is rendered at
    # all. A ``prefixItems`` dropped from the snapshot cannot hide here.
    rendered = generated_tuples(generated)
    snapshot_tuples: dict[tuple[str, str], list[str]] = {}
    for name, schema in document.get("components", {}).get("schemas", {}).items():
        for prop, prop_schema in (schema.get("properties") or {}).items():
            if not isinstance(prop_schema, dict):
                continue
            slots = prop_schema.get("prefixItems")
            if isinstance(slots, list):
                snapshot_tuples[(name, prop)] = [_ts_slot(slot) for slot in slots]
    for (component, field), expected_slots in sorted(snapshot_tuples.items()):
        members = rendered.get((component, field))
        if members is None:
            found.append(
                f"generated client no longer renders {component}.{field} as a "
                f"positional tuple ({len(expected_slots)} slots published)"
            )
        elif list(members) != expected_slots:
            found.append(
                f"generated client renders {component}.{field} as "
                f"[{', '.join(members)}], the snapshot publishes "
                f"[{', '.join(expected_slots)}]"
            )
    for (component, field) in sorted(rendered):
        if (component, field) not in snapshot_tuples:
            found.append(
                f"generated client renders {component}.{field} as a tuple the "
                "snapshot does not publish"
            )

    # Door 6 -- independent fixed point on the component-to-component $ref
    # wiring, read from the snapshot alone. A coordinated regenerate of both
    # artifacts (with the provenance blob ids honestly re-pinned) still moves
    # this literal, because it is derived from neither half.
    actual_ref = _schema_ref_digest(ref_rows_)
    if actual_ref != pinned_ref_digest:
        found.append(
            "published component $ref wiring drifted: _SCHEMA_REF_DIGEST pins "
            f"{pinned_ref_digest} but the snapshot derives {actual_ref}. "
            "Re-pin the digest in the same commit as both artifacts, with a "
            "reason; re-deriving it from the artifact under guard would make "
            "the pin agree with itself."
        )
    if len(ref_rows_) != pinned_ref_rows:
        found.append(
            f"published component $ref row count is {len(ref_rows_)}, "
            f"_EXPECTED_SCHEMA_REF_ROWS pins {pinned_ref_rows}: an intra-schema "
            "reference was added or dropped without moving the fixed point"
        )
    owners = {row[0] for row in ref_rows_}
    targets = {row[2] for row in ref_rows_}
    if len(owners) != pinned_ref_owners:
        found.append(
            f"component $ref wiring spans {len(owners)} owner schemas, "
            f"_EXPECTED_SCHEMA_REF_OWNERS pins {pinned_ref_owners}"
        )
    if len(targets) != pinned_ref_targets:
        found.append(
            f"component $ref wiring names {len(targets)} distinct targets, "
            f"_EXPECTED_SCHEMA_REF_TARGETS pins {pinned_ref_targets}"
        )

    # Door 7 -- a *second* independent fixed point, over the generated client's
    # own ref lines. Re-pinning only the snapshot digest cannot silence this
    # door, and a co-revert that makes both halves agree still moves both.
    actual_client_ref = _client_schema_ref_digest(client_ref_rows_)
    if actual_client_ref != pinned_client_ref_digest:
        found.append(
            "generated component $ref wiring drifted: "
            f"_CLIENT_SCHEMA_REF_DIGEST pins {pinned_client_ref_digest} but the "
            f"client derives {actual_client_ref}. The two digests must move in "
            "the same commit as an intentional contract change."
        )
    if len(client_ref_rows_) != pinned_client_ref_rows:
        found.append(
            f"generated component $ref row count is {len(client_ref_rows_)}, "
            f"_EXPECTED_CLIENT_SCHEMA_REF_ROWS pins {pinned_client_ref_rows}"
        )

    # Door 8 -- named positional agreement. The two independent digests above
    # catch a coordinated co-revert; this door names a one-sided edit by
    # (owner, field, target) so a reviewer sees which property points at the
    # wrong model. It compares the *positional* shape, so a same-count swap
    # between two fields is reported too.
    snap_pos: dict[tuple[str, str, str], int] = {}
    for owner, path, target in ref_rows_:
        key = (owner, _ref_field(path), target)
        snap_pos[key] = snap_pos.get(key, 0) + 1
    cli_pos: dict[tuple[str, str, str], int] = {}
    for owner, field, target, _index in client_ref_rows_:
        key = (owner, field, target)
        cli_pos[key] = cli_pos.get(key, 0) + 1
    for key in sorted(set(snap_pos) | set(cli_pos)):
        if snap_pos.get(key, 0) != cli_pos.get(key, 0):
            found.append(
                f"component $ref target disagrees for "
                f"{key[0]}.{key[1]} -> {key[2]}: snapshot publishes "
                f"{snap_pos.get(key, 0)}, generated client publishes "
                f"{cli_pos.get(key, 0)}"
            )

    return found


def self_test() -> int:
    clean = failures()
    if clean:
        print(f"SELF-TEST FAIL: clean tree drifts: {clean}")
        return 1

    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    generated = GENERATED.read_text(encoding="utf-8")
    cases: dict[str, tuple[str, str]] = {}
    target = "AdminPluginResponse"

    # A coordinated regenerate: drop one field from required in the snapshot
    # and make the same field optional in the generated client.
    doc = copy.deepcopy(document)
    assert doc["components"]["schemas"][target]["required"] == ["key", "status"]
    doc["components"]["schemas"][target]["required"] = ["status"]
    ts = generated.replace(
        "        AdminPluginResponse: {\n            /** Key */\n            key: string;",
        "        AdminPluginResponse: {\n            /** Key */\n            key?: string;",
        1,
    )
    assert ts != generated
    cases["coordinated required drop (both halves)"] = (
        json.dumps(doc, indent=2),
        ts,
    )

    # One-sided: snapshot drops the field, client keeps it required.
    cases["one-sided snapshot required drop"] = (
        json.dumps(doc, indent=2),
        generated,
    )

    # One-sided: client alone makes the field optional.
    cases["one-sided client optional flip"] = (
        json.dumps(document, indent=2),
        ts,
    )

    # A required field invented on a schema that declares it, same row count.
    doc2 = copy.deepcopy(document)
    doc2["components"]["schemas"][target]["required"].append("manifest")
    cases["one-sided required field added"] = (
        json.dumps(doc2, indent=2),
        generated,
    )

    # A same-count permutation: swap a required field between two schemas.
    doc3 = copy.deepcopy(document)
    a = doc3["components"]["schemas"]["AdminPluginResponse"]["required"]
    b = doc3["components"]["schemas"]["AdminPluginsResponse"]["required"]
    assert a == ["key", "status"] and b == ["plugins"]
    a[0], b[0] = b[0], a[0]
    cases["same-count required permutation"] = (
        json.dumps(doc3, indent=2),
        generated,
    )

    # A nested $defs required array is part of the pinned surface too.
    doc4 = copy.deepcopy(document)
    detail = doc4["components"]["schemas"]["ErrorResponse"]["$defs"]["ErrorDetail"]
    assert detail["required"] == ["code", "message"]
    detail["required"] = ["code"]
    cases["nested $defs required drop"] = (
        json.dumps(doc4, indent=2),
        generated,
    )

    # --- the tuple/map surface (Doors 4 and 5). -------------------------

    # The coordinated regenerate this pin is here for: the second slot of a
    # published positional tuple retyped in the snapshot AND in the generated
    # tuple, so a caller who passed two numbers now fails to type-check.
    doc5 = copy.deepcopy(document)
    range_node = doc5["components"]["schemas"]["SequenceAlignResponse"][
        "properties"
    ]["query_range"]
    assert range_node["prefixItems"] == [{"type": "integer"}, {"type": "integer"}]
    range_node["prefixItems"] = [{"type": "integer"}, {"type": "string"}]
    ts5 = generated.replace(
        "            query_range: [\n"
        "                number,\n"
        "                number\n"
        "            ];",
        "            query_range: [\n"
        "                number,\n"
        "                string\n"
        "            ];",
        1,
    )
    assert ts5 != generated
    cases["coordinated tuple slot retype (both halves)"] = (
        json.dumps(doc5, indent=2),
        ts5,
    )

    # One-sided: the snapshot retypes the slot, the client keeps the old one.
    cases["one-sided snapshot tuple slot retype"] = (
        json.dumps(doc5, indent=2),
        generated,
    )

    # One-sided: the client alone retypes the slot. Door 4 is silent here (the
    # snapshot is untouched); Door 5 must name the disagreement, otherwise the
    # tuple door is a snapshot-only check wearing a two-half label.
    cases["one-sided client tuple slot retype"] = (
        json.dumps(document, indent=2),
        ts5,
    )

    # A map bound moved: same keyword, same row count, different value.
    doc6 = copy.deepcopy(document)
    config_node = doc6["components"]["schemas"]["ImportCommitRequest"][
        "properties"
    ]["config"]
    assert config_node["maxProperties"] == 32
    config_node["maxProperties"] = 33
    cases["coordinated maxProperties retype"] = (
        json.dumps(doc6, indent=2),
        generated,
    )

    # A discriminator dropped outright: the client loses the property name it
    # must switch on. Same-count by schema, so the count door cannot see it.
    doc7 = copy.deepcopy(document)
    target_node = doc7["components"]["schemas"]["SequenceMatchRequest"][
        "properties"
    ]["target"]
    assert "discriminator" in target_node
    target_node.pop("discriminator")
    cases["one-sided discriminator dropped"] = (
        json.dumps(doc7, indent=2),
        generated,
    )

    # A same-count rotation: the two map bounds swap values with each other,
    # so every count and the row set are unchanged and only the digest moves.
    doc8 = copy.deepcopy(document)
    a_node = doc8["components"]["schemas"]["ImportCommitRequest"]["properties"][
        "config"
    ]
    b_node = doc8["components"]["schemas"]["SettingsPatchRequest"]["properties"][
        "values"
    ]
    assert a_node["maxProperties"] == 32 and b_node["minProperties"] == 1
    a_node["maxProperties"], b_node["minProperties"] = 1, 32
    cases["same-count map bound rotation"] = (
        json.dumps(doc8, indent=2),
        generated,
    )

    # A tuple the snapshot publishes but the client stopped rendering.
    cases["client tuple rendering dropped"] = (
        json.dumps(document, indent=2),
        generated.replace(
            "            query_range: [\n"
            "                number,\n"
            "                number\n"
            "            ];",
            "            query_range: number[];",
            1,
        ),
    )

    # --- the component-to-component $ref wiring (Doors 6, 7 and 8). -------

    # The coordinated regenerate this pin is here for: swap two array-item
    # refs inside AdminDashboardSeries in BOTH halves. Every landed guard
    # stays green; the generated client silently types one field as the other.
    doc9 = copy.deepcopy(document)
    series = doc9["components"]["schemas"]["AdminDashboardSeries"]["properties"]
    assert series["import_throughput"]["items"]["$ref"].endswith(
        "ImportThroughputPoint"
    )
    assert series["query_latency"]["items"]["$ref"].endswith("QueryLatencyPoint")
    series["import_throughput"]["items"]["$ref"] = (
        "#/components/schemas/QueryLatencyPoint"
    )
    series["query_latency"]["items"]["$ref"] = (
        "#/components/schemas/ImportThroughputPoint"
    )
    ts9 = generated.replace(
        '            import_throughput?: components["schemas"]'
        '["ImportThroughputPoint"][];',
        '            import_throughput?: components["schemas"]'
        '["QueryLatencyPoint"][];',
        1,
    ).replace(
        '            query_latency?: components["schemas"]'
        '["QueryLatencyPoint"][];',
        '            query_latency?: components["schemas"]'
        '["ImportThroughputPoint"][];',
        1,
    )
    assert ts9 != generated
    cases["coordinated schema $ref swap (both halves)"] = (
        json.dumps(doc9, indent=2),
        ts9,
    )

    # One-sided: snapshot alone swaps the two refs. Door 6 and Door 8 name it.
    cases["one-sided snapshot $ref swap"] = (
        json.dumps(doc9, indent=2),
        generated,
    )

    # One-sided: client alone swaps the two refs. Door 7 and Door 8 name it.
    cases["one-sided client $ref swap"] = (
        json.dumps(document, indent=2),
        ts9,
    )

    # A same-count rotation that preserves every (owner, target) count: move
    # one ref to a third, already-referenced target on the same owner and
    # bring it back on a different property. The multiset is unchanged, so
    # only the positional snapshot digest can see it.
    doc10 = copy.deepcopy(document)
    s10 = doc10["components"]["schemas"]["AdminDashboardSeries"]["properties"]
    s10["storage_growth"]["items"]["$ref"] = (
        "#/components/schemas/ImportThroughputPoint"
    )
    cases["same-count schema $ref rotation"] = (
        json.dumps(doc10, indent=2),
        generated,
    )

    # Re-pinning only ONE of the two independent digests must not turn a
    # coordinated drift green: the client door stays red.
    found_one = failures(
        snapshot=json.dumps(doc9, indent=2),
        generated=ts9,
        schema_ref_digest=_schema_ref_digest(schema_ref_rows(doc9)),
    )
    assert any("_CLIENT_SCHEMA_REF_DIGEST" in item for item in found_one), found_one
    cases["only the snapshot digest re-pinned stays red"] = (
        json.dumps(doc9, indent=2),
        ts9,
    )

    failures_count = 0
    for name, (snap, gen) in cases.items():
        found = failures(snapshot=snap, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")
    print(f"self-test: {len(cases)} cases, {failures_count} failure(s)")
    return 1 if failures_count else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    found = failures()
    if found:
        for problem in found:
            print(f"openapi-required-fields: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-required-fields: OK ({_EXPECTED_REQUIRED_ROWS} published "
        f"required fields pinned across {_EXPECTED_SCHEMAS} schemas, "
        f"{_EXPECTED_VALUE_ROWS} tuple/map keyword rows pinned, "
        f"{_EXPECTED_SCHEMA_REF_ROWS} component $ref rows pinned across "
        f"{_EXPECTED_SCHEMA_REF_OWNERS} owners / "
        f"{_EXPECTED_SCHEMA_REF_TARGETS} targets)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

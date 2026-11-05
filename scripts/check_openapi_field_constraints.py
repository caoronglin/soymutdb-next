#!/usr/bin/env python3
"""Pin the published field-level constraints to an independent literal.

``openapi.json`` publishes 1712 field-level values -- 815 JSON Schema
constraint rows (``minimum``, ``maximum``, ``maxLength``, ``minLength``,
``pattern``, ``format``, item counts, exclusive bounds) plus 897 ``default``
values -- across 263 component schemas, and 7 published ``examples`` arrays on
property schemas. They are part of the public contract: a client generated from
this document can read them, and runtime validation enforces them. Unlike
``enum``/``const``, the constraints are not emitted in the generated
``openapi.d.ts``; ``default`` is rendered as ``@default`` and ``examples`` as
``@example``, so a coordinated regenerate can change one value in *both*
halves, re-pin the provenance blob ids, and leave every other wired fixed
point blind:

* ``_PUBLISHED_ENUM_BASELINE`` walks only ``enum`` / ``const``;
* ``_RESPONSE_BODY_BASELINE`` / ``_BODY_PAIR_DIGEST`` / the inline-body pins
  read bodies, not property schemas;
* the operationId, parameter, response-surface and document-metadata digests
  do not descend into ``components.schemas`` properties;
* ``_FIELD_CONSTRAINT_DIGEST`` walks the constraint/default keywords only --
  ``examples`` is a list-valued sibling, not one of ``_KEYS``;
* ``_PINNED_ARTIFACTS`` is provenance blob ids: re-pinning them is the
  documented "one reviewed action" beside a regenerate.

Decisive ablations on live bytes: byte-preserving ``maxItems: 100 -> 999`` in
the snapshot, a coordinated ``default: 0 -> 999999`` rewritten in the snapshot
and the generated ``@default`` line with both blob ids re-pinned, and all 7
``examples`` values rewritten in the snapshot *and* the generated ``@example``
tags with both blob ids honestly re-pinned -- all 12 wired OpenAPI guards, 12
OpenAPI test suites and the whole contracts layer (SMOKE PASS 922 passed) stay
green. Those coordinated shapes are why ``default`` and ``examples`` are pinned
here too, not left to a two-artifact comparison that a co-revert satisfies.

This guard reads committed bytes only (``json`` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. It pins:

* ``_FIELD_CONSTRAINT_DIGEST`` -- a hand-written sha256 over the canonical
  sorted ``(path, key, value)`` rows of every real schema node, read from
  nowhere. Re-deriving it from the artifacts under guard would be
  self-referential. A legitimate change re-pins it in the same commit as the
  snapshot, with a reason;
* ``_EXPECTED_CONSTRAINT_ROWS`` / ``_EXPECTED_SCHEMAS`` / ``_EXPECTED_BY_KEY``
  -- exact count doors that a same-count permutation cannot satisfy alone;
* ``_EXAMPLE_DIGEST`` -- a second hand-written sha256 over the canonical
  sorted ``(path, index, value)`` rows of every published ``examples`` array.
  It is deliberately separate from ``_FIELD_CONSTRAINT_DIGEST``: constraints
  and defaults are scalar keywords, examples are ordered lists of sample
  values. Folding them together would lose the failure resolution (a dropped
  ``@example`` tag would read as a constraint drift);
* ``_EXPECTED_EXAMPLES`` / ``_EXPECTED_GENERATED_EXAMPLES`` -- exact count
  doors on both halves. The generated half counts only strict ``* @example ``
  JSDoc markers: a ``@description`` blob containing ``user@example.com`` is
  a decoy that a naive ``'@example' in line`` scan would miscount as an 8th;
* door 8 -- the generated half's **values**, matched in order against the
  digest-pinned snapshot projection. Door 5 answers "how many tags"; door 8
  answers "what do they say". A one-sided rewrite of one ``@example`` value
  keeps all 7 tags, leaves the snapshot digest and both count doors silent,
  and -- once ``generated_blob`` is honestly re-pinned -- passes the whole
  contracts layer. The chain is independent at its root: ``_EXAMPLE_DIGEST``
  is a hand-written literal over the snapshot, and door 8 stands down when
  that digest does not match, so a snapshot-side drift is named by door 1
  with full failure resolution instead of being double-counted.
* door 11 -- the **field** each generated ``@example`` tag is printed under.
  Door 8 compares a flat, unlabelled value sequence; two doc blocks publishing
  the same value can exchange a tag without moving that sequence. Dropping the
  tag from ``LoginRequest.username`` and adding a second one to
  ``LoginRequest.email`` keeps all 7 tags, leaves the snapshot and both count
  doors intact, and -- with ``generated_blob`` honestly re-pinned -- passed the
  whole layer ``SMOKE PASS``. ``generated_example_rows()`` labels each tag
  with its component and field (``finditer``, so a second tag in one block is
  seen), and ``example_projection()`` reads the digest-pinned snapshot the
  same way. Compared per field, values in order: a dropped tag names one field
  instead of shifting blame onto every later one. Door 11 stands down when the
  snapshot digest or the tag cardinality drifts, and door 8 stands down when
  door 11 is on, so a drift is named once with full resolution.
* door 12 -- an **independent literal** for the 7 generated ``@example``
  values. Doors 8 and 11 both read the snapshot as their reference, while the
  generator reads ``openapi.d.ts``: a regenerate that moves one value in
  *both* halves is invisible to any two-artifact comparison, and the only
  surviving witness (``_EXAMPLE_DIGEST``) is exactly the literal a regenerate
  requires you to re-pin, honestly, with a reason. Sorting the property
  blocks cannot see it either. ``_GENERATED_EXAMPLE_VALUE_DIGEST`` is a
  hand-written sha256 over canonical ``(component, field, value)`` rows read
  from the generated bytes and from nowhere else, in the
  ``_DEFAULT_TAG_VALUE_DIGEST`` mould. It closes the coordinated both-halves
  cell for the 7 values the way door 7 closes it for the 896 defaults; a
  reviewed regenerate re-pins it in the same commit as both artifacts.
* a one-sided drop, add, retype or move of any single constraint/example is
  named by its path, so the failure says which field changed.

Division of labour is pinned by positive controls, not asserted in prose: a
same-count ``examples`` value swap must make *only* ``_EXAMPLE_DIGEST`` fire
(the two count doors stay silent), while dropping one generated ``@example``
tag must make *only* the generated count door fire. Otherwise door 5 would be
nothing but a count check wearing a digest-shaped coat.

The 897 ``default`` values also have a *second* published half: the generator
renders 896 of them as ``@default`` JSDoc tags in ``openapi.d.ts`` (the one
``InlineTarget.kind`` discriminator becomes a literal type instead). #282
folded ``default`` into the digest but carried no floor on that generated
half: deleting a tag and honestly re-pinning both provenance blob ids left
every wired guard green. ``_DEFAULT_TAG_DIGEST`` is a second hand-written
sha256 over the canonical ``(component, field)`` tag rows, read from the
committed generated bytes rather than derived from the snapshot under guard.
It is checked against the *pinned* projection, so a regenerate that drops a
tag cannot pass by agreement. Unlike the strict ``@example`` marker, the
tag rows are positional: a same-count relocation between two fields is
caught only by the digest, with both count doors silent.

``additionalProperties`` is a separate published shape: 102 component-schema
nodes declare a boolean or a schema value, rendered as a ``[key: string]``
index signature in the generated client (the 35 ``false`` nodes render no line
at all). It is not in ``_KEYS``, and no two-artifact comparison can see a
``false`` node. A coordinated regenerate that flips one node in both halves,
honestly re-pins both provenance blob ids and leaves every other door green
was measured on live bytes. Two more independent literals close it:
``_ADDITIONAL_PROPERTIES_DIGEST`` over the canonical ``(path, value)`` rows,
``_CLIENT_ADDITIONAL_PROPERTIES_DIGEST`` over the generated
``(component, index-signature type)`` rows, plus exact count doors and a
one-sided consistency door that names the component.

A legitimate contract change must move the digests in the same commit as the
snapshot and say why. Re-deriving a digest from the artifacts under guard
would make the pin self-referential. ``--self-test`` injects one-sided and
coordinated drifts into copies of the bytes and asserts each is caught; the
clean tree must pass.

#297 pins the *presence and location* of those 896 tags -- ``(component,
field)`` rows -- but not the published value written in the tag. A single
retyped ``@default 10000 -> @default 9999`` with ``generated_blob`` honestly
re-pinned keeps Door 6 and every other wired guard green (``SMOKE PASS``).
``_DEFAULT_TAG_VALUE_DIGEST`` is a second independent literal over
``(component, field, value)`` triples, so the client-visible fallback value
has a fixed point too. Kept separate from ``_DEFAULT_TAG_DIGEST``: folding a
value into a location digest would lose failure resolution (a dropped tag and
a retyped value would read as the same drift).

Usage:
    python3 scripts/check_openapi_field_constraints.py
    python3 scripts/check_openapi_field_constraints.py --self-test
"""

from __future__ import annotations

import argparse
import copy
from collections import Counter
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
SELF = Path(__file__).name

# The published constraint vocabulary. These are JSON Schema keywords, not
# property names: a component may legitimately have a field *called* "format"
# or "minimum" (``ExportManifestResponse.properties.format``), which is a
# schema node of its own and must not be counted as a constraint on the map.
_KEYS: tuple[str, ...] = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "format",
    "multipleOf",
    # ``default`` is a published value, not just an annotation: clients read
    # it and the generator renders it as ``@default``. Pinning it here closes
    # the coordinated rewrite in both halves that every two-artifact check
    # (and the provenance blob re-pin) agrees with.
    "default",
)
# A dict is a schema node (and its keyword values are constraints) only when
# it carries one of these markers. ``properties``/``$defs`` maps are name ->
# schema, not schemas themselves, so their own keys are never constraints.
_SCHEMA_MARKERS = frozenset(
    {"type", "$ref", "anyOf", "oneOf", "allOf", "enum", "const", "items"}
)

# Reviewed, hand-written fixed point on the whole published constraint
# surface. sha256 of "\n".join(["soymutdb-field-constraints/v2"] +
#   sorted(f"{path}|{key}|{json.dumps(value, sort_keys=True)}")).
# v2 folds the 897 published ``default`` values into the same fixed point.
# Regenerate with _digest() after an intentional contract change and update in
# the same commit, with a reason.
_FIELD_CONSTRAINT_DIGEST = (
    "405ca0867e880043ee132cc37647981fa372ff85fb0d4db2db2c4f6e56f7a56c"
)
_EXPECTED_CONSTRAINT_ROWS = 1712
_EXPECTED_SCHEMAS = 263
_EXPECTED_BY_KEY: dict[str, int] = {
    "default": 897,
    "exclusiveMinimum": 6,
    "format": 151,
    "maxItems": 24,
    "maxLength": 183,
    "maximum": 58,
    "minItems": 17,
    "minLength": 125,
    "minimum": 227,
    "pattern": 24,
}

# Independent fixed point for the published ``examples`` arrays. sha256 of
# "\n".join(["soymutdb-published-examples/v1"] +
#   sorted(f"{path}|{index}|{json.dumps(value, sort_keys=True)}")) of every
# ``examples`` list on a property schema. Hand-written, NOT derived from the
# artifacts under guard. Regenerate with _example_digest() after an intentional
# contract change and update in the same commit, with a reason.
_EXAMPLE_DIGEST = "505821408a432b85893123625136d747a5b787f4337c3d8cf1da3e09c89e6fe4"
_EXPECTED_EXAMPLES = 7
_EXPECTED_GENERATED_EXAMPLES = 7
_GENERATED = ROOT / "packages" / "api-client" / "src" / "generated" / "openapi.d.ts"

# Strict JSDoc marker. ``grep -c '@example'`` returns 8 on this tree because a
# @description block carries ``user@example.com``; that decoy is prose, not a
# published example, and must not be counted.
_GENERATED_EXAMPLE = re.compile(r"^\s*\* @example ", re.MULTILINE)

# Independent fixed point for the generated ``@default`` JSDoc projection.
# sha256 of "\n".join(["soymutdb-generated-default-tags/v1"] +
#   sorted(f"{component}|{field}")) over the 896 property doc blocks carrying
# an ``@default`` marker. Hand-written, NOT derived from the snapshot under
# guard. Regenerate with _default_tag_digest() after an intentional, reviewed
# regenerate and update in the same commit as both artifacts, with a reason.
_DEFAULT_TAG_DIGEST = (
    "f5737d9fbfb4a689721a52c51604185c6997b5c011999091be128b95dc72d065"
)
_EXPECTED_DEFAULT_TAGS = 896

# Independent fixed point for the *value* written in each generated @default
# tag. sha256 of "\n".join(["soymutdb-generated-default-values/v1"] +
#   sorted(f"{component}|{field}|{value}")) over the 896 doc blocks. #297's
# _DEFAULT_TAG_DIGEST pins (component, field) only; a retyped value keeps that
# digest green. Hand-written, NOT derived from the artifacts under guard:
# regenerating it from openapi.d.ts would make the pin self-referential, and a
# co-revert with a re-pinned generated_blob would then agree with itself.
# Regenerate with _default_tag_value_digest() after an intentional, reviewed
# regenerate and update in the same commit as both artifacts, with a reason.
_DEFAULT_TAG_VALUE_DIGEST = (
    "c7c1f7f5c31416c69b892107f8711f64ef629b8919619a7c9d614c1c7d013824"
)

# Independent fixed point for the VALUE printed in each generated @example
# tag. Doors 8 and 11 compare the generated half against the snapshot under
# guard; a regenerate that moves a value in BOTH halves (and honestly re-pins
# _EXAMPLE_DIGEST plus the provenance blob ids) satisfies every such
# comparison, and sorting the property blocks cannot see it either. This
# digest is the one face of the published example value with its own literal.
# sha256 of "\n".join(["soymutdb-generated-example-values/v1"] +
#   sorted(f"{component}|{field}|{value}")) over the 7 generated tags.
# Hand-written, NOT derived from either artifact under guard. Regenerate with
# _generated_example_value_digest() after an intentional, reviewed regenerate
# and update in the same commit as both artifacts, with a reason.
_GENERATED_EXAMPLE_VALUE_DIGEST = (
    "1a5efc727525c00f3c05a7b2061acec1c592475f929bf58b5d073b96554026a8"
)
_EXPECTED_GENERATED_EXAMPLE_VALUE_ROWS = 7

# Independent fixed point on the published ``additionalProperties`` surface.
# 102 component-schema nodes publish a boolean or a schema value; none is in
# ``_KEYS`` (it is a schema *shape*, not a scalar constraint), and a ``false``
# node renders no line at all in the generated client. sha256 of
# "\n".join(["soymutdb-schema-additional-properties/v1"] + sorted rows), each
# row "|".join((dotted path, canonical JSON value)). Read from nowhere.
_ADDITIONAL_PROPERTIES_DIGEST = (
    "4030dc8d56d82e3be31ea99cf2838fcbc6865384765f2df50530334e8ca23f4e"
)
_EXPECTED_ADDITIONAL_PROPERTIES = 102
# sha256 over the generated client's (component, index-signature type) rows.
# The 35 ``false`` nodes deliberately render nothing; the other 67 do. A
# second literal is required: checking the client against the snapshot under
# guard would pass on a coordinated regenerate that moves both halves.
_CLIENT_ADDITIONAL_PROPERTIES_DIGEST = (
    "380346075bd99ab0fd4e2a2481e8d63f64b05b32681eb94b6b877a65476e899d"
)
_EXPECTED_CLIENT_ADDITIONAL_PROPERTIES = 67


def rows(document: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Canonical (path, key, value) rows for every real schema node."""
    out: list[tuple[str, str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            is_schema = any(marker in node for marker in _SCHEMA_MARKERS)
            if is_schema:
                for key in _KEYS:
                    if key in node:
                        out.append((path, key, node[key]))
            for name, value in node.items():
                walk(value, f"{path}/{name}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(document.get("components", {}).get("schemas", {}), "")
    return out


def _digest(rows_: list[tuple[str, str, Any]]) -> str:
    canonical = sorted(
        f"{path}|{key}|{json.dumps(value, sort_keys=True)}"
        for path, key, value in rows_
    )
    blob = "\n".join(["soymutdb-field-constraints/v2", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _by_key(rows_: list[tuple[str, str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, key, _ in rows_:
        counts[key] = counts.get(key, 0) + 1
    return counts


def _schemas(rows_: list[tuple[str, str, Any]]) -> set[str]:
    # path starts "/<SchemaName>/..." -- the first segment is the component.
    return {path.split("/")[1] for path, _, _ in rows_}


def example_rows(document: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Canonical (path, index, value) rows for every published ``examples`` list.

    Only ``components.schemas`` property nodes are walked. A dict is a schema
    node only when it carries a schema marker, so a field literally named
    ``examples`` is never mistaken for the keyword itself (same rule as
    ``rows()`` uses for ``default`` / ``format``-named properties).
    """
    out: list[tuple[str, str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            is_schema = any(marker in node for marker in _SCHEMA_MARKERS)
            if is_schema and isinstance(node.get("examples"), list):
                for index, value in enumerate(node["examples"]):
                    out.append((path, str(index), value))
            for name, value in node.items():
                walk(value, f"{path}/{name}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}")

    walk(document.get("components", {}).get("schemas", {}), "")
    return out


def _example_digest(rows_: list[tuple[str, str, Any]]) -> str:
    canonical = sorted(
        f"{path}|{index}|{json.dumps(value, sort_keys=True, ensure_ascii=False)}"
        for path, index, value in rows_
    )
    blob = "\n".join(["soymutdb-published-examples/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def generated_examples(generated: str | None = None) -> list[str]:
    """Strict ``* @example `` JSDoc values from the generated client."""
    if generated is None:
        generated = _GENERATED.read_text(encoding="utf-8")
    return [
        line.split("@example ", 1)[1].strip()
        for line in generated.splitlines()
        if _GENERATED_EXAMPLE.search(line)
    ]


# ``finditer``, not ``search``: one property doc block may carry more than one
# ``@example`` tag, and every one is a published value. A reader that quietly
# reads less is the same failure mode as a guard that quietly checks less.
_EXAMPLE_TAG = re.compile(r"^\s*\* @example (?P<value>.*?)\s*$", re.MULTILINE)


def generated_example_rows(
    generated: str | None = None,
) -> list[tuple[str, str, str]]:
    """``(component, field, value)`` rows for every generated ``@example`` tag.

    ``generated_examples()`` is a flat, unlabelled list: enough for the count
    door, not enough to say *which* field a tag belongs to. These rows keep
    the component and field the tag is printed under, so the generated half can
    be compared to the snapshot per field instead of by position.
    """
    if generated is None:
        generated = _GENERATED.read_text(encoding="utf-8")
    region = _SCHEMAS_REGION.search(generated)
    if region is None:
        return []
    out: list[tuple[str, str, str]] = []
    for block in _COMPONENT_BLOCK.finditer(region.group("body")):
        name = block.group("name")
        for prop in _PROPERTY_DOC.finditer(block.group("body")):
            for tag in _EXAMPLE_TAG.finditer(prop.group("doc")):
                out.append((name, prop.group("field"), tag.group("value")))
    return out


def example_projection(
    document: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Document-order ``(component, field, value)`` rows of published examples.

    ``properties`` keeps document order, which is the order the generator
    prints the tags in. Same schema-marker rule as ``example_rows()``: a
    property literally named ``examples`` is not the keyword itself.
    """
    out: list[tuple[str, str, str]] = []
    schemas = document.get("components", {}).get("schemas", {})
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        for field, node in (schema.get("properties") or {}).items():
            if not isinstance(node, dict):
                continue
            if not any(marker in node for marker in _SCHEMA_MARKERS):
                continue
            values = node.get("examples")
            if not isinstance(values, list):
                continue
            for value in values:
                out.append((name, field, str(value)))
    return out


def _values_by_field(
    rows_: list[tuple[str, str, str]],
) -> dict[tuple[str, str], list[str]]:
    """Group ordered ``(component, field, value)`` rows into per-field lists."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for name, field, value in rows_:
        grouped.setdefault((name, field), []).append(value)
    return grouped


def example_field_drift(
    published: list[tuple[str, str, str]],
    printed: list[tuple[str, str, str]],
) -> list[str]:
    """One failure per field whose published ``@example`` values disagree.

    Values within a field are compared as an ordered list, so a same-count
    permutation inside one field is caught too. Per field rather than by
    position: a dropped tag shifts every later tag, and an index-wise compare
    would name six innocent neighbours before the real one.
    """
    want = _values_by_field(published)
    have = _values_by_field(printed)
    out: list[str] = []
    for field in sorted(set(want) | set(have)):
        if want.get(field) == have.get(field):
            continue
        label = f"{field[0]}.{field[1]}"
        if field not in have:
            out.append(
                f"generated @example tags missing for {label}: the snapshot "
                f"publishes {want[field]!r} but openapi.d.ts prints none"
            )
        elif field not in want:
            out.append(
                f"generated @example tags invented for {label}: openapi.d.ts "
                f"prints {have[field]!r} but the snapshot publishes no "
                "examples for it"
            )
        else:
            out.append(
                f"generated @example values disagree for {label}: the "
                f"snapshot publishes {want[field]!r} but openapi.d.ts prints "
                f"{have[field]!r}. A tag relocated between two doc blocks "
                "leaves the flat value sequence and both count doors "
                "unchanged."
            )
    return out


# ``openapi-typescript`` prints component schemas at 8-space indent, their
# property doc blocks at 12, and the property declaration right below the
# block. Restrict to the ``schemas`` region so ``parameters`` / ``responses``
# blocks with the same indentation cannot be misread as components.
_SCHEMAS_REGION = re.compile(r"^    schemas: \{\n(?P<body>.*?)^    \};$", re.M | re.S)
_COMPONENT_BLOCK = re.compile(
    r"^        (?P<name>[A-Za-z_][A-Za-z0-9_]*): \{\n(?P<body>.*?)^        \};$",
    re.M | re.S,
)
_PROPERTY_DOC = re.compile(
    r"^            (?P<doc>/\*\*(?:.|\n)*?\*/)\n"
    r"^            (?P<field>[A-Za-z_][A-Za-z0-9_]*)\??\s*:",
    re.M,
)


def default_tag_rows(generated: str) -> list[tuple[str, str]]:
    """Canonical ``(component, field)`` rows carrying a published ``@default``.

    The generator emits either a one-line ``/** @default x */`` or a multi-line
    block; both are read. A doc block with no ``@default`` is not a default tag,
    and a nested inline object (deeper indent) is not a direct property here.
    """
    region = _SCHEMAS_REGION.search(generated)
    if region is None:
        return []
    out: list[tuple[str, str]] = []
    for block in _COMPONENT_BLOCK.finditer(region.group("body")):
        name = block.group("name")
        body = block.group("body")
        for prop in _PROPERTY_DOC.finditer(body):
            if re.search(r"@default\b", prop.group("doc")):
                out.append((name, prop.group("field")))
    return out


def _default_tag_digest(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{name}|{field}" for name, field in rows_)
    blob = "\n".join(["soymutdb-generated-default-tags/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def default_tag_values(generated: str) -> list[tuple[str, str, str]]:
    """Canonical ``(component, field, value)`` rows of generated @default tags.

    Reuses the same doc-block region as ``default_tag_rows`` so the two readers
    cannot disagree about *which* properties carry a tag. The value is the tail
    of the ``@default`` marker; a bare tag (the one empty-string default) is an
    empty string, counted by its position rather than by a substring scan.
    """
    region = _SCHEMAS_REGION.search(generated)
    if region is None:
        return []
    out: list[tuple[str, str, str]] = []
    for block in _COMPONENT_BLOCK.finditer(region.group("body")):
        name = block.group("name")
        for prop in _PROPERTY_DOC.finditer(block.group("body")):
            marker = re.search(
                r"@default\b(?P<tail>[^\n]*)(?:\n\s*\*[^\n]*)*",
                prop.group("doc"),
            )
            if not marker:
                continue
            # The value is the rest of the @default line only. A multiline doc
            # block may carry further tags (* @enum / * @constant / */); those
            # are not part of the published default value.
            value = marker.group("tail").replace("*/", "").strip()
            out.append((name, prop.group("field"), value))
    return out


def _default_tag_value_digest(
    rows_: list[tuple[str, str, str]],
) -> str:
    canonical = sorted(f"{name}|{field}|{value}" for name, field, value in rows_)
    blob = "\n".join(["soymutdb-generated-default-values/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _generated_example_value_digest(
    rows_: list[tuple[str, str, str]],
) -> str:
    """Canonical digest of the generated ``(component, field, value)`` rows."""
    canonical = sorted(f"{name}|{field}|{value}" for name, field, value in rows_)
    blob = "\n".join(["soymutdb-generated-example-values/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_PRIMITIVE_TYPE = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}
_CLIENT_INDEX_SIGNATURE = re.compile(
    r"^\s*\[key: string\]: (?P<type>[^;]+);$"
)


def additional_property_rows(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Canonical (dotted path, canonical JSON value) rows."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "additionalProperties" in node:
                out.append(
                    (
                        path,
                        json.dumps(node["additionalProperties"], sort_keys=True),
                    )
                )
            for name, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, f"{path}/{name}" if path else name)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}/{index}" if path else str(index))

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, name)
    return out


def _additional_properties_digest(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{path}|{value}" for path, value in rows_)
    blob = "\n".join(["soymutdb-schema-additional-properties/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _client_type(value: Any) -> str | None:
    """openapi-typescript's index-signature type for one published value."""
    if value is True:
        return "unknown"
    if value is False:
        return None  # a closed object renders no index signature at all
    if not isinstance(value, dict):
        return None
    if "$ref" in value:
        return f'components["schemas"]["{str(value["$ref"]).split("/")[-1]}"]'
    for key in ("anyOf", "oneOf"):
        if key in value:
            return " | ".join(_client_type(part) or "unknown" for part in value[key])
    if "type" in value:
        declared = value["type"]
        if isinstance(declared, list):
            return " | ".join(_PRIMITIVE_TYPE.get(t, "unknown") for t in declared)
        return _PRIMITIVE_TYPE.get(declared, "unknown")
    return "unknown"


def client_additional_properties(generated: str) -> list[tuple[str, str]]:
    """(component, index-signature type) rows in components.schemas."""
    block = _SCHEMAS_REGION.search(generated)
    if block is None:
        raise ValueError("generated client has no components.schemas block")
    out: list[tuple[str, str]] = []
    component: str | None = None
    for line in block.group("body").splitlines():
        opener = re.match(r"^        (?P<name>[A-Za-z_][A-Za-z0-9_]*): \{$", line)
        if opener:
            component = opener.group("name")
            continue
        index = _CLIENT_INDEX_SIGNATURE.match(line)
        if index and component:
            out.append((component, index.group("type")))
    return out


def _client_additional_properties_digest(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{component}|{type_}" for component, type_ in rows_)
    blob = "\n".join(["soymutdb-client-additional-properties/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    digest: str | None = None,
    expected_rows: int | None = None,
    expected_schemas: int | None = None,
    by_key: dict[str, int] | None = None,
    example_digest: str | None = None,
    expected_examples: int | None = None,
    expected_generated_examples: int | None = None,
    tag_digest: str | None = None,
    expected_tags: int | None = None,
    tag_value_digest: str | None = None,
    generated_example_value_digest: str | None = None,
    additional_digest: str | None = None,
    client_additional_digest: str | None = None,
    expected_additional: int | None = None,
    expected_client_additional: int | None = None,
    pin_example_fields: bool = True,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = _GENERATED.read_text(encoding="utf-8")
    try:
        document = json.loads(snapshot)
        rows_ = rows(document)
        example_rows_ = example_rows(document)
        additional_rows_ = additional_property_rows(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published constraints from snapshot: {exc}"]
    try:
        client_additional_ = client_additional_properties(generated)
    except ValueError as exc:
        return [f"cannot read generated client index signatures: {exc}"]

    pinned_digest = _FIELD_CONSTRAINT_DIGEST if digest is None else digest
    pinned_rows = (
        _EXPECTED_CONSTRAINT_ROWS if expected_rows is None else expected_rows
    )
    pinned_schemas = (
        _EXPECTED_SCHEMAS if expected_schemas is None else expected_schemas
    )
    pinned_by_key = _EXPECTED_BY_KEY if by_key is None else by_key
    pinned_tag_digest = _DEFAULT_TAG_DIGEST if tag_digest is None else tag_digest
    pinned_tags = _EXPECTED_DEFAULT_TAGS if expected_tags is None else expected_tags
    pinned_value_digest = (
        _DEFAULT_TAG_VALUE_DIGEST
        if tag_value_digest is None
        else tag_value_digest
    )
    pinned_generated_example_digest = (
        _GENERATED_EXAMPLE_VALUE_DIGEST
        if generated_example_value_digest is None
        else generated_example_value_digest
    )
    pinned_additional = (
        _ADDITIONAL_PROPERTIES_DIGEST
        if additional_digest is None
        else additional_digest
    )
    pinned_client_additional = (
        _CLIENT_ADDITIONAL_PROPERTIES_DIGEST
        if client_additional_digest is None
        else client_additional_digest
    )
    pinned_additional_count = (
        _EXPECTED_ADDITIONAL_PROPERTIES
        if expected_additional is None
        else expected_additional
    )
    pinned_client_additional_count = (
        _EXPECTED_CLIENT_ADDITIONAL_PROPERTIES
        if expected_client_additional is None
        else expected_client_additional
    )

    # Door 1 -- independent fixed point over the whole surface. A single value
    # change, a moved constraint between two same-count fields, or a
    # coordinate regenerate all move the digest.
    actual = _digest(rows_)
    if actual != pinned_digest:
        found.append(
            "published field constraints drifted: _FIELD_CONSTRAINT_DIGEST "
            f"pins {pinned_digest} but the snapshot derives {actual}. A "
            "baseline is a fixed point for the artifact, not a place to make "
            "a guard agree with itself -- re-pin the digest in the same commit "
            "as the snapshot, with a reason."
        )

    # Door 2 -- exact shape doors. These name a drop/add without relying on the
    # digest alone, and make a same-count permutation visible in the counts.
    if len(rows_) != pinned_rows:
        found.append(
            f"published constraint row count is {len(rows_)}, "
            f"_EXPECTED_CONSTRAINT_ROWS pins {pinned_rows}: a constraint was "
            "added or dropped without moving the fixed point"
        )
    observed_schemas = _schemas(rows_)
    if len(observed_schemas) != pinned_schemas:
        found.append(
            f"constraints span {len(observed_schemas)} component schemas, "
            f"_EXPECTED_SCHEMAS pins {pinned_schemas}"
        )
    observed_by_key = _by_key(rows_)
    if observed_by_key != pinned_by_key:
        changed = [
            f"{key} {pinned_by_key.get(key, 0)}->{observed_by_key.get(key, 0)}"
            for key in sorted(set(pinned_by_key) | set(observed_by_key))
            if pinned_by_key.get(key, 0) != observed_by_key.get(key, 0)
        ]
        found.append(
            "published constraint counts by keyword changed: "
            + ", ".join(changed[:6])
            + (" ..." if len(changed) > 6 else "")
        )

    # Door 5 -- the published ``examples`` projection. Deliberately its own
    # digest: a drift here must say "examples", not "field constraints".
    pinned_example_digest = _EXAMPLE_DIGEST if example_digest is None else example_digest
    pinned_examples = (
        _EXPECTED_EXAMPLES if expected_examples is None else expected_examples
    )
    pinned_generated = (
        _EXPECTED_GENERATED_EXAMPLES
        if expected_generated_examples is None
        else expected_generated_examples
    )
    actual_example_digest = _example_digest(example_rows_)
    if actual_example_digest != pinned_example_digest:
        found.append(
            "published examples drifted: _EXAMPLE_DIGEST pins "
            f"{pinned_example_digest} but the snapshot derives "
            f"{actual_example_digest}. A coordinated regenerate that rewrites "
            "one example in both halves and re-pins the provenance blob ids "
            "satisfies every two-artifact check; re-pin this digest in the "
            "same commit as the snapshot, with a reason."
        )
    if len(example_rows_) != pinned_examples:
        found.append(
            f"published example count is {len(example_rows_)}, "
            f"_EXPECTED_EXAMPLES pins {pinned_examples}: an example was added "
            "or dropped without moving the fixed point"
        )
    gen_examples = generated_examples(generated)
    printed_example_rows = generated_example_rows(generated)
    if len(gen_examples) != pinned_generated:
        found.append(
            f"generated @example tag count is {len(gen_examples)}, "
            f"_EXPECTED_GENERATED_EXAMPLES pins {pinned_generated}: the "
            "generator dropped or invented a published example. The strict "
            "'* @example ' marker is used, so the @description decoy "
            "user@example.com is not counted."
        )

    # Door 12 -- an independent literal for the 7 generated @example VALUES.
    # Doors 8 and 11 both read the snapshot as their reference, so a
    # regenerate that moves a value in both halves (and honestly re-pins
    # _EXAMPLE_DIGEST and the provenance blob ids) agrees with itself. This
    # digest is read from nowhere: it is the one witness that does not move
    # with a reviewed re-pin of the artifacts it guards.
    #
    # Stand down whenever the two halves already disagree, so a one-sided
    # rewrite is named once by door 8 / door 11 with its field, a snapshot-
    # side rewrite stays door 5's alone, and a cardinality drift stays with
    # the count door. What is left is the coordinated shape: both halves
    # publish the same NEW value, all counts hold, and the snapshot digest
    # has been honestly re-pinned -- every two-artifact door is silent and
    # only this literal can name it.
    actual_generated_example_values = _generated_example_value_digest(
        printed_example_rows
    )
    example_value_drift = (
        actual_example_digest == pinned_example_digest
        and len(gen_examples) == pinned_generated
        and not example_field_drift(
            example_projection(document), printed_example_rows
        )
        and actual_generated_example_values != pinned_generated_example_digest
    )
    if example_value_drift:
        found.append(
            "published generated @example values drifted: "
            f"_GENERATED_EXAMPLE_VALUE_DIGEST pins "
            f"{pinned_generated_example_digest} but openapi.d.ts derives "
            f"{actual_generated_example_values}. Both halves publish the "
            "same new example value, so every two-artifact comparison is "
            "silent and the reviewed _EXAMPLE_DIGEST re-pin agrees with the "
            "regenerate; re-pin this literal in the same commit as both "
            "artifacts, with a reason."
        )

    # Door 6 -- the generated client half of the published ``default``
    # values. #282 folded ``default`` into the digest but carried no floor
    # on the 896 ``@default`` JSDoc tags; a regenerate that drops one (with
    # both provenance blob ids re-pinned) kept every wired guard green.
    # Check against the pinned literal, not against the snapshot, so a
    # co-revert of both halves cannot agree.
    tags = default_tag_rows(generated)
    if len(tags) != pinned_tags:
        found.append(
            f"generated @default tag count is {len(tags)}, "
            f"_EXPECTED_DEFAULT_TAGS pins {pinned_tags}: a published "
            "default tag was dropped or added in openapi.d.ts"
        )
    actual_tags = _default_tag_digest(tags)
    if actual_tags != pinned_tag_digest:
        found.append(
            "published generated default tags drifted: _DEFAULT_TAG_DIGEST "
            f"pins {pinned_tag_digest} but openapi.d.ts derives "
            f"{actual_tags}. Re-pin the tag digest in the same commit as "
            "both artifacts, with a reason."
        )

    # Door 7 -- the value written in each generated @default tag. #297's Door 6
    # pins (component, field) presence, so a retyped value (with the one
    # generated_blob re-pin) keeps every other wired guard green. Checked
    # against an independent literal, not against the snapshot's default
    # values: openapi-typescript renders floats / arrays / the empty string
    # differently from JSON, so a two-artifact token comparison would be a
    # second brittle ledger. A same-count value rotation moves only this
    # digest; both of Door 6's doors stay silent.
    value_rows = default_tag_values(generated)
    actual_values = _default_tag_value_digest(value_rows)
    if actual_values != pinned_value_digest:
        found.append(
            "published generated default tag values drifted: "
            f"_DEFAULT_TAG_VALUE_DIGEST pins {pinned_value_digest} but "
            f"openapi.d.ts derives {actual_values}. A baseline is a fixed "
            "point for the artifact, not a place to make a guard agree with "
            "itself -- re-pin the value digest in the same commit as both "
            "artifacts, with a reason."
        )

    # Door 8 -- the generated half's example values, not just its cardinality.
    # The expected sequence is the snapshot's canonical ``examples`` rows,
    # authoritative only because door 5's independent literal matched.
    # Gating on the digest and the tag cardinality keeps failure resolution:
    # a snapshot-side drift is named by door 1, a dropped/added tag by the
    # count door, and only a value/order drift in the generated half lands
    # here. Comparing in order (not as a multiset) also catches a same-count
    # permutation that moves one tag's value onto another field. Door 11 is
    # strictly stronger (per field, values in order), so when it is wired on,
    # door 8 stands down: a value drift must be named once, not twice. The
    # --self-test off-control keeps door 8 load-bearing by disabling door 11.
    snapshot_example_values = tuple(value for _, _, value in example_rows_)
    if (
        not pin_example_fields
        and actual_example_digest == pinned_example_digest
        and len(gen_examples) == pinned_generated
        and tuple(gen_examples) != snapshot_example_values
    ):
        found.append(
            "generated @example values disagree with the pinned published "
            f"examples (client renders {tuple(gen_examples)!r}, snapshot pins "
            f"{snapshot_example_values!r}). Door 5 fixes how many tags are "
            "emitted; door 8 matches their values against the digest-pinned "
            "snapshot projection. A one-sided rewrite of one @example value "
            "keeps all 7 tags and, once generated_blob is re-pinned, leaves "
            "every other door silent."
        )

    # Door 11 -- the *field* each generated ``@example`` tag is printed under.
    # Door 8 compares a flat, unlabelled value sequence. Two doc blocks that
    # publish the same value can exchange a tag without moving that sequence:
    # drop the tag from LoginRequest.username, add a second one to
    # LoginRequest.email, keep all 7 tags, leave the snapshot and both count
    # doors intact, honestly re-pin generated_blob -- live main stayed
    # SMOKE PASS / 1103 passed. The generator prints tags *under a property*,
    # so field identity is a published fact, not an implementation detail.
    #
    # Stands down when the snapshot digest itself has drifted, so a snapshot-
    # side rewrite stays door 5's failure alone and is never double-counted.
    # Also stands down on a cardinality drift, so the count door names it once.
    if (
        pin_example_fields
        and actual_example_digest == pinned_example_digest
        and len(gen_examples) == pinned_generated
    ):
        found.extend(
            example_field_drift(example_projection(document), printed_example_rows)
        )
    # Door 9 -- independent fixed point on the published
    # ``additionalProperties`` surface. Both artifacts are exports of one
    # source, so a regenerate that rewrites one node (or drops/retypes its
    # index signature) moves both halves together; the two literals read from
    # nowhere are the only doors that see it. A ``false`` node has no client
    # counterpart, which is why the client side is pinned to its own digest
    # instead of compared one-to-one against the snapshot.
    actual_additional = _additional_properties_digest(additional_rows_)
    if actual_additional != pinned_additional:
        found.append(
            "published additionalProperties drifted: "
            f"_ADDITIONAL_PROPERTIES_DIGEST pins {pinned_additional} but the "
            f"snapshot derives {actual_additional}. Re-pin the digest in the "
            "same commit as both artifacts, with a reason."
        )
    if len(additional_rows_) != pinned_additional_count:
        found.append(
            f"published additionalProperties row count is "
            f"{len(additional_rows_)}, _EXPECTED_ADDITIONAL_PROPERTIES pins "
            f"{pinned_additional_count}: a node was added or dropped"
        )
    actual_client_additional = _client_additional_properties_digest(
        client_additional_
    )
    if actual_client_additional != pinned_client_additional:
        found.append(
            "generated client index signatures drifted: "
            f"_CLIENT_ADDITIONAL_PROPERTIES_DIGEST pins "
            f"{pinned_client_additional} but the client derives "
            f"{actual_client_additional}. Re-pin the digest in the same commit "
            "as both artifacts, with a reason."
        )
    if len(client_additional_) != pinned_client_additional_count:
        found.append(
            f"generated client publishes {len(client_additional_)} index "
            f"signatures, _EXPECTED_CLIENT_ADDITIONAL_PROPERTIES pins "
            f"{pinned_client_additional_count}"
        )

    # Door 10 -- one-sided consistency. Derive the client projection from the
    # snapshot; a coordinated co-revert is caught by the two digests above,
    # this door names the component when only one half moves.
    expected_client = Counter()
    for path, value in additional_rows_:
        type_ = _client_type(json.loads(value))
        if type_ is not None:
            expected_client[(path.split("/", 1)[0], type_)] += 1
    observed_client = Counter(client_additional_)
    if expected_client != observed_client:
        missing = sorted((expected_client - observed_client).elements())
        extra = sorted((observed_client - expected_client).elements())
        found.append(
            "generated client index signatures disagree with the published "
            f"additionalProperties (missing={missing[:4]}, extra={extra[:4]})"
        )
    return found


def self_test() -> int:
    clean = failures()
    if clean:
        print(f"SELF-TEST FAIL: clean tree drifts: {clean}")
        return 1

    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    cases: dict[str, str] = {}

    # A coordinated regenerate shape: one real value retyped in the snapshot,
    # nothing else. No generated half exists for these keywords.
    target = "/AnalysesSubmitRequest/properties/input_objects/maxItems"
    doc = copy.deepcopy(document)
    assert doc["components"]["schemas"]["AnalysesSubmitRequest"]["properties"][
        "input_objects"
    ]["maxItems"] == 100
    doc["components"]["schemas"]["AnalysesSubmitRequest"]["properties"][
        "input_objects"
    ]["maxItems"] = 999
    cases["coordinated maxItems retype"] = json.dumps(doc, indent=2)

    # A constraint dropped outright.
    doc2 = copy.deepcopy(document)
    doc2["components"]["schemas"]["AnalysesSubmitRequest"]["properties"][
        "input_objects"
    ].pop("minItems")
    cases["one-sided constraint dropped"] = json.dumps(doc2, indent=2)

    # A constraint invented on a field that declares none.
    doc3 = copy.deepcopy(document)
    doc3["components"]["schemas"]["AnalysesSubmitRequest"]["properties"][
        "input_objects"
    ]["pattern"] = "^never$"
    cases["one-sided constraint added"] = json.dumps(doc3, indent=2)

    # A keyword renamed, same value and same count.
    doc4 = copy.deepcopy(document)
    node4 = doc4["components"]["schemas"]["AnalysesSubmitRequest"]["properties"][
        "input_objects"
    ]
    node4["maxLength"] = node4.pop("maxItems")
    cases["constraint keyword renamed"] = json.dumps(doc4, indent=2)

    # A property *named* like a keyword must not be read as a constraint.
    doc5 = copy.deepcopy(document)
    doc5["components"]["schemas"]["ExportManifestResponse"]["properties"][
        "format"
    ]["pattern"] = "^never$"
    cases["new constraint on a keyword-named property"] = json.dumps(doc5, indent=2)

    # The coordinated regenerate shape this pin is here for: one published
    # default retyped in the snapshot. The generated @default line would move
    # with it and the blob ids can be re-pinned, so only the literal sees it.
    doc6 = copy.deepcopy(document)
    assert doc6["components"]["schemas"]["AdminDashboardStats"]["properties"][
        "totalUsers"
    ]["default"] == 0
    doc6["components"]["schemas"]["AdminDashboardStats"]["properties"][
        "totalUsers"
    ]["default"] = 999999
    cases["coordinated default retype"] = json.dumps(doc6, indent=2)

    # A default dropped from one field: exact count door names it.
    doc7 = copy.deepcopy(document)
    doc7["components"]["schemas"]["AdminDashboardStats"]["properties"][
        "totalUsers"
    ].pop("default")
    cases["one-sided default dropped"] = json.dumps(doc7, indent=2)

    # A property literally *named* ``default`` is a schema node of its own;
    # its own keyword values count, the map entry itself does not.
    doc8 = copy.deepcopy(document)
    doc8["components"]["schemas"]["SettingFieldSchema"]["properties"][
        "default"
    ]["pattern"] = "^never$"
    cases["new constraint on the default-named property"] = json.dumps(doc8, indent=2)

    failures_count = 0
    for name, snapshot in cases.items():
        found = failures(snapshot=snapshot)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 5's plants live in their own dict: some of them must also rewrite
    # the generated half, which the constraint/default cases never need.
    # Keeping ``cases`` unchanged leaves the teeth guard's declared-case and
    # loop-consumption probes on this guard exactly as they were.
    generated = _GENERATED.read_text(encoding="utf-8")
    example_cases: dict[str, tuple[str, str]] = {}

    def example_doc(change) -> str:
        doc = copy.deepcopy(document)
        change(doc)
        return json.dumps(doc, indent=2)

    # 1. The decisive coordinated regenerate: all 7 examples rewritten in the
    #    snapshot AND the generated @example tags, provenance blob ids honestly
    #    re-pinned. Only _EXAMPLE_DIGEST sees it; both count doors stay silent.
    def co_revert(doc: dict) -> None:
        for name in ("LoginRequest", "UserCreate"):
            props = doc["components"]["schemas"][name]["properties"]
            for prop in props.values():
                if isinstance(prop, dict) and isinstance(prop.get("examples"), list):
                    prop["examples"] = [v + "X" for v in prop["examples"]]

    co_gen = generated
    for value in ("researcher@univ.edu", "S3cureP@ss!", "Jane Doe", "viewer"):
        co_gen = co_gen.replace("@example " + value, "@example " + value + "X")
    example_cases["coordinated examples co-revert"] = (example_doc(co_revert), co_gen)

    # 2. A same-count value swap (two examples exchange values): the digest
    #    must fire and BOTH count doors must stay silent. Without this positive
    #    control, door 5 is just a count check wearing a digest-shaped coat.
    def swap(doc: dict) -> None:
        props = doc["components"]["schemas"]["LoginRequest"]["properties"]
        props["username"]["examples"], props["password"]["examples"] = (
            props["password"]["examples"],
            props["username"]["examples"],
        )

    example_cases["same-count example swap"] = (example_doc(swap), generated)

    # 3. One example dropped from the snapshot: exact count door names it.
    def drop_snapshot(doc: dict) -> None:
        doc["components"]["schemas"]["LoginRequest"]["properties"]["username"].pop(
            "examples"
        )

    example_cases["one-sided example dropped"] = (example_doc(drop_snapshot), generated)

    # 4. A second example appended to an existing list: the digest fires and
    #    the exact count door names the addition (8 != 7).
    def add_snapshot(doc: dict) -> None:
        doc["components"]["schemas"]["UserCreate"]["properties"]["email"][
            "examples"
        ] = ["researcher@univ.edu", "extra@univ.edu"]

    example_cases["one-sided example added"] = (example_doc(add_snapshot), generated)

    # 5. One generated @example tag dropped: only the generated count door
    #    fires (the snapshot digest and its count door stay silent).
    dropped_gen = generated.replace(
        "             * @example researcher@univ.edu\n", "", 1
    )
    assert dropped_gen != generated
    example_cases["one-sided generated tag dropped"] = (
        json.dumps(document, indent=2),
        dropped_gen,
    )

    # 6. A forged strict marker in the generated half: the count door fires.
    #    The complement -- the real ``@description`` line carrying
    #    ``user@example.com`` must NOT be counted -- is a clean-tree assertion,
    #    pinned from a second file by the companion suite, not an ablation.
    forged_gen = generated.replace(
        '         *             "submitted_by": "user@example.com"',
        '         * @example user@example.com\n'
        '         *             "submitted_by": "user@example.com"',
        1,
    )
    assert forged_gen != generated
    example_cases["forged generated tag invented"] = (
        json.dumps(document, indent=2),
        forged_gen,
    )

    for name, (snapshot, gen) in example_cases.items():
        found = failures(snapshot=snapshot, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 6's plants need the generated half too, so they live in their own
    # dict like ``example_cases``. The snapshot is untouched in both: every
    # snapshot-side door (digest, row count, by-key histogram, examples) stays
    # green. Only the generated @default floor sees them.
    default_tag_cases: dict[str, tuple[str, str]] = {}
    snapshot_clean = json.dumps(document, indent=2)

    # The gap #282 left open: drop one published @default JSDoc tag.
    tag_lines = generated.splitlines(keepends=True)
    dropped = 0
    for index, line in enumerate(tag_lines):
        if "@default" in line and line.lstrip().startswith("* @"):
            del tag_lines[index]
            dropped += 1
            break
    assert dropped == 1
    default_tag_cases["generated @default tag dropped"] = (
        snapshot_clean,
        "".join(tag_lines),
    )

    # A same-count relocation: move a tag between two fields. The count door
    # holds; only the positional digest can name which field lost its tag.
    moved = generated.replace(
        "            /** @default custom */\n"
        '            category: components["schemas"]["WidgetCategoryEnum"];',
        "            /** Template Path */\n"
        '            category: components["schemas"]["WidgetCategoryEnum"];',
        1,
    )
    assert moved != generated
    moved = moved.replace(
        "            /** Template Path */\n            template_path: string;",
        "            /** @default custom */\n            template_path: string;",
        1,
    )
    assert moved != generated
    default_tag_cases["generated @default tag relocated (same count)"] = (
        snapshot_clean,
        moved,
    )

    for name, (snapshot, gen) in default_tag_cases.items():
        found = failures(snapshot=snapshot, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 7 -- the value written in the tag. #297 pins (component, field)
    # presence, so these plants must be caught *only* by the value digest:
    # Door 6's count and location digest both stay green on a pure retype.
    default_value_cases: dict[str, tuple[str, str]] = {}

    # Decisive shape: one published @default value retyped in the generated
    # half, with generated_blob honest-re-pinned. Snapshot untouched, so the
    # 897 default rows and every snapshot-side door stay green.
    needle = "             * @default 10000\n"
    assert generated.count(needle) == 1
    retyped = generated.replace(needle, "             * @default 9999\n", 1)
    assert retyped != generated
    default_value_cases["generated @default value retyped"] = (
        snapshot_clean,
        retyped,
    )

    # A same-count value rotation: two distinct tag values swapped. Door 6's
    # (component, field) rows are unchanged, its count door holds -- only the
    # positional value digest moves.
    a = "             * @default SNP\n"
    b = "             * @default genome\n"
    assert generated.count(a) == generated.count(b) == 1
    rotated = generated.replace(a, "@@A@@", 1).replace(b, a, 1).replace(
        "@@A@@", b, 1
    )
    assert rotated != generated
    default_value_cases["same-count generated @default value rotation"] = (
        snapshot_clean,
        rotated,
    )

    # The one bare @default tag (empty-string default) given a value. Door 6's
    # location rows are unchanged; only the value digest sees it.
    bare = "             * @default\n"
    assert generated.count(bare) == 1
    filled = generated.replace(bare, "             * @default filled\n", 1)
    assert filled != generated
    default_value_cases["bare generated @default value filled"] = (
        snapshot_clean,
        filled,
    )

    for name, (snapshot, gen) in default_value_cases.items():
        found = failures(snapshot=snapshot, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 8's plants also need the generated half, in their own dict so the
    # teeth guard's pinned ``cases``/``example_cases`` probes stay put. The
    # snapshot stays clean: the digest, both count doors and the @default
    # floor are all silent, and only door 8 names the drift.
    example_value_cases: dict[str, tuple[str, str]] = {}

    # 1. The decisive shape: one @example value rewritten in the generated
    #    half only. All 7 tags survive; honest generated_blob re-pinning used
    #    to leave the whole contracts layer SMOKE PASS.
    value_rewrite_gen = generated.replace(
        "@example Jane Doe", "@example John Roe", 1
    )
    assert value_rewrite_gen != generated
    example_value_cases["one-sided generated example value rewritten"] = (
        snapshot_clean,
        value_rewrite_gen,
    )

    # 2. A same-count value permutation in the generated half: swap two
    #    distinct values between two tags. Cardinality is unchanged, so only
    #    door 8 (ordered value match) can name it.
    permuted_gen = (
        generated.replace("@example Jane Doe", "@example __SWAP__", 1)
        .replace("@example viewer", "@example Jane Doe", 1)
        .replace("@example __SWAP__", "@example viewer", 1)
    )
    assert permuted_gen != generated
    assert sorted(generated_examples(permuted_gen)) == sorted(
        generated_examples(generated)
    )
    example_value_cases["same-count generated example value permutation"] = (
        snapshot_clean,
        permuted_gen,
    )

    for name, (snapshot, gen) in example_value_cases.items():
        found = failures(snapshot=snapshot, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 11 -- field identity of each generated @example tag. A flat value
    # comparison cannot see a tag relocated between two doc blocks that publish
    # the same value: the sequence, both count doors and _EXAMPLE_DIGEST all
    # survive. These plants also prove the reader is not quietly reading less
    # (a second tag on one field must be seen) and that door 8 stays silent.
    example_field_cases: dict[str, tuple[str, str]] = {}

    relocated_block = """            /**
             * Username
             * @description Email address or username
             * @default null
             */
            username: string | null;
            /**
             * Email
             * @description Email address (alternative to ``username``)
             * @default null
             * @example researcher@univ.edu
             * @example researcher@univ.edu
             */"""
    original_block = """            /**
             * Username
             * @description Email address or username
             * @default null
             * @example researcher@univ.edu
             */
            username: string | null;
            /**
             * Email
             * @description Email address (alternative to ``username``)
             * @default null
             * @example researcher@univ.edu
             */"""
    assert generated.count(original_block) == 1
    relocated = generated.replace(original_block, relocated_block, 1)
    assert relocated != generated
    assert generated_examples(relocated) == generated_examples(generated)
    example_field_cases["one @example tag relocated between two fields"] = (
        snapshot_clean,
        relocated,
    )

    # A stray second tag on ONE field is a cardinality drift: the count door
    # must name it first and door 11 stands down. The reader itself is pinned
    # separately -- finditer, not search, so two tags in one doc block are two
    # published values. A reader that quietly reads less is the same failure
    # mode as a guard that quietly checks less.
    stray = generated.replace(
        "             * @example Jane Doe\n",
        "             * @example Jane Doe\n             * @example Jane Doe\n",
        1,
    )
    assert stray != generated
    stray_rows = [
        row
        for row in generated_example_rows(stray)
        if row[:2] == ("UserCreate", "full_name")
    ]
    if len(stray_rows) != 2:
        print("SELF-TEST FAIL: stray second @example tag was not read")
        failures_count += 1
    else:
        print("PASS self-test: a stray second @example tag is read")
    stray_found = failures(snapshot=snapshot_clean, generated=stray)
    if not any("tag count is 8" in f for f in stray_found) or any(
        "disagree for" in f for f in stray_found
    ):
        print(f"SELF-TEST FAIL: stray tag not resolved by the count door: {stray_found}")
        failures_count += 1
    else:
        print("PASS self-test: stray tag is resolved by the count door alone")

    for name, (snapshot, gen) in example_field_cases.items():
        found = failures(snapshot=snapshot, generated=gen)
        field_named = [
            f for f in found if "for LoginRequest." in f or "for UserCreate." in f
        ]
        if not field_named:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught by door 11")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Control: with door 11 disabled, the relocated bytes are silent again.
    # The plants are load-bearing, not decorative.
    if failures(
        snapshot=snapshot_clean, generated=relocated, pin_example_fields=False
    ):
        print("SELF-TEST FAIL: door 11 off should leave the relocation silent")
        failures_count += 1
    else:
        print("PASS self-test: door 11 off leaves the relocation silent")

    # Mirror control: a snapshot-side rewrite stays door 5's alone. Door 11
    # stands down when _EXAMPLE_DIGEST has drifted, so no double-counting.
    snap_only = copy.deepcopy(document)
    snap_only["components"]["schemas"]["UserCreate"]["properties"][
        "full_name"
    ]["examples"] = ["John Roe"]
    mirror = failures(snapshot=json.dumps(snap_only, indent=2))
    if len(mirror) != 1 or "_EXAMPLE_DIGEST" not in mirror[0]:
        print(f"SELF-TEST FAIL: snapshot drift not resolved by door 5 alone: {mirror}")
        failures_count += 1
    else:
        print("PASS self-test: snapshot drift stays door 5's alone")

    # Door 9/10 plants: additionalProperties is a schema shape, not one of
    # ``_KEYS``, and a ``false`` node renders no client line at all. Keep them
    # in their own dict so the teeth guard's pinned case probes stay put.
    additional_cases: dict[str, tuple[str, str]] = {}
    target = "AdminSiteBrandResponse"
    original = generated
    ap_doc = copy.deepcopy(document)
    assert ap_doc["components"]["schemas"][target]["additionalProperties"] is False
    ap_doc["components"]["schemas"][target]["additionalProperties"] = True
    ap_snap = json.dumps(ap_doc, indent=2)
    block_start = original.find(f"        {target}: {{")
    block_end = original.find("\n        };", block_start)
    block = original[block_start:block_end]
    assert "[key: string]" not in block
    ap_gen = (
        original[:block_start]
        + block
        + "\n            [key: string]: unknown;"
        + original[block_end:]
    )
    assert ap_gen != original
    additional_cases["coordinated additionalProperties false->true"] = (
        ap_snap,
        ap_gen,
    )
    additional_cases["one-sided snapshot additionalProperties retype"] = (
        ap_snap,
        snapshot_clean,
    )
    additional_cases["one-sided client index signature added"] = (
        snapshot_clean,
        ap_gen,
    )
    # A schema-valued node retyped to a different primitive: digest moves in
    # both halves, counts hold.
    ap_doc2 = copy.deepcopy(document)
    node = ap_doc2["components"]["schemas"]["AnalysesUploadResponse"][
        "properties"
    ]["upload_fields"]
    assert node["additionalProperties"] == {"type": "string"}
    node["additionalProperties"] = {"type": "integer"}
    ap_snap2 = json.dumps(ap_doc2, indent=2)
    ap_gen2 = original.replace(
        "            [key: string]: string;\n",
        "            [key: string]: number;\n",
        1,
    )
    assert ap_gen2 != original
    additional_cases["coordinated additionalProperties type retype"] = (
        ap_snap2,
        ap_gen2,
    )
    # A node dropped from the snapshot only: count door names it.
    ap_doc3 = copy.deepcopy(document)
    del ap_doc3["components"]["schemas"][target]["additionalProperties"]
    additional_cases["one-sided additionalProperties dropped"] = (
        json.dumps(ap_doc3, indent=2),
        snapshot_clean,
    )
    for name, (snap, gen) in additional_cases.items():
        found = failures(snapshot=snap, generated=gen)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Door 12 -- the coordinated both-halves rewrite. Door 8 / door 11 read
    # the snapshot as their reference, so a regenerate that moves one value in
    # BOTH halves (and honestly re-pins _EXAMPLE_DIGEST plus the provenance
    # blob ids) agrees with itself. Only the independent generated-value
    # literal can name it. Keep these in their own dict so the teeth guard's
    # pinned ``cases`` / ``example_cases`` probes stay put.
    independent_value_cases: dict[str, tuple[str, str, str]] = {}

    coordinated_doc = copy.deepcopy(document)
    coordinated_doc["components"]["schemas"]["UserCreate"]["properties"][
        "full_name"
    ]["examples"] = ["John Roe"]
    coordinated_snap = json.dumps(coordinated_doc, indent=2)
    coordinated_gen = generated.replace(
        "@example Jane Doe", "@example John Roe", 1
    )
    assert coordinated_gen != generated
    coordinated_digest = _example_digest(example_rows(coordinated_doc))
    independent_value_cases["coordinated both-halves example rewrite"] = (
        coordinated_snap,
        coordinated_gen,
        coordinated_digest,
    )

    for name, (snap, gen, example_digest) in independent_value_cases.items():
        found = failures(snapshot=snap, generated=gen, example_digest=example_digest)
        if len(found) != 1 or "_GENERATED_EXAMPLE_VALUE_DIGEST" not in found[0]:
            print(f"SELF-TEST FAIL: {name!r} not resolved by door 12 alone: {found}")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")

    # Positive control: a reviewed regenerate re-pins BOTH literals in the
    # same commit, so the new pin is not a dead witness.
    re_pinned_gen_digest = _generated_example_value_digest(
        generated_example_rows(coordinated_gen)
    )
    re_pinned_example = failures(
        snapshot=coordinated_snap,
        generated=coordinated_gen,
        example_digest=coordinated_digest,
        generated_example_value_digest=re_pinned_gen_digest,
    )
    if re_pinned_example:
        print(f"SELF-TEST FAIL: reviewed re-pin was rejected: {re_pinned_example}")
        failures_count += 1
    else:
        print("PASS self-test: reviewed example-value re-pin stays green")

    # A reviewed regenerate that re-pins only _EXAMPLE_DIGEST (the shape the
    # topology used to bless) must no longer be silent: the new literal is a
    # second, independent act. This is the off-control for door 12.
    if not failures(
        snapshot=coordinated_snap,
        generated=coordinated_gen,
        example_digest=coordinated_digest,
    ):
        print("SELF-TEST FAIL: re-pinning only the snapshot digest stayed silent")
        failures_count += 1
    else:
        print("PASS self-test: re-pinning only the snapshot digest does not agree")

    # A reviewed regenerate re-pins both literals with both artifacts. The
    # positive control proves the pair is not a dead pin.
    re_pinned = failures(
        snapshot=ap_snap,
        generated=ap_gen,
        additional_digest=_additional_properties_digest(
            additional_property_rows(json.loads(ap_snap))
        ),
        client_additional_digest=_client_additional_properties_digest(
            client_additional_properties(ap_gen)
        ),
        expected_client_additional=len(client_additional_properties(ap_gen)),
    )
    if re_pinned:
        print(f"SELF-TEST FAIL: same-commit re-pin was rejected: {re_pinned}")
        failures_count += 1
    else:
        print("PASS self-test: same-commit re-pin stays green")
    total = (
        len(cases)
        + len(example_cases)
        + len(default_tag_cases)
        + len(default_value_cases)
        + len(example_value_cases)
        + len(example_field_cases)
        + len(additional_cases)
        + len(independent_value_cases)
        + 7  # stray reader, stray count door, door-11 off, mirror, re-pin,
             # reviewed example-value re-pin, snapshot-digest-only control
    )
    print(f"self-test: {total} cases, {failures_count} failure(s)")
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
            print(f"openapi-field-constraints: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-field-constraints: OK ({_EXPECTED_CONSTRAINT_ROWS} published "
        f"constraint rows pinned across {_EXPECTED_SCHEMAS} schemas, "
        f"{_EXPECTED_ADDITIONAL_PROPERTIES} additionalProperties nodes pinned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pin published component-schema ``description`` and ``title`` prose to literals.

``openapi.json`` publishes 257 ``description`` strings on component-schema
property nodes across 169 schemas, and 2327 ``title`` strings across all 362
schemas. ``openapi-typescript`` renders each one as
an ``@description`` line in the generated ``components["schemas"]`` JSDoc, so
the prose is client-visible: it is what an IDE shows a caller hovering a field.
Multi-line descriptions become ``@description <first line>`` plus indented
continuation lines; the generator also emits exactly one synthetic
``@description discriminator enum property added by openapi-typescript``.
Those continuation lines are client-visible IDE hover text. The description
half's two literals read only ``@description`` first lines, so a regenerate
that rewrote, dropped or relocated one of the 204 indented continuation
lines -- with both provenance blob ids honestly re-pinned -- stayed green.
Door 3c pins that component-schema share of the same continuation
projection with a third hand-written literal in this guard.

No other wired fixed point reads this surface:

* ``_FIELD_CONSTRAINT_DIGEST`` walks JSON Schema constraint keywords plus
  ``default`` -- ``description`` is not in ``_KEYS``;
* ``_REQUIRED_FIELD_DIGEST`` walks ``required`` arrays and the generated
  optional markers, not prose;
* ``_ANNOTATION_DIGEST`` / ``_RESPONSE_SURFACE_DIGEST`` / the summary digest
  walk *operations*; the annotation guard's docstring says so explicitly;
* the document-metadata lock freezes ``info`` and the tag catalog;
* ``check_openapi_inline_body_integrity`` / the body baselines read body
  shapes, and ``_PINNED_ARTIFACTS`` is a provenance blob id: re-pinning both
  ids beside a regenerate is the documented "one deliberate reviewed action".

The ``title`` strings are the same genus one keyword earlier. Every landed
``title`` guard pins key *order* (``_title_last`` in the snapshot contract),
the normalizer's spelling, or the top-level ``info.title`` -- none reads the
published title *values*, which ``openapi-typescript`` prints as the first
prose line of each ``components["schemas"]`` JSDoc block. A byte-preserving
rewrite of one title in the snapshot and its JSDoc line, with both blob ids
re-pinned, kept every wired guard and the whole contracts layer green.

Decisive ablation on live bytes: byte-preserving rewrite of one property's
``description`` in the snapshot and the matching ``@description`` line in the
generated client (both halves agree), re-pinning both blob ids, leaves all
eleven wired OpenAPI guards, their ``--self-test`` suites and the whole
contracts layer ``SMOKE PASS``. A client-visible doc line silently changes and
nothing in the layer pins it.

This guard reads committed bytes only (``json`` + ``re`` + stdlib): no Python
3.15, no API import, no wheel, no database, no workspace install. It pins:

* ``_SCHEMA_DESCRIPTION_DIGEST`` -- a hand-written sha256 over canonical sorted
  ``(schema path, description)`` rows, read from nowhere. Exported from the
  snapshot alone, so a co-revert of both halves still changes it;
* ``_EXPECTED_ROWS`` / ``_EXPECTED_SCHEMAS`` -- exact count doors, so a drop
  or add is named without relying on the digest alone;
* the generated client's ``@description`` first-line multiset against the
  *pinned* rows (plus the one documented synthetic line), so a one-sided edit
  that rewrites only the JSDoc is named too. The client half is checked
  against the pins, not against the snapshot under guard;
* ``_CLIENT_DESCRIPTION_SEQUENCE_DIGEST`` -- a second, independent sha256 over
  the generated ``@description`` lines **in document order**. A multiset is
  order-blind: rotating three distinct lines between fields keeps every count
  and the multiset unchanged, and a coordinated co-revert that re-pins only
  the snapshot digest agrees with itself and passes. This literal is read from
  nowhere, so that rotation and that co-revert both move it.
* ``_CLIENT_DESCRIPTION_CONTINUATION_DIGEST`` -- a third hand-written sha256
  over canonical sorted ``(component, description, index, prose)`` rows of the
  generated indented continuation lines, read from the committed client bytes.
  Doors 3 / 3b read only ``@description`` first lines; the 204 continuation
  lines across 50 description nodes are the component-schema share of the same
  projection #314 pins on ``paths``. ``_EXPECTED_CLIENT_CONTINUATION_ROWS`` /
  ``_EXPECTED_CLIENT_CONTINUATION_NODES`` are its exact count doors.

The ``title`` half is a second, independent fixed point over its own rows:

* ``_SCHEMA_TITLE_DIGEST`` -- a hand-written sha256 over canonical sorted
  ``(schema path, title)`` rows, read from nowhere. The walker recurses into
  the ``title`` key itself: seven schemas publish a property literally named
  ``title`` whose value is ``"Title"``, and skipping that key left those rows
  unpinned (a snapshot-only rewrite of one stayed green). They are published
  values, not synthetic generator lines;
* ``_EXPECTED_TITLE_ROWS`` / ``_EXPECTED_TITLE_SCHEMAS`` -- exact count doors;
* the generated client's JSDoc first-prose-line multiset, checked against the
  *pinned* title values. The generator emits a JSDoc block only for annotated
  nodes (1232 of 2327 titles render) plus exactly one synthetic ``Title``
  line, so the check is a sub-multiset of the pins, not an equality. A
  co-revert of both halves still changes the published digest.

Finally, the door every one of the above sorts away: the snapshot's own
``components.schemas`` **definition order**.

* ``_COMPONENT_DEFINITION_ORDER_DIGEST`` -- a hand-written sha256 over the
  definition names *in insertion order*, read from nowhere. Doors 1/4/6/7 are
  sorted row digests and Door 8 resolves a title *by* ``(component, field)``,
  so a byte-preserving rotation of two adjacent member blocks keeps all of
  them -- and both count doors -- green. ``openapi-typescript`` emits the
  component interfaces in snapshot insertion order, so which definition comes
  first is a published fact;
* ``_EXPECTED_COMPONENT_DEFINITIONS`` -- the exact definition count.

Decisive ablation on live bytes: swapping two adjacent
``components.schemas`` member blocks byte for byte leaves every other door at
``rc=0`` (the description and title multisets are unchanged, both counts
unchanged, Door 8 still resolves every field); only Door 12 names it.

The generated client's JSDoc title *lines* are the same genus on a
positional axis, and Doors 6/7 do not cover them: Door 6 pins a sorted
multiset, Door 7 pins sorted ``component|field|title`` rows, Door 8 looks a
title up by ``(component, field)``, and Door 9 walks property declarations
rather than the ``*`` prose lines above them. A declaration-only swap -- move
two adjacent property lines, leave each ``/**`` block where it is -- keeps
every count, every multiset and every pinned row intact while the label a
reader sees above a field changes. Two positional literals close it, one per
artifact half:

* ``_CLIENT_TITLE_SEQUENCE_DIGEST`` -- sha256 over the generated JSDoc title
  lines **in document order**;
* ``_ORDER_SNAPSHOT_TITLE_SEQUENCE_DIGEST`` -- sha256 over the snapshot's own
  ``title`` lines **in insertion order**;
* ``_EXPECTED_CLIENT_TITLE_LINES`` -- count door on the same walk.

They are separate ledgers: a declaration-only swap moves the client literal
and leaves the snapshot literal untouched, so re-pinning one cannot silence
the other.

A legitimate prose change must move the digest in the same commit as both
artifacts and say why. Re-deriving the digest from the artifact under guard
would make the pin self-referential.

The component-property declaration order is the same genus one level up.
``openapi-typescript`` prints a component's properties in the snapshot's
insertion order, so the generated interface's field sequence is part of the
published shape (IDE completion order, object key enumeration). Every landed
digest on this surface walks *values* or *field sets*, never the positional
``(component, index, field)`` triple: rotating two adjacent properties in both
halves, with both provenance blob ids honestly re-pinned, keeps all twelve
wired OpenAPI guards, their companion suites and the whole contracts layer
``SMOKE PASS`` while two client-visible declarations silently swap. Two
independent hand-written literals pin that order -- one over the snapshot
rows, one over the generated component blocks -- so re-pinning either half
alone cannot silence the other, and a one-sided edit is named by component
and field.

Usage:
    python3 scripts/check_openapi_schema_descriptions.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
GENERATED = ROOT / "packages" / "api-client" / "src" / "generated" / "openapi.d.ts"

# Reviewed, hand-written fixed point on the whole published description prose.
# sha256 of "\n".join(["soymutdb-schema-descriptions/v1"] +
#   sorted(f"{path}|{description}")) over every string `description` on a
#   component-schema node. Regenerate with _digest() after an intentional
#   prose change and update in the same commit, with a reason.
_SCHEMA_DESCRIPTION_DIGEST = (
    "a60bd748da20db13a062c12b747f8b641c4bb744b212002ba10362aa6797a3d5"
)
_EXPECTED_ROWS = 257
_EXPECTED_SCHEMAS = 169

# openapi-typescript emits one JSDoc description that is not in the snapshot.
# Pinned explicitly so a future generator change to this line is a reviewed
# edit rather than a silent extra row.
_SYNTHETIC_CLIENT_DESCRIPTION = (
    "discriminator enum property added by openapi-typescript"
)

# Second independent fixed point for the description half: a sha256 over the
# generated client's @description lines IN DOCUMENT ORDER, not a multiset.
# The title half already has two independent client literals (Door 6 sorted
# digest + Door 7 positional triples); this is the description half's
# counterpart. Read from nowhere -- regenerate with
# _digest_client_description_sequence() after an intentional, reviewed prose
# change, in the same commit as both artifacts, with a reason.
_CLIENT_DESCRIPTION_SEQUENCE_DIGEST = (
    "e2cbc097af0dc74c9f43fcf4def6f279c3dfd86f21f73fdacfc2e9669c80bec4"
)
_EXPECTED_CLIENT_DESCRIPTION_LINES = 258

# Reviewed, hand-written fixed point on the whole published title surface.
# sha256 of "\n".join(["soymutdb-schema-titles/v1"] +
#   sorted(f"{path}|{title}")) over every string `title` on a component-schema
#   node. Regenerate with _digest_title() after an intentional prose change.
_SCHEMA_TITLE_DIGEST = (
    "6ad9c8cd12ceb3508a25ce934509716405b9b326eac5afdfc9e9c37ff6ddaec0"
)
_EXPECTED_TITLE_ROWS = 2327
_EXPECTED_TITLE_SCHEMAS = 362

# Of the 1232 multi-line JSDoc blocks client_titles() reads, exactly one has
# "Title" as its first prose line. The seven published "Title" rows are on
# single-line JSDoc blocks, which this reader does not collect; that line is
# pinned here so a generator change is a reviewed edit, not a silent extra row.
_SYNTHETIC_CLIENT_TITLE = "Title"

# Second independent fixed point: the generated client's JSDoc first-prose
# lines. A digest over these lines, read from nowhere, catches a coordinated
# co-revert that edits both halves: the snapshot digest moves, and so does
# this one. Comparing the client lines against a multiset derived from the
# *snapshot under guard* would be self-referential -- a co-revert of both
# halves would agree with itself and pass.
_CLIENT_TITLE_DIGEST = (
    "3daaf30bd143170c66710c8497c7229b3d415a42f60b09bed3014fc7358ba2e9"
)
_EXPECTED_CLIENT_TITLE_LINES = 1232

_COMPONENT_SCHEMAS = re.compile(
    r"^    schemas: \{\n(?P<body>.*?)^    \};$", re.M | re.S
)
_DESCRIPTION_LINE = re.compile(r"^\s*\* @description (.*)$", re.M)


def rows(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Canonical (schema path, description) rows over every string description."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            value = node.get("description")
            if isinstance(value, str):
                out.append((path, value))
            for name, child in node.items():
                if name == "description" or not isinstance(child, (dict, list)):
                    continue
                walk(child, f"{path}/{name}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, name)
    return out


def _digest(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{path}|{value}" for path, value in rows_)
    blob = "\n".join(["soymutdb-schema-descriptions/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def client_descriptions(generated: str) -> list[str]:
    """First-line ``@description`` values in components["schemas"] JSDoc."""
    block = _COMPONENT_SCHEMAS.search(generated)
    if block is None:
        raise ValueError("generated client has no components.schemas block")
    return _DESCRIPTION_LINE.findall(block.group("body"))


def _digest_client_description_sequence(lines: list[str]) -> str:
    """sha256 over the generated ``@description`` lines in document order."""
    blob = "\n".join(
        ["soymutdb-client-schema-description-sequence/v1", *lines]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

_JSDOC_BLOCK = re.compile(r"/\*\*\n((?:\s*\*.*\n)*?)\s*\*/")
_FIRST_PROSE = re.compile(r"^\s*\* (?!@)(.*)$", re.M)


def title_rows(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Canonical (schema path, title) rows over every string ``title``."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            value = node.get("title")
            if isinstance(value, str):
                out.append((path, value))
            for name, child in node.items():
                if not isinstance(child, (dict, list)):
                    continue
                walk(child, f"{path}/{name}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")

    for name, schema in document.get("components", {}).get("schemas", {}).items():
        walk(schema, name)
    return out


def _digest_title(rows_: list[tuple[str, str]]) -> str:
    canonical = sorted(f"{path}|{value}" for path, value in rows_)
    blob = "\n".join(["soymutdb-schema-titles/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def client_titles(generated: str) -> list[str]:
    """First prose line of each components["schemas"] JSDoc block."""
    block = _COMPONENT_SCHEMAS.search(generated)
    if block is None:
        raise ValueError("generated client has no components.schemas block")
    out: list[str] = []
    for body in _JSDOC_BLOCK.findall(block.group("body")):
        match = _FIRST_PROSE.search(body)
        if match:
            out.append(match.group(1))
    return out


def _digest_client_title(lines: list[str]) -> str:
    canonical = sorted(lines)
    blob = "\n".join(["soymutdb-client-schema-titles/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

# Door 12 -- the snapshot's own ``components.schemas`` *definition order*.
# Every door above is order-insensitive in this dimension: Doors 1/4 are
# sorted row digests, Doors 6/7 sort their client rows, and Door 8 looks a
# title up *by* ``(component, field)``. ``openapi-typescript`` emits the
# component interfaces in snapshot insertion order, so the definition order
# is what a caller sees in IDE completion and when enumerating the module --
# a published fact with no fixed point. Two byte-preserving rotations survive
# every door above: swapping two adjacent component definitions in the
# snapshot, and moving a component's ``description`` row to a different
# component (the multiset is unchanged). Door 12 is a hand-written sha256
# over the definition names IN INSERTION ORDER, read from nowhere, so both
# rotations move it and a one-sided edit cannot hide behind a re-pinned count.
_COMPONENT_DEFINITION_ORDER_DIGEST = (
    "91f239588b99fd442ea8341908dd13d5721cc270e16dd48e450f91c31d74b968"
)
_EXPECTED_COMPONENT_DEFINITIONS = 362


def component_definition_order(document: dict[str, Any]) -> list[str]:
    """Every ``components.schemas`` name, in snapshot insertion order."""
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return []
    return list(schemas)


def _digest_component_definition_order(names: list[str]) -> str:
    """sha256 over the definition order -- a sequence, not a sorted multiset."""
    blob = "\n".join(["soymutdb-component-definition-order/v1", *names])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ``client_titles()`` keeps a *sorted* digest, so it cannot see two
# same-count title lines swap places: the multiset is unchanged. That is a
# real client-visible drift -- the label an IDE shows for one field lands on
# another -- and it survives every other door on this surface. Door 8 pins
# that position; Door 7's digest is the independent ledger a coordinated
# co-revert still has to move.
_SCHEMA_BLOCK = re.compile(
    r"^        (?P<name>\w+): \{\n(?P<body>.*?)^        \};$", re.M | re.S
)
_FIELD_DOC = re.compile(
    r"^            /\*\*(?P<doc>.*?)\*/\n"
    r"^            (?P<field>[A-Za-z_][A-Za-z0-9_]*)\??:",
    re.M | re.S,
)

# Reviewed, hand-written fixed point on the generated client's positional
# title triples. sha256 of the canonical sorted ``component|field|title``
# rows. regenerate with _digest_client_title_rows() after an intentional
# prose change, in the same commit as both artifacts.
_CLIENT_TITLE_ROWS_DIGEST = (
    "8ece22ef60eba74cbe47e3e4e0806348a8cbfcf8fe804221141afdcd606ce271"
)
_EXPECTED_CLIENT_TITLE_ROWS = 1952

# Reviewed, hand-written fixed point on component-property declaration order.
# sha256 of "\n".join(["soymutdb-component-property-order/v1"] +
#   sorted(f"{component}|{index}|{field}")) over every direct ``properties``
# entry of every component schema, in snapshot insertion order. Read from
# nowhere -- regenerate with _digest_property_order() after an intentional,
# reviewed reorder, in the same commit as both artifacts, with a reason.
_PROPERTY_ORDER_DIGEST = (
    "85ae9dc9832c6ba547fade07dad0eb7ce3f0a8d8673683da6b630371e09bd812"
)
_EXPECTED_PROPERTY_ORDER_ROWS = 2083
_EXPECTED_PROPERTY_ORDER_SCHEMAS = 335

# Second independent fixed point: the generated component blocks' own
# (component, index, field) rows, in document order. A coordinated co-revert
# moves this literal too; re-pinning only the snapshot digest cannot silence
# it, and comparing the client against the snapshot under guard would be
# self-referential on exactly that shape.
_CLIENT_PROPERTY_ORDER_DIGEST = (
    "759631f346cec56ae0cfd055a70360a51b7e1bedfc7ff6bb976b70ac56fd1e8a"
)
_EXPECTED_CLIENT_PROPERTY_ORDER_ROWS = 2083

# A direct property declaration in a generated component block, at the one
# indentation level the generator uses for top-level component fields. Nested
# inline object fields are two levels deeper and are deliberately not read.
_PROPERTY_DECL = re.compile(
    r'^            (?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\??:', re.M
)

# Reviewed, hand-written fixed point on the generated client's JSDoc title
# *sequence*. Every door above is order-insensitive on this surface: Door 6
# pins a sorted digest, Door 7 pins sorted ``component|field|title`` rows,
# Door 8 looks a title up by ``(component, field)``, and Door 9 walks property
# declarations, not the ``*`` prose lines above them. So a declaration-only
# swap -- move two adjacent property lines, leave each ``/**`` block where it
# is -- keeps every count, both multisets and every pinned row intact while the
# label a reader sees above a field changes. sha256 over the titles in document
# order; read from nowhere, regenerate with
# _digest_client_title_sequence() after an intentional, reviewed reorder, in
# the same commit as both artifacts, with a reason.
_CLIENT_TITLE_SEQUENCE_DIGEST = (
    "e5d5c74091be283cc1df3cb2b7f92a1a19f36a173c8a8fd997d3a4d4074c4a65"
)
_ORDER_SNAPSHOT_TITLE_SEQUENCE_DIGEST = (
    "d28b247eb2bd4a5af47084792c39d297de8de2523241efb6c80ca59fd6ff74b8"
)
_EXPECTED_CLIENT_TITLE_LINES = 1232


def _first_plain_line(doc: str) -> str | None:
    for line in doc.splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if not line or line.startswith("@") or line == "/":
            continue
        return line
    return None


def client_title_rows(generated: str) -> list[tuple[str, str, str]]:
    """(component, field, leading JSDoc line) for every documented field."""
    block = _COMPONENT_SCHEMAS.search(generated)
    if block is None:
        raise ValueError("generated client has no components.schemas block")
    out: list[tuple[str, str, str]] = []
    for schema in _SCHEMA_BLOCK.finditer(block.group("body")):
        name = schema.group("name")
        for field in _FIELD_DOC.finditer(schema.group("body")):
            title = _first_plain_line(field.group("doc"))
            if title is not None:
                out.append((name, field.group("field"), title))
    return out


def _digest_client_title_rows(rows_: list[tuple[str, str, str]]) -> str:
    canonical = sorted(f"{c}|{f}|{t}" for c, f, t in rows_)
    blob = "\n".join(["soymutdb-client-schema-title-rows/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def property_order_rows(document: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Canonical (component, index, field) rows in snapshot insertion order."""
    out: list[tuple[str, str, str]] = []
    for name, schema in document.get("components", {}).get("schemas", {}).items():
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for index, field in enumerate(properties):
                out.append((name, str(index), field))
    return out


def client_property_order_rows(generated: str) -> list[tuple[str, str, str]]:
    """Canonical (component, index, field) rows from generated blocks.

    Only the ``components.schemas`` region is walked, so ``operations`` and
    ``parameters`` sub-blocks (also 8-space indented) cannot be mistaken for
    component definitions. The index is the property's position inside its
    own block, which is what a caller sees in the emitted interface.
    """
    block = _COMPONENT_SCHEMAS.search(generated)
    if block is None:
        return []
    out: list[tuple[str, str, str]] = []
    for schema in _SCHEMA_BLOCK.finditer(block.group("body")):
        for index, field in enumerate(_PROPERTY_DECL.finditer(schema.group("body"))):
            out.append(
                (schema.group("name"), str(index), field.group(1) or field.group(2))
            )
    return out


def _digest_property_order(rows_: list[tuple[str, str, str]]) -> str:
    canonical = sorted(f"{c}|{i}|{f}" for c, i, f in rows_)
    blob = "\n".join(["soymutdb-component-property-order/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _digest_client_property_order(rows_: list[tuple[str, str, str]]) -> str:
    canonical = sorted(f"{c}|{i}|{f}" for c, i, f in rows_)
    blob = "\n".join(["soymutdb-client-component-property-order/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# Third hand-written literal in this guard: the generated client's *continuation*
# prose. The two literals above read only ``@description`` first lines; a
# multi-line description also renders 204 indented ``*     ...`` lines (50
# description nodes) that no landed door reads. sha256 over canonical sorted
# ``(component|description|index|prose)`` rows, read from nowhere. A one-sided
# rewrite, a drop, a same-count relocation between nodes, and a coordinated
# co-revert with both blob ids re-pinned all move it. Regenerate with
# _digest_client_continuations() after an intentional, reviewed prose change,
# in the same commit as both artifacts, with a reason.
_CLIENT_DESCRIPTION_CONTINUATION_DIGEST = (
    "ccc25f1c2e289f12bcefa716408896282c0a9ef8eb3a8386fb9b0f58d99867e8"
)
_EXPECTED_CLIENT_CONTINUATION_ROWS = 204
_EXPECTED_CLIENT_CONTINUATION_NODES = 50

_CONTINUATION_LINE = re.compile(r"^\s*\*\s{4,}(\S.*)$")
_COMPONENT_NAME = re.compile(r"^        (\w+): \{$")


def client_description_continuations(
    generated: str,
) -> list[tuple[str, str, str, str]]:
    """(component, description, index, prose) rows of generated continuation prose.

    Only JSDoc blocks carrying an ``@description`` first line own continuation
    rows; a ``@default`` block that renders a multi-line array is deliberately
    excluded -- its indented lines are a value, not published description
    prose. The row is keyed by (component, description, index) so a line that
    moves to another description node or another position changes the digest
    even when the total count is preserved.
    """
    block = _COMPONENT_SCHEMAS.search(generated)
    if block is None:
        raise ValueError("generated client has no components.schemas block")
    out: list[tuple[str, str, str, str]] = []
    component: str | None = None
    doc: list[str] = []
    in_doc = False
    for line in block.group("body").splitlines():
        match = _COMPONENT_NAME.match(line)
        if match:
            component = match.group(1)
            continue
        if line.strip().startswith("/**"):
            in_doc = True
            doc = []
            continue
        if in_doc:
            doc.append(line)
            if line.strip() == "*/":
                descs = _DESCRIPTION_LINE.findall("\n".join(doc))
                if descs:
                    owner = descs[0]
                    index = 0
                    for entry in doc:
                        prose = _CONTINUATION_LINE.match(entry)
                        if prose:
                            out.append(
                                (component or "", owner, str(index), prose.group(1))
                            )
                            index += 1
                in_doc = False
                doc = []
    return out


def _digest_client_continuations(
    rows_: list[tuple[str, str, str, str]],
) -> str:
    canonical = sorted(f"{c}|{d}|{i}|{t}" for c, d, i, t in rows_)
    blob = "\n".join(
        ["soymutdb-client-schema-description-continuations/v1", *canonical]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _digest_client_title_sequence(lines: list[str]) -> str:
    """Positional digest: the titles exactly as the generator printed them.

    ``_digest_client_title`` sorts, so it cannot see a rotation. This one
    keeps document order, which is the order a reader of the emitted
    interface sees.
    """
    blob = "\n".join(["soymutdb-client-schema-title-sequence/v1", *lines])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def snapshot_title_sequence_rows(document: dict[str, Any]) -> list[tuple[str, str]]:
    """(schema path, leading title line) in snapshot insertion order."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            title = node.get("title")
            if isinstance(title, str):
                out.append((path, title))
            for name, child in node.items():
                if name == "title" or not isinstance(child, (dict, list)):
                    continue
                walk(child, f"{path}/{name}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}")

    walk(document, "schema")
    return out


def _digest_snapshot_title_sequence(rows_: list[tuple[str, str]]) -> str:
    """Positional digest over the snapshot's own title lines, in order."""
    blob = "\n".join(
        ["soymutdb-snapshot-title-sequence/v1", *(f"{p}|{v}" for p, v in rows_)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    digest: str | None = None,
    expected_rows: int | None = None,
    expected_schemas: int | None = None,
    title_digest: str | None = None,
    client_title_digest: str | None = None,
    expected_title_rows: int | None = None,
    expected_title_schemas: int | None = None,
    client_title_rows_digest: str | None = None,
    expected_client_title_rows: int | None = None,
    client_description_sequence_digest: str | None = None,
    expected_client_description_lines: int | None = None,
    client_continuation_digest: str | None = None,
    expected_client_continuation_rows: int | None = None,
    expected_client_continuation_nodes: int | None = None,
    property_order_digest: str | None = None,
    expected_property_order_rows: int | None = None,
    expected_property_order_schemas: int | None = None,
    client_property_order_digest: str | None = None,
    expected_client_property_order_rows: int | None = None,
    component_definition_order_digest: str | None = None,
    expected_component_definitions: int | None = None,
    client_title_sequence_digest: str | None = None,
    snapshot_title_sequence_digest: str | None = None,
    expected_client_title_lines: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = GENERATED.read_text(encoding="utf-8")
    try:
        document = json.loads(snapshot)
        rows_ = rows(document)
        client = client_descriptions(generated)
        titles_ = title_rows(document)
        client_title_lines = client_titles(generated)
        client_title_triples = client_title_rows(generated)
        client_continuations = client_description_continuations(generated)
        property_order = property_order_rows(document)
        client_property_order = client_property_order_rows(generated)
        component_order = component_definition_order(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published schema descriptions: {exc}"]

    pinned_digest = _SCHEMA_DESCRIPTION_DIGEST if digest is None else digest
    pinned_rows = _EXPECTED_ROWS if expected_rows is None else expected_rows
    pinned_schemas = _EXPECTED_SCHEMAS if expected_schemas is None else expected_schemas

    # Door 1 -- independent fixed point over the whole prose surface.
    actual = _digest(rows_)
    if actual != pinned_digest:
        found.append(
            "published schema descriptions drifted: _SCHEMA_DESCRIPTION_DIGEST "
            f"pins {pinned_digest} but the snapshot derives {actual}. A "
            "baseline is a fixed point for the artifact, not a place to make a "
            "guard agree with itself -- re-pin the digest in the same commit "
            "as both artifacts, with a reason."
        )

    # Door 2 -- exact shape doors. A drop or add is named even when a digest
    # is re-pinned, and a same-count rotation cannot hide behind the counts.
    if len(rows_) != pinned_rows:
        found.append(
            f"published description row count is {len(rows_)}, "
            f"_EXPECTED_ROWS pins {pinned_rows}: a description was added or "
            "dropped without moving the fixed point"
        )
    schemas = {path.split("/", 1)[0] for path, _ in rows_}
    if len(schemas) != pinned_schemas:
        found.append(
            f"descriptions span {len(schemas)} component schemas, "
            f"_EXPECTED_SCHEMAS pins {pinned_schemas}"
        )

    # Door 3 -- the generated client half, checked against the pinned rows
    # (not against the drifted snapshot), so a coordinated regenerate cannot
    # pass by making both halves agree on a drift.
    pinned_first_lines = Counter(value.split("\n", 1)[0] for _, value in rows_)
    expected_client = pinned_first_lines.copy()
    expected_client[_SYNTHETIC_CLIENT_DESCRIPTION] += 1
    observed_client = Counter(client)
    if observed_client != expected_client:
        missing = sorted((expected_client - observed_client).elements())
        extra = sorted((observed_client - expected_client).elements())
        found.append(
            "generated client @description lines disagree with the pinned "
            f"schema prose (missing={missing[:4]}, extra={extra[:4]})"
        )

    # Door 3b -- a second, independent fixed point for the description half.
    # Door 3 is a multiset against the pinned snapshot rows: a same-count
    # rotation of three generated lines keeps that multiset and every count
    # green, and a coordinated co-revert that honestly re-pins only the
    # snapshot digest makes the two halves agree with themselves. This literal
    # is read from nowhere, so both shapes still move it.
    pinned_client_sequence = (
        _CLIENT_DESCRIPTION_SEQUENCE_DIGEST
        if client_description_sequence_digest is None
        else client_description_sequence_digest
    )
    actual_client_sequence = _digest_client_description_sequence(client)
    if actual_client_sequence != pinned_client_sequence:
        found.append(
            "generated client @description sequence drifted: "
            f"_CLIENT_DESCRIPTION_SEQUENCE_DIGEST pins "
            f"{pinned_client_sequence} but the client derives "
            f"{actual_client_sequence}. A client-visible description line "
            "moved or retyped; re-pin the literal in the same commit as both "
            "artifacts, with a reason."
        )
    pinned_client_lines = (
        _EXPECTED_CLIENT_DESCRIPTION_LINES
        if expected_client_description_lines is None
        else expected_client_description_lines
    )
    if len(client) != pinned_client_lines:
        found.append(
            f"generated client @description line count is {len(client)}, "
            f"_EXPECTED_CLIENT_DESCRIPTION_LINES pins {pinned_client_lines}: "
            "a description was added or dropped without moving the literal"
        )

    # Door 3c -- a third hand-written literal in this guard, over the
    # component-schema share of the same continuation projection #314 pins on
    # ``paths``. Doors 3 / 3b read only ``@description`` first lines; the
    # generated client also renders 204 indented continuation lines across 50
    # description nodes, and no landed fixed point reads them. A coordinated
    # co-revert of both halves with both provenance blob ids honestly re-pinned
    # stayed green: the snapshot digest, the first-line multiset and the
    # first-line sequence all still agreed. This literal is read from nowhere
    # and keyed by (component, description, index), so a rewrite, a drop, or a
    # same-count relocation between nodes moves it.
    pinned_continuation = (
        _CLIENT_DESCRIPTION_CONTINUATION_DIGEST
        if client_continuation_digest is None
        else client_continuation_digest
    )
    actual_continuation = _digest_client_continuations(client_continuations)
    if actual_continuation != pinned_continuation:
        found.append(
            "generated client description continuations drifted: "
            f"_CLIENT_DESCRIPTION_CONTINUATION_DIGEST pins "
            f"{pinned_continuation} but the client derives "
            f"{actual_continuation}. Re-pin the literal in the same commit "
            "as both artifacts, with a reason."
        )
    pinned_continuation_rows = (
        _EXPECTED_CLIENT_CONTINUATION_ROWS
        if expected_client_continuation_rows is None
        else expected_client_continuation_rows
    )
    if len(client_continuations) != pinned_continuation_rows:
        found.append(
            f"generated client description continuation row count is "
            f"{len(client_continuations)}, "
            f"_EXPECTED_CLIENT_CONTINUATION_ROWS pins "
            f"{pinned_continuation_rows}: a published description "
            "continuation was dropped or invented in openapi.d.ts"
        )
    continuation_nodes = {(c, d) for c, d, _i, _t in client_continuations}
    pinned_continuation_nodes = (
        _EXPECTED_CLIENT_CONTINUATION_NODES
        if expected_client_continuation_nodes is None
        else expected_client_continuation_nodes
    )
    if len(continuation_nodes) != pinned_continuation_nodes:
        found.append(
            f"generated client description continuations span "
            f"{len(continuation_nodes)} description nodes, "
            f"_EXPECTED_CLIENT_CONTINUATION_NODES pins "
            f"{pinned_continuation_nodes}"
        )

    # Door 4 -- independent fixed point over the whole published title surface.
    pinned_title_digest = (
        _SCHEMA_TITLE_DIGEST if title_digest is None else title_digest
    )
    actual_title_digest = _digest_title(titles_)
    if actual_title_digest != pinned_title_digest:
        found.append(
            "published schema titles drifted: _SCHEMA_TITLE_DIGEST pins "
            f"{pinned_title_digest} but the snapshot derives "
            f"{actual_title_digest}. A baseline is a fixed point for the "
            "artifact, not a place to make a guard agree with itself -- re-pin "
            "the digest in the same commit as both artifacts, with a reason."
        )

    # Door 5 -- exact shape doors for the title surface.
    pinned_title_rows = (
        _EXPECTED_TITLE_ROWS if expected_title_rows is None else expected_title_rows
    )
    pinned_title_schemas = (
        _EXPECTED_TITLE_SCHEMAS
        if expected_title_schemas is None
        else expected_title_schemas
    )
    if len(titles_) != pinned_title_rows:
        found.append(
            f"published title row count is {len(titles_)}, "
            f"_EXPECTED_TITLE_ROWS pins {pinned_title_rows}: a title was added "
            "or dropped without moving the fixed point"
        )
    title_schemas = {path.split("/", 1)[0] for path, _ in titles_}
    if len(title_schemas) != pinned_title_schemas:
        found.append(
            f"titles span {len(title_schemas)} component schemas, "
            f"_EXPECTED_TITLE_SCHEMAS pins {pinned_title_schemas}"
        )

    # Door 6 -- independent fixed point on the generated client's JSDoc title
    # lines. Both artifacts are exports of one source, so a digest over the
    # client lines (read from nowhere) catches a coordinated co-revert that
    # moves both halves together; comparing the client against the snapshot
    # under guard would be self-referential and pass on that exact shape.
    actual_client_digest = _digest_client_title(client_title_lines)
    pinned_client_digest = (
        _CLIENT_TITLE_DIGEST if client_title_digest is None else client_title_digest
    )
    if actual_client_digest != pinned_client_digest:
        found.append(
            "generated client JSDoc titles drifted: _CLIENT_TITLE_DIGEST pins "
            f"{pinned_client_digest} but the client derives "
            f"{actual_client_digest}. Re-pin the digest in the same commit as "
            "both artifacts, with a reason."
        )
    if len(client_title_lines) != _EXPECTED_CLIENT_TITLE_LINES:
        found.append(
            f"generated client JSDoc title line count is "
            f"{len(client_title_lines)}, _EXPECTED_CLIENT_TITLE_LINES pins "
            f"{_EXPECTED_CLIENT_TITLE_LINES}"
        )
    if client_title_lines.count(_SYNTHETIC_CLIENT_TITLE) != 1:
        found.append(
            "generated client JSDoc titles carry "
            f"{client_title_lines.count(_SYNTHETIC_CLIENT_TITLE)} synthetic "
            f"{_SYNTHETIC_CLIENT_TITLE!r} line(s), expected exactly one"
        )

    # Door 7 -- independent fixed point over the *positional* client triples.
    # Door 6 pins a sorted digest, so a same-count rotation of two title
    # lines keeps the multiset and the counts intact and passes every door
    # above. This one carries the field name, so a swap moves it.
    pinned_rows_digest = (
        _CLIENT_TITLE_ROWS_DIGEST
        if client_title_rows_digest is None
        else client_title_rows_digest
    )
    actual_rows_digest = _digest_client_title_rows(client_title_triples)
    if actual_rows_digest != pinned_rows_digest:
        found.append(
            "generated client JSDoc title rows drifted: "
            f"_CLIENT_TITLE_ROWS_DIGEST pins {pinned_rows_digest} but the "
            f"client derives {actual_rows_digest}. A field label moved to "
            "another field; re-pin the literal in the same commit as both "
            "artifacts, with a reason."
        )

    pinned_rows_count = (
        _EXPECTED_CLIENT_TITLE_ROWS
        if expected_client_title_rows is None
        else expected_client_title_rows
    )
    if len(client_title_triples) != pinned_rows_count:
        found.append(
            "generated client JSDoc title row count is "
            f"{len(client_title_triples)}, _EXPECTED_CLIENT_TITLE_ROWS pins "
            f"{pinned_rows_count}: a documented field gained or lost its "
            "leading title line"
        )

    # Door 8 -- positional cross-artifact door. Every generated triple must
    # match the *pinned* snapshot row for that (component, field), so a
    # one-sided edit is named by component and field instead of only moving
    # a digest.
    published_titles = {
        (path.split("/")[0], path.split("/")[2]): value
        for path, value in titles_
        if len(path.split("/")) == 3 and path.split("/")[1] == "properties"
    }
    for component, field, title in client_title_triples:
        expected = published_titles.get((component, field))
        if expected is None:
            found.append(
                f"generated client documents {component}.{field} with title "
                f"{title!r}, but the snapshot publishes no title for it"
            )
        elif expected != title:
            found.append(
                f"generated client title for {component}.{field} is {title!r} "
                f"but the snapshot publishes {expected!r}"
            )

    # Door 9 -- component-property declaration order. Every landed digest on
    # this surface walks values or field sets, never the positional
    # (component, index, field) triple. Rotating two adjacent properties in
    # both halves (with the provenance blob ids honestly re-pinned) therefore
    # kept the whole contracts layer green while two client-visible
    # declarations swapped. Two independent literals pin the order, one per
    # artifact half, so re-pinning one cannot silence the other.
    pinned_order = (
        _PROPERTY_ORDER_DIGEST
        if property_order_digest is None
        else property_order_digest
    )
    actual_order = _digest_property_order(property_order)
    if actual_order != pinned_order:
        found.append(
            "published component property order drifted: _PROPERTY_ORDER_DIGEST "
            f"pins {pinned_order} but the snapshot derives {actual_order}. "
            "A fixed point is pinned against the artifact, not derived from it "
            "-- re-pin the digest in the same commit as both artifacts, with a "
            "reason."
        )
    pinned_order_rows = (
        _EXPECTED_PROPERTY_ORDER_ROWS
        if expected_property_order_rows is None
        else expected_property_order_rows
    )
    pinned_order_schemas = (
        _EXPECTED_PROPERTY_ORDER_SCHEMAS
        if expected_property_order_schemas is None
        else expected_property_order_schemas
    )
    if len(property_order) != pinned_order_rows:
        found.append(
            f"published component property row count is {len(property_order)}, "
            f"_EXPECTED_PROPERTY_ORDER_ROWS pins {pinned_order_rows}: a property "
            "was added or dropped without moving the fixed point"
        )
    order_schemas = {row[0] for row in property_order}
    if len(order_schemas) != pinned_order_schemas:
        found.append(
            f"published component property order spans {len(order_schemas)} "
            f"schemas, _EXPECTED_PROPERTY_ORDER_SCHEMAS pins "
            f"{pinned_order_schemas}"
        )

    pinned_client_order = (
        _CLIENT_PROPERTY_ORDER_DIGEST
        if client_property_order_digest is None
        else client_property_order_digest
    )
    actual_client_order = _digest_client_property_order(client_property_order)
    if actual_client_order != pinned_client_order:
        found.append(
            "generated client component property order drifted: "
            f"_CLIENT_PROPERTY_ORDER_DIGEST pins {pinned_client_order} but the "
            f"client derives {actual_client_order}. The two digests must move "
            "in the same commit as an intentional contract change; re-pinning "
            "only the snapshot side leaves this door red."
        )
    pinned_client_order_rows = (
        _EXPECTED_CLIENT_PROPERTY_ORDER_ROWS
        if expected_client_property_order_rows is None
        else expected_client_property_order_rows
    )
    if len(client_property_order) != pinned_client_order_rows:
        found.append(
            f"generated client component property row count is "
            f"{len(client_property_order)}, "
            f"_EXPECTED_CLIENT_PROPERTY_ORDER_ROWS pins "
            f"{pinned_client_order_rows}"
        )

    # Named positional agreement: a one-sided reorder is reported by the
    # component and field that moved, not only by a moved digest. Checked
    # against the pinned snapshot rows, so a coordinated regenerate cannot
    # pass by making both halves agree on the drifted order.
    if property_order != client_property_order:
        snap_map = {(c, i): f for c, i, f in property_order}
        cli_map = {(c, i): f for c, i, f in client_property_order}
        for key in sorted(set(snap_map) | set(cli_map)):
            if snap_map.get(key) != cli_map.get(key):
                found.append(
                    f"generated client component property order disagrees at "
                    f"{key[0]}[{key[1]}]: snapshot publishes "
                    f"{snap_map.get(key)!r}, client prints {cli_map.get(key)!r}"
                )
                break


    # Door 12 -- independent fixed point over the component *definition*
    # order. Doors 1/4/6/7 sort, and Door 8 looks a row up by field, so a
    # byte-preserving rotation of two adjacent definitions (or a description
    # row moving between two components) keeps every door above green while
    # the generated interface order -- a client-visible published fact --
    # changes.
    pinned_component_order = (
        _COMPONENT_DEFINITION_ORDER_DIGEST
        if component_definition_order_digest is None
        else component_definition_order_digest
    )
    actual_component_order = _digest_component_definition_order(component_order)
    if actual_component_order != pinned_component_order:
        found.append(
            "published component definition order drifted: "
            "_COMPONENT_DEFINITION_ORDER_DIGEST pins "
            f"{pinned_component_order} but the snapshot derives "
            f"{actual_component_order}. Every door above sorts its rows, so "
            "a reordered components.schemas block is invisible to them; the "
            "generated interfaces keep the snapshot's order. Re-pin the "
            "literal in the same commit as both artifacts, with a reason."
        )

    pinned_component_count = (
        _EXPECTED_COMPONENT_DEFINITIONS
        if expected_component_definitions is None
        else expected_component_definitions
    )
    if len(component_order) != pinned_component_count:
        found.append(
            f"component definition count is {len(component_order)}, "
            f"_EXPECTED_COMPONENT_DEFINITIONS pins {pinned_component_count}: "
            "a schema was added or dropped without moving the fixed point"
        )

    # Door 10 -- positional title sequence. Doors 6/7 pin sorted shapes, Door
    # 8 looks a title up by (component, field), and Door 9 walks property
    # declarations rather than the ``*`` prose lines above them. A
    # declaration-only swap therefore keeps every count, both multisets and
    # every pinned row intact while two labels change place in the emitted
    # interface. Two independent positional literals -- one per artifact half
    # -- pin that order, so re-pinning either half alone cannot silence the
    # other.
    pinned_sequence = (
        _CLIENT_TITLE_SEQUENCE_DIGEST
        if client_title_sequence_digest is None
        else client_title_sequence_digest
    )
    actual_sequence = _digest_client_title_sequence(client_title_lines)
    if actual_sequence != pinned_sequence:
        found.append(
            "generated client JSDoc title sequence drifted: "
            f"_CLIENT_TITLE_SEQUENCE_DIGEST pins {pinned_sequence} but the "
            f"client derives {actual_sequence}. A client-visible field label "
            "moved to another position; re-pin the literal in the same commit "
            "as both artifacts, with a reason."
        )
    pinned_sequence_lines = (
        _EXPECTED_CLIENT_TITLE_LINES
        if expected_client_title_lines is None
        else expected_client_title_lines
    )
    if len(client_title_lines) != pinned_sequence_lines:
        found.append(
            f"generated client JSDoc title line count is "
            f"{len(client_title_lines)}, _EXPECTED_CLIENT_TITLE_LINES pins "
            f"{pinned_sequence_lines}: a title line was added or dropped "
            "without moving the positional literal"
        )

    pinned_snapshot_sequence = (
        _ORDER_SNAPSHOT_TITLE_SEQUENCE_DIGEST
        if snapshot_title_sequence_digest is None
        else snapshot_title_sequence_digest
    )
    actual_snapshot_sequence = _digest_snapshot_title_sequence(
        snapshot_title_sequence_rows(document)
    )
    if actual_snapshot_sequence != pinned_snapshot_sequence:
        found.append(
            "published schema title sequence drifted: "
            f"_ORDER_SNAPSHOT_TITLE_SEQUENCE_DIGEST pins "
            f"{pinned_snapshot_sequence} but the snapshot derives "
            f"{actual_snapshot_sequence}. Re-pinning only the client half "
            "leaves this door red."
        )

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    problems = failures()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-schema-descriptions: OK ({_EXPECTED_ROWS} published "
        f"descriptions and {_EXPECTED_TITLE_ROWS} titles pinned across "
        f"{_EXPECTED_SCHEMAS} / {_EXPECTED_TITLE_SCHEMAS} schemas, "
        f"{_EXPECTED_CLIENT_CONTINUATION_ROWS} generated continuations, "
        f"{_EXPECTED_COMPONENT_DEFINITIONS} component definitions pinned "
        f"in order, {_EXPECTED_PROPERTY_ORDER_ROWS} component property order "
        "rows pinned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

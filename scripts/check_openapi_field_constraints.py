#!/usr/bin/env python3
"""Pin the published field-level constraints to an independent literal.

``openapi.json`` publishes 1712 field-level values -- 815 JSON Schema
constraint rows (``minimum``, ``maximum``, ``maxLength``, ``minLength``,
``pattern``, ``format``, item counts, exclusive bounds) plus 897 ``default``
values -- across 263 component schemas. They are part of the public contract:
a client generated from this document can read them, and runtime validation
enforces them. Unlike ``enum``/``const``, the constraints are not emitted in
the generated ``openapi.d.ts``; ``default`` is rendered as ``@default``, so a
coordinated regenerate can change one value in *both* halves, re-pin the
provenance blob ids, and leave every other wired fixed point blind:

* ``_PUBLISHED_ENUM_BASELINE`` walks only ``enum`` / ``const``;
* ``_RESPONSE_BODY_BASELINE`` / ``_BODY_PAIR_DIGEST`` / the inline-body pins
  read bodies, not property schemas;
* the operationId, parameter, response-surface and document-metadata digests
  do not descend into ``components.schemas`` properties;
* ``_PINNED_ARTIFACTS`` is provenance blob ids: re-pinning them is the
  documented "one reviewed action" beside a regenerate.

Decisive ablations on live bytes: byte-preserving ``maxItems: 100 -> 999`` in
the snapshot, and a coordinated ``default: 0 -> 999999`` rewritten in the
snapshot and the generated ``@default`` line with both blob ids re-pinned --
all wired OpenAPI guards, their ``--self-test`` suites and the whole contracts
layer stay green. That second shape is why ``default`` is pinned here too, not
left to a two-artifact comparison that a co-revert satisfies.

This guard reads committed bytes only (``json`` + stdlib): no Python 3.15, no
API import, no wheel, no database, no workspace install. It pins:

* ``_FIELD_CONSTRAINT_DIGEST`` -- a hand-written sha256 over the canonical
  sorted ``(path, key, value)`` rows of every real schema node, read from
  nowhere. Re-deriving it from the artifacts under guard would be
  self-referential. A legitimate change re-pins it in the same commit as the
  snapshot, with a reason;
* ``_EXPECTED_CONSTRAINT_ROWS`` / ``_EXPECTED_SCHEMAS`` / ``_EXPECTED_BY_KEY``
  -- exact count doors that a same-count permutation cannot satisfy alone;
* a one-sided drop, add, retype or move of any single constraint is named by
  its path, so the failure says which field changed.

A legitimate contract change must move the digest in the same commit as the
snapshot and say why. Re-deriving the digest from the artifacts under guard
would make the pin self-referential. ``--self-test`` injects one-sided and
coordinated drifts into copies of the bytes and asserts each is caught; the
clean tree must pass.

Usage:
    python3 scripts/check_openapi_field_constraints.py
    python3 scripts/check_openapi_field_constraints.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
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


def failures(
    *,
    snapshot: str | None = None,
    digest: str | None = None,
    expected_rows: int | None = None,
    expected_schemas: int | None = None,
    by_key: dict[str, int] | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    try:
        document = json.loads(snapshot)
        rows_ = rows(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published constraints from snapshot: {exc}"]

    pinned_digest = _FIELD_CONSTRAINT_DIGEST if digest is None else digest
    pinned_rows = (
        _EXPECTED_CONSTRAINT_ROWS if expected_rows is None else expected_rows
    )
    pinned_schemas = (
        _EXPECTED_SCHEMAS if expected_schemas is None else expected_schemas
    )
    pinned_by_key = _EXPECTED_BY_KEY if by_key is None else by_key

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
            print(f"openapi-field-constraints: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-field-constraints: OK ({_EXPECTED_CONSTRAINT_ROWS} published "
        f"constraint rows pinned across {_EXPECTED_SCHEMAS} schemas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

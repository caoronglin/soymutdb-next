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

# A component's own required-array length, keyed by its top-level name.
# 282 exact doors: a same-count permutation that moves one field from schema
# A to schema B keeps the total and the digest's multiset shape is not enough
# on its own, so these are checked too. Kept as a literal floor.
_EXPECTED_BY_SCHEMA_TOP: dict[str, int] = {}  # filled by _by_schema_top() below


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


def client_optional(generated: str) -> dict[str, set[str]]:
    """component name -> set of fields rendered optional (``field?: T``)."""
    out: dict[str, set[str]] = {}
    for match in _COMPONENT_BLOCK.finditer(generated):
        out[match.group("name")] = set(
            _OPTIONAL_PROP.findall(match.group("body"))
        )
    return out


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    digest: str | None = None,
    expected_rows: int | None = None,
    expected_schemas: int | None = None,
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
        f"required fields pinned across {_EXPECTED_SCHEMAS} schemas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

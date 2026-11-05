#!/usr/bin/env python3
"""Pin the published operation-parameter surface to an independent literal.

``openapi.json`` and ``src/generated/openapi.d.ts`` are both exports of
``app.main:app``. A guard that compares them to each other proves
self-consistency, not truth. The 467 published parameters are client-visible:
``openapi-typescript`` turns each one into a property of the generated
``operations[*].parameters`` object, so a renamed/retyped/dropped parameter
changes the TypeScript a consumer compiles against. Nothing in the contracts
layer read them -- the enum guard walks value domains, the body guard walks
``$ref`` bodies, the operationId guard walks symbol names, and the auth guard
walks ``security``. A parameter is none of those.

Decisive ablation on live bytes: rename one query parameter in *both* halves
together (the snapshot's ``paths.*.*.parameters[].name`` and the generated
client's ``query`` property), re-pin the two provenance blob ids in
``test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS`` -- the "one
deliberate reviewed action" that guard's own docstring admits -- and every
wired OpenAPI guard stays ``rc=0`` while the contracts layer prints
``SMOKE PASS``. A coordinated regenerate of a renamed request field is exactly
this shape: both artifacts agree with each other, and no fixed point says the
old parameter was ever published.

This guard reads committed bytes only (``json`` + ``re`` + stdlib): no Python
3.15, no API import, no wheel, no database, no workspace install. It pins:

* ``_PARAMETER_DIGEST`` -- a hand-written sha256 over the canonical sorted
  ``(METHOD path, index, name, in, required, schema)`` tuples, read from
  nowhere. Exported from both artifacts independently, so a co-revert of both
  halves still changes it;
* ``_EXPECTED_PARAMETER_COUNT`` -- the exact number of published parameters,
  a second, count-level door that a same-count permutation alone cannot pass;
* three-way agreement: the snapshot's parameter identity set per operation ==
  the generated ``operations[*].parameters`` property set (name, location,
  requiredness). A one-sided edit is named by operation and parameter.

Uniqueness and shape are checked too: two parameters sharing one
``(in, name)`` on the same operation are a broken contract, and a location
outside ``query``/``header``/``path``/``cookie`` is not publishable.

A legitimate change must move the digest in the same commit as both artifacts
and say why, exactly like ``_OPERATION_ID_DIGEST`` /
``_PUBLISHED_ENUM_BASELINE`` / ``_BODY_PAIR_DIGEST``. Re-deriving the digest
from the artifacts under guard would make the pin self-referential, which is
the whole failure this file replaces. ``--self-test`` injects one-sided drifts
into copies of the bytes and asserts each is caught; the clean tree must pass.

Usage:
    python3 scripts/check_openapi_operation_parameter_floor.py
    python3 scripts/check_openapi_operation_parameter_floor.py --self-test
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
SMOKE = ROOT / "scripts" / "smoke.sh"
SELF = Path(__file__).name

METHODS = frozenset(
    {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
)
LOCATIONS = frozenset({"query", "header", "path", "cookie"})

# A reviewed, hand-written fixed point on the published parameter surface.
# sha256 of "\n".join(["soymutdb-operation-parameters/v1"] + sorted rows),
# each row being the eight space-joined fields of a parameter tuple (schema
# serialised with sort_keys=True, ensure_ascii=False). Regenerate with
# _digest() after an intentional contract change and update in the same
# commit, with a reason.
_PARAMETER_DIGEST = "e8b5b11d4a9a2ced2614d8d7939e6c31b9f5377cb7bfa7a2445e28d1b6245872"
_EXPECTED_PARAMETER_COUNT = 467
_EXPECTED_OPERATION_COUNT = 268

# ``operations[*].parameters`` group header: "            query?: {" or
# "            query?: never;". The optional marker on the group is emitted
# by the generator when the whole group may be absent; requiredness of an
# individual parameter is the optional marker on its own property.
GEN_OP_KEY = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_]*): \{$", re.MULTILINE)
GEN_GROUP = re.compile(r"^ {12}(query|header|path|cookie)\??: (never|\{)$")
GEN_PROP = re.compile(
    r'^ {16}(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))(\??): [^;]+;$'
)


def _snapshot_parameters(document: dict[str, Any]) -> list[tuple[str, ...]]:
    """Canonical rows for every parameter of every published operation."""
    rows: list[tuple[str, ...]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            oid = operation.get("operationId")
            if not isinstance(oid, str):
                raise ValueError(f"{method.upper()} {path} has no string operationId")
            for index, parameter in enumerate(operation.get("parameters", []) or []):
                if not isinstance(parameter, dict):
                    raise ValueError(f"{method.upper()} {path} parameter {index} is not an object")
                name = parameter.get("name")
                location = parameter.get("in")
                if not isinstance(name, str) or not isinstance(location, str):
                    raise ValueError(f"{method.upper()} {path} parameter {index} has no name/in")
                schema = json.dumps(parameter.get("schema", {}), sort_keys=True, ensure_ascii=False)
                rows.append(
                    (
                        method.upper(),
                        path,
                        oid,
                        str(index),
                        name,
                        location,
                        "true" if parameter.get("required") else "false",
                        schema,
                    )
                )
    return rows


def _snapshot_identity(document: dict[str, Any]) -> dict[str, set[tuple[str, str, bool]]]:
    """operationId -> {(in, name, required)} from the snapshot.

    Every published operation gets a key, including the ones with no
    parameters: the generated client declares all of them, so a missing key
    here would read as a phantom operation instead of an empty group.
    """
    out: dict[str, set[tuple[str, str, bool]]] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                oid = operation.get("operationId")
                if isinstance(oid, str):
                    out.setdefault(oid, set())
    for row in _snapshot_parameters(document):
        out[row[2]].add((row[5], row[4], row[6] == "true"))
    return out


def _generated_identity(generated: str) -> dict[str, set[tuple[str, str, bool]]]:
    """operationId -> {(in, name, required)} from the generated client."""
    marker = "export interface operations {"
    if marker not in generated:
        raise ValueError("generated client declares no operations interface")
    body = generated.split(marker, 1)[1]
    starts = [(m.start(), m.group(1)) for m in GEN_OP_KEY.finditer(body)]
    out: dict[str, set[tuple[str, str, bool]]] = {}
    for index, (position, key) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(body)
        lines = body[position:end].splitlines()
        identity: set[tuple[str, str, bool]] = set()
        in_parameters = False
        current: str | None = None
        for line in lines:
            if line == "        parameters: {":
                in_parameters = True
                continue
            if not in_parameters:
                continue
            if line == "        };":
                break
            group = GEN_GROUP.match(line)
            if group:
                current = group.group(1) if group.group(2) == "{" else None
                continue
            if line == "            };":
                current = None
                continue
            if current:
                prop = GEN_PROP.match(line)
                if prop:
                    name = prop.group(1) or prop.group(2)
                    # A property is required when it has no `?`; the group's
                    # own `?` only says the whole group may be absent.
                    identity.add((current, name, prop.group(3) != "?"))
        out[key] = identity
    return out


def _digest(rows: list[tuple[str, ...]]) -> str:
    blob = "\n".join(
        ["soymutdb-operation-parameters/v1"] + [" ".join(row) for row in sorted(rows)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    smoke: str | None = None,
    digest: str | None = None,
    expected_count: int | None = None,
    expected_operations: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = GENERATED.read_text(encoding="utf-8")
    if smoke is None:
        smoke = SMOKE.read_text(encoding="utf-8")
    pinned_digest = _PARAMETER_DIGEST if digest is None else digest
    pinned_count = _EXPECTED_PARAMETER_COUNT if expected_count is None else expected_count
    pinned_ops = _EXPECTED_OPERATION_COUNT if expected_operations is None else expected_operations

    try:
        document = json.loads(snapshot)
        rows = _snapshot_parameters(document)
        snap = _snapshot_identity(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published parameters from snapshot: {exc}"]
    try:
        gen = _generated_identity(generated)
    except ValueError as exc:
        return [f"cannot read generated client parameters: {exc}"]

    # Door 1 -- independent fixed point. A coordinated edit of both halves
    # changes the row set, so the digest moves even when every consistency
    # check below still agrees.
    actual_digest = _digest(rows)
    if actual_digest != pinned_digest:
        found.append(
            f"published parameter surface drifted: _PARAMETER_DIGEST pins "
            f"{pinned_digest} but the snapshot derives {actual_digest}. A "
            "baseline is a fixed point for the artifacts, not a place to make "
            "a guard agree with itself -- regenerate the client and re-pin the "
            "digest in the same commit, with a reason."
        )
    if len(rows) != pinned_count:
        found.append(
            f"published parameter count is {len(rows)}, _EXPECTED_PARAMETER_COUNT "
            f"pins {pinned_count}: a parameter was added or dropped without "
            "moving the fixed point"
        )
    if len(snap) != pinned_ops:
        found.append(
            f"published operation count is {len(snap)}, _EXPECTED_OPERATION_COUNT "
            f"pins {pinned_ops}: an operation was added or dropped"
        )

    # Door 2 -- the two surfaces must name the same parameter identities. A
    # one-sided edit (snapshot only, or generated client only) is named.
    if set(snap) != set(gen):
        found.append(
            "generated operations interface keys do not match the published "
            f"operationIds (missing={sorted(set(snap) - set(gen))[:3]}, "
            f"phantom={sorted(set(gen) - set(snap))[:3]})"
        )
    for key in sorted(set(snap) & set(gen)):
        if snap[key] != gen[key]:
            found.append(
                f"{key}: generated parameters disagree with the snapshot "
                f"(snapshot_only={sorted(snap[key] - gen[key])[:3]}, "
                f"generated_only={sorted(gen[key] - snap[key])[:3]})"
            )

    # Door 3 -- shape invariants that make the published contract usable.
    for row in rows:
        _, path, oid, _, name, location, _, _ = row
        if location not in LOCATIONS:
            found.append(f"{oid} ({path}): parameter {name!r} has invalid in={location!r}")
    duplicates: dict[tuple[str, str, str], int] = {}
    for row in rows:
        _, _, oid, _, name, location, _, _ = row
        key = (oid, location, name)
        duplicates[key] = duplicates.get(key, 0) + 1
    dup_keys = sorted(key for key, count in duplicates.items() if count > 1)
    if dup_keys:
        found.append(f"duplicate (operation, in, name) parameters: {dup_keys[:5]}")

    if f"scripts/{SELF}" not in smoke:
        found.append(f"contracts smoke layer does not invoke {SELF}")
    return found


def self_test() -> int:
    """Every one-sided drift must be caught; the clean tree must pass."""
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    generated = GENERATED.read_text(encoding="utf-8")
    smoke = SMOKE.read_text(encoding="utf-8")
    clean = failures(snapshot=snapshot, generated=generated, smoke=smoke)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    document = json.loads(snapshot)
    target_path = "/api/v1/genes/region-structure"
    target_name = "release_id"
    new_name = "release_id_v2"

    def co_revert() -> tuple[str, str]:
        doc = copy.deepcopy(document)
        for parameter in doc["paths"][target_path]["get"]["parameters"]:
            if parameter.get("name") == target_name and parameter.get("in") == "query":
                parameter["name"] = new_name
                break
        key = "    get_region_structure_api_v1_genes_region_structure_get: {"
        start = generated.find(key)
        end = generated.find("\n    };", start)
        block = generated[start:end]
        assert f"{target_name}?: number | null;" in block
        changed = block.replace(
            f"{target_name}?: number | null;", f"{new_name}?: number | null;", 1
        )
        return json.dumps(doc, indent=2), generated[:start] + changed + generated[end:]

    co_snap, co_gen = co_revert()
    re_pinned_digest = _digest(_snapshot_parameters(json.loads(co_snap)))
    cases: list[tuple[str, dict[str, Any]]] = [
        # 1. The decisive co-revert: both halves agree, only the literal sees it.
        ("a coordinated parameter rename in both halves", dict(snapshot=co_snap, generated=co_gen)),
        # 1b. The same coordinated rename with the fixed point honestly
        #     re-pinned in the same commit: the only green coordinated shape.
        #     Both limbs in the case list, so a digest door weakened to
        #     self-agreement makes case 1 report instead of read as a pass.
        (
            "a coordinated parameter rename with its digest re-pinned",
            dict(
                snapshot=co_snap,
                generated=co_gen,
                digest=re_pinned_digest,
                expect_clean=True,
            ),
        ),
        # 2. Snapshot-only rename.
        ("a snapshot-only parameter rename", dict(snapshot=co_snap)),
        # 3. Generated-client-only rename.
        ("a generated-client-only parameter rename", dict(generated=co_gen)),
    ]
    # 4. Requiredness flipped in the snapshot alone.
    one = copy.deepcopy(document)
    for parameter in one["paths"][target_path]["get"]["parameters"]:
        if parameter.get("name") == target_name and parameter.get("in") == "query":
            parameter["required"] = True
            break
    cases.append(("a snapshot-only requiredness flip", dict(snapshot=json.dumps(one, indent=2))))
    # 5. A parameter dropped from both halves (same-count is not the only drift).
    dropped = copy.deepcopy(document)
    op = dropped["paths"][target_path]["get"]
    op["parameters"] = [p for p in op["parameters"] if p.get("name") != target_name]
    gen_dropped = generated.replace("                release_id?: number | null;\n", "", 1)
    cases.append(
        (
            "a coordinated parameter drop in both halves",
            dict(snapshot=json.dumps(dropped, indent=2), generated=gen_dropped),
        )
    )
    # 6/7. Hand-bumped literals (the baseline-sync escape hatch).
    cases.append(("a hand-bumped digest", dict(digest="0" * 64)))
    cases.append(("a hand-bumped parameter count", dict(expected_count=999)))
    # 8. An operation dropped from the snapshot.
    no_op = copy.deepcopy(document)
    del no_op["paths"]["/api/v1/health/live"]["get"]
    cases.append(
        ("an operation dropped from the snapshot", dict(snapshot=json.dumps(no_op, indent=2)))
    )
    # 9. Invalid location.
    bad_loc = copy.deepcopy(document)
    for parameter in bad_loc["paths"][target_path]["get"]["parameters"]:
        if parameter.get("name") == target_name and parameter.get("in") == "query":
            parameter["in"] = "body"
            break
    cases.append(
        (
            "a parameter published with an invalid location",
            dict(snapshot=json.dumps(bad_loc, indent=2)),
        )
    )
    # 10. A duplicate (in, name) on one operation.
    dup = copy.deepcopy(document)
    dup["paths"][target_path]["get"]["parameters"].append(
        {"name": target_name, "in": "query", "required": False, "schema": {"type": "integer"}}
    )
    cases.append(
        ("a duplicated (in, name) parameter", dict(snapshot=json.dumps(dup, indent=2)))
    )
    # 11. Wiring dropped.
    cases.append(
        ("the smoke.sh wiring dropped", dict(smoke=smoke.replace(f"scripts/{SELF}", "", 1)))
    )
    # 12. The operations interface removed entirely.
    cases.append(
        (
            "the operations interface removed",
            dict(
                generated=generated.replace(
                    "export interface operations {", "export interface renamed {", 1
                )
            ),
        )
    )

    results = 0
    failures_seen = 0
    base: dict[str, Any] = dict(snapshot=snapshot, generated=generated, smoke=smoke)
    for label, kwargs in cases:
        expect_clean = kwargs.pop("expect_clean", False)
        found = failures(**{**base, **kwargs})
        results += 1
        if expect_clean:
            if not found:
                print(f"PASS self-test: {label} -> stays green")
            else:
                failures_seen += 1
                print(f"FAIL self-test: {label} was rejected: {found}")
        elif found:
            print(f"PASS self-test: {label} -> {len(found)} failure(s)")
        else:
            failures_seen += 1
            print(f"FAIL self-test: {label} was NOT caught")

    print(f"self-test: {results} cases, {failures_seen} failure(s)")
    return 1 if failures_seen else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    found = failures()
    if found:
        for problem in found:
            print(f"openapi-operation-parameter-floor: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-operation-parameter-floor: OK "
        f"({_EXPECTED_PARAMETER_COUNT} published parameters pinned across "
        f"{_EXPECTED_OPERATION_COUNT} operations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pin the published operationId surface to an independent literal fixed point.

``openapi.json`` and ``src/generated/openapi.d.ts`` are both exports of
``app.main:app``. Every guard that compares them to each other proves
self-consistency, not truth. The 268 ``operationId`` values are client-visible:
they are the keys of the generated ``operations`` interface and the names of
the TypeScript types a consumer imports, and ``openapi-typescript`` derives
them from the operation's Python function name + route. Nothing in the
contracts layer read them.

Decisive ablation on live bytes: retype one ``operationId`` in *both* halves
together (snapshot's ``paths.*.*.operationId`` and the generated client's
``operations["..."]`` reference + interface key), re-pin the two provenance
blob ids in ``test_openapi_snapshot_body_integrity._PINNED_ARTIFACTS`` (the
"one deliberate reviewed action" that guard's own docstring admits), and every
wired OpenAPI guard stays ``rc=0`` and the contracts layer still prints
``SMOKE PASS``. A coordinated regenerate of a renamed handler is exactly this
shape: the published symbol moves, both artifacts agree with each other, and
no fixed point says the old symbol was ever published.

This guard reads committed bytes only (``json`` + ``re`` + stdlib): no Python
3.15, no API import, no wheel, no database, no workspace install. It pins:

* ``_OPERATION_ID_DIGEST`` -- a hand-written sha256 over the canonical sorted
  ``(METHOD path, operationId)`` pair set, read from nowhere. Exported from
  both artifacts independently, so a co-revert of both halves still changes it;
* ``_EXPECTED_OPERATION_COUNT`` -- the exact number of published operations
  (a second, count-level door that cannot be satisfied by a same-count
  permutation alone);
* three-way agreement: snapshot map == generated ``paths`` -> ``operations``
  reference map == generated ``operations`` interface key set. A one-sided
  edit (only the snapshot, or only one of the two generated surfaces) is named.

Uniqueness and identifier shape are checked too: two operations sharing one
``operationId`` collapse the generated client's type table, and a symbol that
is not a valid TypeScript property name breaks the emitted ``.d.ts``.

A legitimate rename must move the digest in the same commit as the two
artifacts and say why, exactly like ``_ERROR_RESPONSE_BASELINE`` /
``_SNAPSHOT_FLOOR`` / ``_BODY_PAIR_DIGEST``. Re-deriving the digest from the
artifacts under guard would make the pin self-referential, which is the whole
failure this file replaces. ``--self-test`` injects one-sided drifts into
copies of the bytes and asserts each is caught; the clean tree must pass.

Usage:
    python3 scripts/check_openapi_operation_id_floor.py
    python3 scripts/check_openapi_operation_id_floor.py --self-test
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

# A reviewed, hand-written lower bound on the published operationId surface.
# sha256 of "\n".join(["soymutdb-operation-ids/v1"] + sorted(f"{key} {oid}")).
# Regenerate with _digest() after an intentional contract change and update in
# the same commit, with a reason.
_OPERATION_ID_DIGEST = "1f55857d26bba0210cdb9d0b8dc73b8a5d42f33ddac8d55cba3a68681d491673"
_EXPECTED_OPERATION_COUNT = 268

PATH_LINE = re.compile(r'^    "(/[^"]*)": \{$')
OP_REF = re.compile(
    r'^        (get|put|post|patch|delete|options|head|trace): '
    r'operations\["([^"]+)"\];$'
)
INTERFACE_KEY = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_]*): \{$", re.MULTILINE)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _snapshot_map(document: dict[str, Any]) -> dict[str, str]:
    """(METHOD path) -> operationId, from the committed snapshot."""
    out: dict[str, str] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            oid = operation.get("operationId")
            if not isinstance(oid, str):
                raise ValueError(f"{method.upper()} {path} has no string operationId")
            out[f"{method.upper()} {path}"] = oid
    return out


def _generated_path_map(generated: str) -> dict[str, str]:
    """(METHOD path) -> operations[\"...\"] symbol, from the paths interface."""
    out: dict[str, str] = {}
    in_paths = False
    path: str | None = None
    for line in generated.splitlines():
        if line.startswith("export interface paths {"):
            in_paths = True
            continue
        if in_paths and line.startswith("export "):
            break
        if not in_paths:
            continue
        match = PATH_LINE.match(line)
        if match:
            path = match.group(1)
            continue
        match = OP_REF.match(line)
        if match and path is not None:
            out[f"{match.group(1).upper()} {path}"] = match.group(2)
    return out


def _interface_keys(generated: str) -> set[str]:
    """The declared keys of the generated ``operations`` interface."""
    marker = "export interface operations {"
    if marker not in generated:
        raise ValueError("generated client declares no operations interface")
    return set(INTERFACE_KEY.findall(generated.split(marker, 1)[1]))


def _digest(operation_ids: dict[str, str]) -> str:
    blob = "\n".join(
        ["soymutdb-operation-ids/v1"]
        + [f"{key} {operation_ids[key]}" for key in sorted(operation_ids)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    smoke: str | None = None,
    digest: str | None = None,
    expected_count: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = GENERATED.read_text(encoding="utf-8")
    if smoke is None:
        smoke = SMOKE.read_text(encoding="utf-8")
    pinned_digest = _OPERATION_ID_DIGEST if digest is None else digest
    pinned_count = _EXPECTED_OPERATION_COUNT if expected_count is None else expected_count

    try:
        document = json.loads(snapshot)
        snap = _snapshot_map(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published operationIds from snapshot: {exc}"]
    try:
        path_map = _generated_path_map(generated)
        keys = _interface_keys(generated)
    except ValueError as exc:
        return [f"cannot read generated client operations: {exc}"]

    # Door 1 -- independent fixed point. A coordinated edit of both halves
    # changes the pair set, so the digest moves even when every consistency
    # check below still agrees.
    actual_digest = _digest(snap)
    if actual_digest != pinned_digest:
        found.append(
            f"published operationId surface drifted: _OPERATION_ID_DIGEST pins "
            f"{pinned_digest} but the snapshot derives {actual_digest}. A "
            "baseline is a fixed point for the artifacts, not a place to make "
            "a guard agree with itself -- regenerate the client and re-pin the "
            "digest in the same commit, with a reason."
        )
    if len(snap) != pinned_count:
        found.append(
            f"published operation count is {len(snap)}, _EXPECTED_OPERATION_COUNT "
            f"pins {pinned_count}: an operation was added or dropped without "
            "moving the fixed point"
        )

    # Door 2 -- the three surfaces must name the same symbols. A one-sided
    # edit (snapshot only, or one of the two generated surfaces only) is named.
    if snap != path_map:
        missing = sorted(set(snap) - set(path_map))
        extra = sorted(set(path_map) - set(snap))
        retyped = sorted(
            key for key in set(snap) & set(path_map) if snap[key] != path_map[key]
        )
        found.append(
            "generated paths interface does not reference the snapshot's "
            f"operationIds (missing={missing[:3]}, extra={extra[:3]}, "
            f"retyped={retyped[:3]})"
        )
    if set(snap.values()) != keys:
        found.append(
            "generated operations interface keys do not match the published "
            f"operationIds (missing={sorted(set(snap.values()) - keys)[:3]}, "
            f"phantom={sorted(keys - set(snap.values()))[:3]})"
        )

    # Door 3 -- shape invariants that make the generated TypeScript usable.
    values = list(snap.values())
    duplicates = sorted({oid for oid in values if values.count(oid) > 1})
    if duplicates:
        found.append(f"operationIds are not unique: {duplicates[:5]}")
    malformed = sorted({oid for oid in values if not IDENTIFIER.fullmatch(oid)})
    if malformed:
        found.append(
            f"operationIds are not valid TypeScript property names: {malformed[:5]}"
        )

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
    cases: list[tuple[str, dict[str, Any]]] = []
    old = "liveness_api_v1_health_live_get"

    # 1. The decisive co-revert: retype in BOTH halves. The digest is the only
    #    thing that can see it, because all three surfaces still agree.
    def co_revert() -> tuple[str, str]:
        doc = copy.deepcopy(document)
        for item in doc["paths"].values():
            for method, operation in item.items():
                if method in METHODS and isinstance(operation, dict):
                    if operation.get("operationId") == old:
                        operation["operationId"] = old + "_v2"
        gen = generated.replace(
            f'operations["{old}"]', f'operations["{old}_v2"]'
        ).replace(f"    {old}: {{", f"    {old}_v2: {{")
        return json.dumps(doc, indent=2), gen

    co_snap, co_gen = co_revert()
    cases.append(
        (
            "a coordinated operationId retype in both halves",
            dict(snapshot=co_snap, generated=co_gen),
        )
    )
    # 1b. The same co-revert with the fixed point honestly re-pinned in the
    #     same commit. Both halves agree and the digest moves with them, so
    #     this is the *only* green shape among the coordinated drifts. Keeping
    #     both limbs in the case list makes them load-bearing: if the digest
    #     door is weakened to self-agreement, case 1 stops failing and the
    #     self-test reports it instead of silently passing a green tree.
    re_pinned_digest = _digest(_snapshot_map(json.loads(co_snap)))
    cases.append(
        (
            "a coordinated operationId retype with its digest re-pinned",
            dict(
                snapshot=co_snap,
                generated=co_gen,
                digest=re_pinned_digest,
                expect_clean=True,
            ),
        )
    )
    # 2. Snapshot-only retype (one-half drift).
    one = copy.deepcopy(document)
    for item in one["paths"].values():
        for method, operation in item.items():
            if method in METHODS and isinstance(operation, dict):
                if operation.get("operationId") == old:
                    operation["operationId"] = old + "_v2"
    cases.append(
        ("a snapshot-only operationId retype", dict(snapshot=json.dumps(one, indent=2)))
    )
    # 3. Generated-client-only retype of the paths reference.
    cases.append(
        (
            "a generated paths reference retyped alone",
            dict(generated=generated.replace(f'operations["{old}"]', f'operations["{old}_v2"]')),
        )
    )
    # 4. Interface key dropped while the reference stays.
    cases.append(
        (
            "an operations interface key dropped",
            dict(generated=generated.replace(f"    {old}: {{", "    dropped_symbol: {")),
        )
    )
    # 5. An operation dropped from the snapshot.
    dropped = copy.deepcopy(document)
    del dropped["paths"]["/api/v1/health/live"]["get"]
    cases.append(
        (
            "an operation dropped from the snapshot",
            dict(snapshot=json.dumps(dropped, indent=2)),
        )
    )
    # 6. A bumped literal (the baseline-sync escape hatch).
    cases.append(("a hand-bumped digest", dict(digest="0" * 64)))
    # 7. A hand-bumped count.
    cases.append(("a hand-bumped operation count", dict(expected_count=999)))
    # 8. A duplicated operationId (two operations, one symbol).
    dup = copy.deepcopy(document)
    second = next(
        op
        for path, item in dup["paths"].items()
        for method, op in item.items()
        if method in METHODS and isinstance(op, dict) and op.get("operationId") != old
    )
    second["operationId"] = old
    cases.append(
        ("two operations sharing one operationId", dict(snapshot=json.dumps(dup, indent=2)))
    )
    # 9. Wiring dropped.
    cases.append(
        ("the smoke.sh wiring dropped", dict(smoke=smoke.replace(f"scripts/{SELF}", "", 1)))
    )
    # 10. An interface with no operations block at all.
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
            print(f"openapi-operation-id-floor: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-operation-id-floor: OK "
        f"({_EXPECTED_OPERATION_COUNT} published operationIds pinned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
* ``_PATH_ORDER_DIGEST`` / ``_CLIENT_PATH_ORDER_DIGEST`` -- two hand-written
  sha256 literals over the ``index|path`` rows IN DOCUMENT ORDER, one per
  artifact. Every other fixed point here is sorted, so a coordinated swap of
  two whole path blocks (same pair set, same counts, same bytes, provenance
  blobs honestly re-pinned) moves none of them; ``openapi-typescript`` prints
  paths in document order, so the emitted interface sequence is itself a
  client-visible shape. ``_EXPECTED_PATH_COUNT`` is the exact count door;
* ``_METHOD_SEQUENCE_DIGEST`` -- a hand-written sha256 over canonical sorted
  ``(path, index, METHOD)`` rows of the snapshot's HTTP methods **in document
  order**. The operationId digest above is a sorted pair *set*: swapping two
  adjacent methods under one path keeps every ``(METHOD path, operationId)``
  pair intact, so the digest, the count and all three agreement doors stay
  green. ``openapi-typescript`` prints the ``paths`` interface's methods in a
  fixed order regardless of the snapshot, so no two-artifact comparison can
  see this -- the snapshot's own method order is the only published record of
  FastAPI's router-registration order, and it is what OpenAPI tooling displays.
  ``_EXPECTED_METHOD_ROWS`` is its exact count door;
* three-way agreement: snapshot map == generated ``paths`` -> ``operations``
  reference map == generated ``operations`` interface key set, plus a named
  per-index path-order agreement. A one-sided edit (only the snapshot, or
  only one of the two generated surfaces) is named.

Uniqueness and identifier shape are checked too: two operations sharing one
``operationId`` collapse the generated client's type table, and a symbol that
is not a valid TypeScript property name breaks the emitted ``.d.ts``.

A legitimate rename must move the digest in the same commit as the two
artifacts and say why, exactly like ``_ERROR_RESPONSE_BASELINE`` /
``_SNAPSHOT_FLOOR`` / ``_BODY_PAIR_DIGEST``. Re-deriving any digest from the
artifacts under guard would make the pin self-referential, which is the whole
failure this file replaces. ``--self-test`` injects one-sided drifts and a
coordinated same-count path-block swap into copies of the bytes and asserts
each is caught, with both order literals honestly re-pinned in the one green
shape; the clean tree must pass.

Usage:
    python3 scripts/check_openapi_operation_id_floor.py
    python3 scripts/check_openapi_operation_id_floor.py --self-test
"""

from __future__ import annotations

import argparse
import copy
from collections import OrderedDict
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

# Independent fixed points on the published PATH DECLARATION ORDER. The
# operationId digest above walks a *sorted* (METHOD path, operationId) pair
# set, and every other landed digest on this family is sorted too. A
# permutation that swaps two whole path blocks in both artifacts preserves
# the pair set, the path count, every body/response/parameter/enum/title row
# and the export normalizer's byte fixed point; openapi-typescript prints
# ``paths`` in the snapshot's own document order, so the emitted interface's
# sequence is itself a client-visible shape (IDE completion order, object key
# enumeration). The only landed order reader
# (``test_openapi_snapshot_contract.py``) compares the two halves to each
# other, which a coordinated co-revert satisfies.
#
# Two hand-written sha256 literals, read from nowhere, over the canonical
# ``index|path`` rows IN DOCUMENT ORDER -- the snapshot's ``paths`` keys and
# the generated ``export interface paths`` keys separately. A sorted multiset
# would be blind to a same-count rotation; re-pinning only one side cannot
# silence the other. Regenerate with _path_order_digest() after an
# intentional, reviewed reorder and update in the same commit as both
# artifacts, with a reason.
_PATH_ORDER_DIGEST = "086901ee36ea25318728b5486aa311968568e7633e255b72fa4701fe68a1bcd2"
_CLIENT_PATH_ORDER_DIGEST = "baabc2c7606dafb7dbbf10b54292007ceaefe105c072c394460ec524f014a7e7"
_EXPECTED_PATH_COUNT = 238
# Reviewed, hand-written fixed point on the snapshot's HTTP method sequence.
# sha256 of "\n".join(["soymutdb-published-method-sequence/v1"] +
#   sorted(f"{path}|{index}|{METHOD}")) over every method of every path, where
# `index` is the method's position in that path's insertion order. A sorted
# set of (METHOD path) pairs cannot see that "post" and "get" traded places,
# but the positional row changes for both. openapi-typescript emits a fixed
# method order in openapi.d.ts, so there is no generated half to compare
# against -- this literal is the only anchor. Read from nowhere; re-pin in the
# same commit as the snapshot after an intentional, reviewed reorder.
_METHOD_SEQUENCE_DIGEST = (
    "1a3af1165bdd777bead8a38837d1b075b1aee45bd162e77c612daa2b2f5b888b"
)
_EXPECTED_METHOD_ROWS = 268

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


def _snapshot_paths(document: dict[str, Any]) -> list[str]:
    """The snapshot's ``paths`` keys in DOCUMENT ORDER."""
    return [path for path in document.get("paths", {})]


def _paths_interface(generated: str) -> str:
    """The body of the generated ``export interface paths`` block."""
    marker = "export interface paths {"
    if marker not in generated:
        raise ValueError("generated client declares no paths interface")
    body = generated.split(marker, 1)[1]
    # Only a top-level declaration ends the block; docstring prose such as
    # "export job (vcf/...)" must not truncate it.
    end = re.search(r"^export (?:type|interface) ", body, re.M)
    return body[: end.start()] if end else body


def _generated_paths(generated: str) -> list[str]:
    """The generated ``paths`` interface keys in DOCUMENT ORDER."""
    return re.findall(r'^    "(/[^"]*)": \{$', _paths_interface(generated), re.M)


def _path_order_digest(paths: list[str], tag: str) -> str:
    """sha256 over ``index|path`` rows, in order -- not a sorted multiset."""
    blob = "\n".join([tag, *(f"{index}|{path}" for index, path in enumerate(paths))])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _digest(operation_ids: dict[str, str]) -> str:
    blob = "\n".join(
        ["soymutdb-operation-ids/v1"]
        + [f"{key} {operation_ids[key]}" for key in sorted(operation_ids)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def method_sequence_rows(document: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Canonical (path, index, METHOD) rows of the snapshot's method order."""
    out: list[tuple[str, str, str]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for index, method in enumerate(k for k in item if k in METHODS):
            out.append((path, str(index), method.upper()))
    return out


def _method_sequence_digest(rows: list[tuple[str, str, str]]) -> str:
    canonical = sorted(f"{p}|{i}|{m}" for p, i, m in rows)
    blob = "\n".join(["soymutdb-published-method-sequence/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    smoke: str | None = None,
    digest: str | None = None,
    expected_count: int | None = None,
    path_order_digest: str | None = None,
    client_path_order_digest: str | None = None,
    expected_path_count: int | None = None,
    method_sequence_digest: str | None = None,
    expected_method_rows: int | None = None,
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
    pinned_order = _PATH_ORDER_DIGEST if path_order_digest is None else path_order_digest
    pinned_client_order = (
        _CLIENT_PATH_ORDER_DIGEST
        if client_path_order_digest is None
        else client_path_order_digest
    )
    pinned_paths = _EXPECTED_PATH_COUNT if expected_path_count is None else expected_path_count
    pinned_method_digest = (
        _METHOD_SEQUENCE_DIGEST
        if method_sequence_digest is None
        else method_sequence_digest
    )
    pinned_method_rows = (
        _EXPECTED_METHOD_ROWS if expected_method_rows is None else expected_method_rows
    )

    try:
        document = json.loads(snapshot)
        snap = _snapshot_map(document)
        snap_paths = _snapshot_paths(document)
        method_rows = method_sequence_rows(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published operationIds from snapshot: {exc}"]
    try:
        path_map = _generated_path_map(generated)
        keys = _interface_keys(generated)
        gen_paths = _generated_paths(generated)
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

    # Door 1b -- the path declaration ORDER, in both halves independently.
    # Every other fixed point on this surface is sorted, so a coordinated
    # swap of two whole path blocks (same pair set, same counts, same bytes,
    # provenance blobs honestly re-pinned) moves none of them. Two separate
    # literals: re-pinning only the snapshot side cannot silence the client
    # door, and a co-revert that makes both halves agree still moves both.
    actual_order = _path_order_digest(snap_paths, "soymutdb-snapshot-path-order/v1")
    if actual_order != pinned_order:
        found.append(
            f"published snapshot path order drifted: _PATH_ORDER_DIGEST pins "
            f"{pinned_order} but the snapshot derives {actual_order}. Path "
            "order is a client-visible shape the generator reproduces in "
            "document order -- re-pin both literals in the same commit as "
            "both artifacts, with a reason."
        )
    actual_client_order = _path_order_digest(gen_paths, "soymutdb-client-path-order/v1")
    if actual_client_order != pinned_client_order:
        found.append(
            f"generated client path order drifted: _CLIENT_PATH_ORDER_DIGEST "
            f"pins {pinned_client_order} but the generated client derives "
            f"{actual_client_order}. A one-sided reorder or a coordinated "
            "co-revert of both halves must not ship silently."
        )
    if len(snap_paths) != pinned_paths:
        found.append(
            f"published path count is {len(snap_paths)}, _EXPECTED_PATH_COUNT "
            f"pins {pinned_paths}: a path was added or dropped without moving "
            "the order fixed points"
        )
    if len(gen_paths) != len(snap_paths):
        found.append(
            f"generated client declares {len(gen_paths)} paths, the snapshot "
            f"declares {len(snap_paths)}: the two halves no longer agree"
        )
    if snap_paths != gen_paths:
        first = next(
            (
                index
                for index, (a, b) in enumerate(zip(snap_paths, gen_paths))
                if a != b
            ),
            min(len(snap_paths), len(gen_paths)),
        )
        found.append(
            f"generated paths interface order disagrees with the snapshot at "
            f"index {first}: snapshot has {snap_paths[first:first + 1]}, "
            f"client has {gen_paths[first:first + 1]}. openapi-typescript "
            "prints paths in document order, so both halves must move together."
        )

    # Door 1c -- the snapshot's own HTTP method order. Every other literal in
    # this guard is a sorted set of (METHOD path) pairs, so two adjacent
    # methods trading places under one path moves none of them; the generated
    # client prints its methods in a fixed order and cannot expose the swap.
    # The positional row is the only published record of that order.
    actual_method_digest = _method_sequence_digest(method_rows)
    if actual_method_digest != pinned_method_digest:
        found.append(
            "published HTTP method sequence drifted: _METHOD_SEQUENCE_DIGEST "
            f"pins {pinned_method_digest} but the snapshot derives "
            f"{actual_method_digest}. Methods were reordered under a path; "
            "re-pin the literal in the same commit as the snapshot, with a "
            "reason."
        )
    if len(method_rows) != pinned_method_rows:
        found.append(
            f"published HTTP method row count is {len(method_rows)}, "
            f"_EXPECTED_METHOD_ROWS pins {pinned_method_rows}: a method was "
            "added or dropped without moving the fixed point"
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
    # 11. The decisive ORDER drift: swap the first two whole path blocks in
    #     BOTH halves. Every other fixed point here is sorted, so the pair
    #     set, the operation count, the path count and the two-artifact
    #     agreement all stay identical; only the two sequence literals move.
    def swap_first_two_paths(text: str) -> str:
        starts = list(re.finditer(r'^    "(/[^"]+)": \{$', text, re.M))
        a, b, c = starts[0].start(), starts[1].start(), starts[2].start()
        return text[:a] + text[b:c] + text[a:b] + text[c:]

    swapped_snapshot = swap_first_two_paths(snapshot)
    swapped_generated = swap_first_two_paths(generated)
    cases.append(
        (
            "a coordinated path-block swap in both halves",
            dict(snapshot=swapped_snapshot, generated=swapped_generated),
        )
    )
    # 11b. The same co-revert with BOTH order literals honestly re-pinned in
    #      the same commit stays green -- the reviewed action, not a whitelist.
    swapped_doc = json.loads(swapped_snapshot)
    cases.append(
        (
            "a coordinated path-block swap with both order digests re-pinned",
            dict(
                snapshot=swapped_snapshot,
                generated=swapped_generated,
                path_order_digest=_path_order_digest(
                    _snapshot_paths(swapped_doc), "soymutdb-snapshot-path-order/v1"
                ),
                client_path_order_digest=_path_order_digest(
                    _generated_paths(swapped_generated), "soymutdb-client-path-order/v1"
                ),
                expect_clean=True,
            ),
        )
    )
    # 11c. Re-pinning only ONE side cannot silence the other.
    cases.append(
        (
            "a path-block swap with only the snapshot order digest re-pinned",
            dict(
                snapshot=swapped_snapshot,
                generated=swapped_generated,
                path_order_digest=_path_order_digest(
                    _snapshot_paths(swapped_doc), "soymutdb-snapshot-path-order/v1"
                ),
            ),
        )
    )
    # 12. A one-sided reorder (snapshot only) is named by the order door.
    cases.append(
        ("a snapshot-only path-block swap", dict(snapshot=swapped_snapshot)),
    )
    # 13. A one-sided reorder (generated only) is named by the order door.
    cases.append(
        ("a generated-only path-block swap", dict(generated=swapped_generated)),
    )
    # 14. A hand-bumped path count.
    cases.append(("a hand-bumped path count", dict(expected_path_count=999)))
    # 15. A hand-bumped order digest (the baseline-sync escape hatch).
    cases.append(("a hand-bumped path order digest", dict(path_order_digest="0" * 64)))
    # 18. Two adjacent methods trading places under one path. Every other
    #     door in this guard is a sorted (METHOD path) pair set, so without
    #     the positional literal this is the decisive silent drift.
    swapped = json.loads(snapshot, object_pairs_hook=OrderedDict)
    victim = next(
        path
        for path, item in swapped["paths"].items()
        if sum(1 for k in item if k in METHODS) >= 2
    )
    order = [k for k in swapped["paths"][victim] if k in METHODS]
    first, second = order[0], order[1]
    rebuilt: "OrderedDict[str, Any]" = OrderedDict()
    for key, value in swapped["paths"][victim].items():
        if key == first:
            rebuilt[second] = swapped["paths"][victim][second]
        elif key == second:
            rebuilt[first] = swapped["paths"][victim][first]
        else:
            rebuilt[key] = value
    swapped["paths"][victim] = rebuilt
    swap_snap = json.dumps(swapped, indent=2)
    cases.append(
        (
            "two adjacent HTTP methods swapped under one path",
            dict(snapshot=swap_snap),
        )
    )
    # 18b. The same swap with the positional literal honestly re-pinned in the
    #      same commit. Both limbs keep the door load-bearing: weaken it to
    #      self-agreement and case 11 stops failing, which the harness reports.
    cases.append(
        (
            "a method swap with its sequence digest re-pinned",
            dict(
                snapshot=swap_snap,
                method_sequence_digest=_method_sequence_digest(
                    method_sequence_rows(json.loads(swap_snap))
                ),
                expect_clean=True,
            ),
        )
    )
    # 19. A hand-bumped method row count.
    cases.append(
        ("a hand-bumped method row count", dict(expected_method_rows=999))
    )
    # 20. A hand-bumped positional literal.
    cases.append(("a hand-bumped method sequence digest", dict(method_sequence_digest="0" * 64)))

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
        f"({_EXPECTED_OPERATION_COUNT} published operationIds and "
        f"{_EXPECTED_PATH_COUNT} path order rows pinned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

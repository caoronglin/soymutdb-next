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

# Reviewed, hand-written fixed point on the published parameter descriptions.
# 20 operations publish a `description` on a parameter; openapi-typescript
# renders each as an `@description` line in the generated
# `operations[*].parameters` doc block -- prose an IDE shows a caller. The
# parameter digest above walks (method, path, name, in, required, schema) but
# deliberately not the description, so a coordinated co-revert of the prose in
# both halves (with the provenance blob ids honestly re-pinned) moves no landed
# fixed point. Kept as its own literal for the same reason as the required /
# tuple / title doors: a retyped description is not a renamed parameter.
_PARAMETER_DESCRIPTION_DIGEST = (
    "6a3110df52a5eaf109b72adab22be80d3a2ffd6a7c7f869599307d595e26c74d"
)
_EXPECTED_PARAMETER_DESCRIPTIONS = 20

# The generated half is pinned by a *separate* literal, not derived from the
# snapshot under guard. Two independent fixed points: a coordinated co-revert
# cannot pass by making both halves agree, and re-pinning only the snapshot
# digest does not silence the client door.
_CLIENT_PARAMETER_DESCRIPTION_DIGEST = (
    "992c0031115675a58c3a04c4dfc4b137a818e37d97285bc9465b66c252769d8e"
)
_EXPECTED_CLIENT_PARAMETER_DESCRIPTIONS = 20

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


GEN_PARAM_DESCRIPTION = re.compile(
    r"/\*\* @description (.+?) \*/\n\s+(?P<field>[\w\"-]+)\??:"
)


def _parameter_description_rows(
    document: dict[str, Any],
) -> list[tuple[str, ...]]:
    """Canonical (METHOD, path, operationId, index, name, in, description)."""
    rows: list[tuple[str, ...]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            oid = operation.get("operationId")
            for index, parameter in enumerate(operation.get("parameters", []) or []):
                if not isinstance(parameter, dict):
                    continue
                description = parameter.get("description")
                if not isinstance(description, str):
                    continue
                rows.append(
                    (
                        method.upper(),
                        path,
                        str(oid),
                        str(index),
                        str(parameter.get("name", "")),
                        str(parameter.get("in", "")),
                        description,
                    )
                )
    return rows


def _parameter_description_digest(rows: list[tuple[str, ...]]) -> str:
    canonical = sorted("|".join(row) for row in rows)
    blob = "\n".join(["soymutdb-parameter-descriptions/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _client_parameter_descriptions(generated: str) -> dict[tuple[str, str], str]:
    """(operationId, field) -> first @description line, parameters blocks only.

    Each operation's ``parameters: {`` section is read up to ``responses: {``,
    so the many ``@description`` lines on response/body doc blocks cannot be
    mistaken for a parameter description.
    """
    out: dict[tuple[str, str], str] = {}
    for match in GEN_OP_KEY.finditer(generated):
        oid = match.group(1)
        start = match.start()
        end = generated.find("\n    };\n", start)
        segment = generated[start : end if end > 0 else start + 20000]
        parameters = segment.find("        parameters: {")
        if parameters < 0:
            continue
        responses = segment.find("        responses: {", parameters)
        block = segment[parameters : responses if responses > 0 else len(segment)]
        for prop in GEN_PARAM_DESCRIPTION.finditer(block):
            out[(oid, prop.group("field"))] = prop.group(1)
    return out


def _client_parameter_description_digest(
    rows: dict[tuple[str, str], str],
) -> str:
    canonical = sorted(f"{oid}|{field}|{value}" for (oid, field), value in rows.items())
    blob = "\n".join(
        ["soymutdb-client-parameter-descriptions/v1", *canonical]
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
    description_digest: str | None = None,
    expected_descriptions: int | None = None,
    client_description_digest: str | None = None,
    expected_client_descriptions: int | None = None,
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
    pinned_description_digest = (
        _PARAMETER_DESCRIPTION_DIGEST
        if description_digest is None
        else description_digest
    )
    pinned_descriptions = (
        _EXPECTED_PARAMETER_DESCRIPTIONS
        if expected_descriptions is None
        else expected_descriptions
    )
    pinned_client_description_digest = (
        _CLIENT_PARAMETER_DESCRIPTION_DIGEST
        if client_description_digest is None
        else client_description_digest
    )
    pinned_client_descriptions = (
        _EXPECTED_CLIENT_PARAMETER_DESCRIPTIONS
        if expected_client_descriptions is None
        else expected_client_descriptions
    )

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

    # Door 4 -- independent fixed point on the published parameter
    # descriptions. A coordinated co-revert of one parameter's prose in both
    # halves, with the provenance blob ids honestly re-pinned, moves this
    # digest even though every two-artifact comparison above agrees.
    description_rows = _parameter_description_rows(document)
    actual_description = _parameter_description_digest(description_rows)
    if actual_description != pinned_description_digest:
        found.append(
            "published parameter descriptions drifted: "
            f"_PARAMETER_DESCRIPTION_DIGEST pins {pinned_description_digest} "
            f"but the snapshot derives {actual_description}. Re-pin the digest "
            "in the same commit as both artifacts, with a reason."
        )
    if len(description_rows) != pinned_descriptions:
        found.append(
            f"published parameter description row count is {len(description_rows)}, "
            f"_EXPECTED_PARAMETER_DESCRIPTIONS pins {pinned_descriptions}"
        )

    # Door 5 -- the generated half, pinned by its *own* independent literal.
    # Re-pinning only the snapshot digest does not silence this door, and a
    # coordinated co-revert cannot pass by making both halves agree.
    try:
        client_descriptions = _client_parameter_descriptions(generated)
    except ValueError as exc:
        found.append(f"cannot read generated parameter descriptions: {exc}")
        return found
    actual_client_description = _client_parameter_description_digest(
        client_descriptions
    )
    if actual_client_description != pinned_client_description_digest:
        found.append(
            "generated parameter descriptions drifted: "
            f"_CLIENT_PARAMETER_DESCRIPTION_DIGEST pins "
            f"{pinned_client_description_digest} but the client derives "
            f"{actual_client_description}. Re-pin the digest in the same "
            "commit as both artifacts, with a reason."
        )
    if len(client_descriptions) != pinned_client_descriptions:
        found.append(
            "generated parameter description row count is "
            f"{len(client_descriptions)}, "
            f"_EXPECTED_CLIENT_PARAMETER_DESCRIPTIONS pins "
            f"{pinned_client_descriptions}"
        )

    # One-sided edits are named by operation and field.
    snapshot_first_lines = {
        (oid, name): description.splitlines()[0]
        for _, _, oid, _, name, _, description in description_rows
    }
    for key, expected in sorted(snapshot_first_lines.items()):
        observed = client_descriptions.get(key)
        if observed is None:
            found.append(
                f"generated client no longer renders the published description "
                f"of {key[0]}.{key[1]}"
            )
        elif observed != expected:
            found.append(
                f"generated client renders {key[0]}.{key[1]} description as "
                f"{observed!r}, the snapshot publishes {expected!r}"
            )
    for key in sorted(client_descriptions):
        if key not in snapshot_first_lines:
            found.append(
                f"generated client renders a description at {key[0]}.{key[1]} "
                "the snapshot does not publish"
            )
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

    # --- the published parameter description surface (Doors 4 and 5). ----
    target_oid = "get_region_structure_api_v1_genes_region_structure_get"
    target_field = "include_parts"
    original = (
        "Include CDS/UTR segments. False returns gene bodies only."
    )
    drifted = original + " (planted drift)"

    def description_co_revert() -> tuple[str, str]:
        doc = copy.deepcopy(document)
        for parameter in doc["paths"][target_path]["get"]["parameters"]:
            if parameter.get("name") == target_field:
                assert parameter["description"] == original
                parameter["description"] = drifted
                break
        snap = json.dumps(doc, indent=2)
        gen = generated.replace(
            f"/** @description {original} */",
            f"/** @description {drifted} */",
            1,
        )
        assert gen != generated
        return snap, gen

    co_snap, co_gen = description_co_revert()
    cases.append(
        (
            "a coordinated parameter description co-revert in both halves",
            dict(snapshot=co_snap, generated=co_gen),
        )
    )
    cases.append(
        (
            "a one-sided snapshot parameter description retype",
            dict(snapshot=co_snap),
        )
    )
    cases.append(
        (
            "a one-sided client parameter description retype",
            dict(generated=co_gen),
        )
    )
    # Re-pinning only the snapshot digest must not silence the client door.
    repinned = _parameter_description_digest(
        _parameter_description_rows(json.loads(co_snap))
    )
    cases.append(
        (
            "a description digest re-pin without the client digest",
            dict(
                snapshot=co_snap,
                generated=co_gen,
                description_digest=repinned,
            ),
        )
    )
    # A same-count rotation of two descriptions leaves every count door green.
    rotated = copy.deepcopy(document)
    described = [
        (op, parameter)
        for path, item in rotated["paths"].items()
        for method, op in item.items()
        if method in METHODS and isinstance(op, dict)
        for parameter in (op.get("parameters", []) or [])
        if isinstance(parameter.get("description"), str)
    ]
    assert len(described) >= 2
    first_value = described[0][1]["description"]
    second_value = described[1][1]["description"]
    assert first_value != second_value
    described[0][1]["description"], described[1][1]["description"] = (
        second_value,
        first_value,
    )
    cases.append(
        (
            "a same-count parameter description rotation",
            dict(snapshot=json.dumps(rotated, indent=2)),
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

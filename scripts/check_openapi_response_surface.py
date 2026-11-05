#!/usr/bin/env python3
"""Pin the published response surface to an independent literal fixed point.

``openapi.json`` and ``src/generated/openapi.d.ts`` are both exports of
``app.main:app``. Guards that compare them to each other prove
self-consistency, not truth. Every published operation declares a set of
response codes, and the generated client types exactly that set as the keys of
``operations[...].responses``. A coordinated regenerate that renames one
success status (or drops/adds one) on *both* halves moves both artifacts
together, so none of the existing fixed points can see it:

* ``_BODY_PAIR_DIGEST`` / ``_RESPONSE_BODY_BASELINE`` / ``_REQUEST_BODY_BASELINE``
  only see responses that carry a ``$ref`` body. All 12 declared ``204``
  responses are content-less, so they appear in **zero** body pairs.
* ``_ERROR_RESPONSE_BASELINE`` only pins 4xx/5xx codes; success codes are
  outside it.
* ``_SNAPSHOT_FLOOR`` is a (paths, schemas) floor, not a per-operation pin.
* ``_PINNED_ARTIFACTS`` is a provenance blob id: re-pinning both ids is the
  guard's own documented "one deliberate reviewed action" alongside a
  regenerate, so a co-revert that re-pins them stays green.

Decisive ablation on live bytes: rename one ``204`` to ``205`` in the
snapshot and in the generated ``operations`` interface (byte-preserving, both
halves agree), re-pin the two blob ids as that guard instructs, and every
wired OpenAPI guard stays ``rc=0``. The generated TypeScript type for that
operation silently changes from ``responses.204`` to ``responses.205`` -- a
client-visible contract break that nothing in the layer pins.

This guard reads committed bytes only (``json`` + ``re`` + stdlib): no Python
3.15, no API import, no wheel, no database, no workspace install. It pins:

* ``_RESPONSE_SURFACE_DIGEST`` -- a hand-written sha256 over the canonical
  sorted ``(METHOD, path, status, description, has_content)`` tuple set,
  read from nowhere. Exported from both artifacts independently, so a
  co-revert of both halves still changes it;
* ``_EXPECTED_RESPONSE_ENTRIES`` / ``_EXPECTED_OPERATION_COUNT`` -- exact
  count doors that a same-count permutation cannot satisfy alone;
* three-way agreement: snapshot per-operation response set == generated
  ``paths`` -> ``operations`` reference map == generated ``operations``
  interface response keys. A one-sided edit is named;
* content-less responses must agree on the ``content?: never`` shape in the
  generated client, and content-bearing ones on the ``content: {`` marker.

A legitimate contract change must move the digest in the same commit as the
two artifacts and say why, exactly like ``_ERROR_RESPONSE_BASELINE`` /
``_BODY_PAIR_DIGEST``. Re-deriving the digest from the artifacts under guard
would make the pin self-referential, which is the whole failure this file
replaces. ``--self-test`` injects one-sided and coordinated drifts into copies
of the bytes and asserts each is caught; the clean tree must pass.

The operation-level ``summary`` is the same genus one step earlier in the
document: ``openapi-typescript`` prints it as the first ``* text`` line of the
JSDoc block in the ``paths`` interface, so it is client-visible prose. No
landed guard reads it. ``_RESPONSE_SURFACE_DIGEST`` only walks ``responses``;
``_PINNED_ARTIFACTS`` is a provenance blob id that a regenerate re-pins in the
same deliberate act. A coordinated retype of one ``summary`` in BOTH halves,
plus a re-pin of those two blob ids, left every wired OpenAPI guard ``rc=0``
while ``/** Liveness */`` silently became something else.

``_OPERATION_SUMMARY_DIGEST`` is a second hand-written sha256 over the
canonical sorted ``(method, path, operationId, summary)`` tuples, read from
nowhere. The guard also checks that every generated ``paths`` operation's JSDoc
summary equals the snapshot's, so a one-sided edit is named by operation, and
that the generated operation count matches. Both doors move on a coordinated
retype only because the literal is independent of the artifacts.

Usage:
    python3 scripts/check_openapi_response_surface.py
    python3 scripts/check_openapi_response_surface.py --self-test
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

# A reviewed, hand-written fixed point on the whole published response surface.
# sha256 of "\n".join(["soymutdb-response-surface/v1"] +
#   sorted(f"{method} {path} {status} {description} {has_content}")).
# Regenerate with _digest() after an intentional contract change and update in
# the same commit, with a reason.
_RESPONSE_SURFACE_DIGEST = (
    "eb685be49379913d47db7b2e90ceec2e691931e69f992cb1e724a17b1ff1a951"
)
_EXPECTED_RESPONSE_ENTRIES = 808
_EXPECTED_OPERATION_COUNT = 268

# Independent fixed point for the operation-level ``summary`` prose. sha256 of
# "\n".join(["soymutdb-operation-summary/v1"] +
#   sorted(f"{method}|{path}|{operationId}|{summary}")). Regenerate with
# _summary_digest() after an intentional, reviewed contract change and update
# in the same commit as the two artifacts, with a reason.
_OPERATION_SUMMARY_DIGEST = (
    "e0ae8e0a760b465ad280c5c462e914bebadb18a98f627970159f0ba559fd0ac6"
)
_EXPECTED_SUMMARY_OPERATIONS = 268

# Independent fixed point for the request-body surface. ``openapi-typescript``
# renders ``requestBody.required: true`` as ``requestBody: {`` and a missing
# body as ``requestBody?: never;`` in the generated ``operations`` interface;
# a ``false``/absent required flag becomes ``requestBody?: {``. That optional
# marker is client-visible (a caller may omit the body), and no landed guard
# reads it: the body baselines count ``$ref`` bodies, ``_RESPONSE_SURFACE_DIGEST``
# walks responses, and ``_PINNED_ARTIFACTS`` is a provenance blob id that a
# regenerate re-pins in the same deliberate act. A coordinated co-revert that
# flips one ``required`` flag in both halves and re-pins those two blob ids
# left every wired OpenAPI guard ``rc=0`` on live bytes.
#
# sha256 of "\n".join(["soymutdb-request-body-surface/v1"] +
#   sorted(f"{method}|{path}|{operationId}|{state}")), where ``state`` is
# ``absent`` / ``true`` / ``false``. Read from nowhere; re-pin in the same
# commit as an intentional contract change, with a reason.
_REQUEST_BODY_SURFACE_DIGEST = (
    "11042ffae3a33f2eaf5e9324e389fe83c587d61bd6977906c7bfa367ea8491c0"
)
_EXPECTED_REQUEST_BODY_BEARING_OPERATIONS = 86

# The generated ``paths`` interface maps (METHOD, path) -> operations["symbol"].
PATH_LINE = re.compile(r'^    "(/[^"]*)": \{$')
OP_REF = re.compile(
    r"^        (get|put|post|patch|delete|options|head|trace): "
    r'operations\["([^"]+)"\];$'
)
# Each operation definition in the generated ``operations`` interface.
OP_DEF = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_]*): \{$", re.MULTILINE)
STATUS_KEY = re.compile(r"^            (\d{3}): \{$", re.MULTILINE)


def _snapshot_rows(document: dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    """Canonical (METHOD, path, status, description, has_content) rows."""
    rows: list[tuple[str, str, str, str, str]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            responses = operation.get("responses") or {}
            for status, response in responses.items():
                content = response.get("content") or {}
                rows.append(
                    (
                        method.upper(),
                        path,
                        str(status),
                        response.get("description", ""),
                        str(bool(content)),
                    )
                )
    return rows


def _digest(rows: list[tuple[str, str, str, str, str]]) -> str:
    canonical = sorted(rows)
    blob = "\n".join(
        ["soymutdb-response-surface/v2"]
        + ["|".join(row) for row in canonical]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _snapshot_surface(
    document: dict[str, Any],
) -> dict[tuple[str, str], dict[str, tuple[bool, str]]]:
    """(METHOD, path) -> {status: (has_content, description)}."""
    out: dict[tuple[str, str], dict[str, tuple[bool, str]]] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            key = (method.upper(), path)
            surface: dict[str, tuple[bool, str]] = {}
            for status, response in (operation.get("responses") or {}).items():
                surface[str(status)] = (
                    bool(response.get("content") or {}),
                    response.get("description", ""),
                )
            out[key] = surface
    return out


def _generated_path_map(generated: str) -> dict[tuple[str, str], str]:
    """(METHOD, path) -> operations[\"...\"] symbol, from the paths interface."""
    out: dict[tuple[str, str], str] = {}
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
        ref = OP_REF.match(line)
        if ref and path is not None:
            out[(ref.group(1).upper(), path)] = ref.group(2)
    return out


def _generated_operations(
    generated: str,
) -> dict[str, dict[str, tuple[bool, str]]]:
    """symbol -> {status: (has_content, description)} from the client."""
    start = generated.find("export interface operations {")
    if start < 0:
        raise ValueError("generated client has no operations interface")
    block = generated[start:]
    matches = list(OP_DEF.finditer(block))
    out: dict[str, dict[str, tuple[bool, str]]] = {}
    for i, match in enumerate(matches):
        name = match.group(1)
        body = block[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(block)
        ]
        rstart = body.find("        responses: {")
        if rstart < 0:
            continue
        surface: dict[str, tuple[bool, str]] = {}
        for status_match in STATUS_KEY.finditer(body, rstart):
            status = status_match.group(1)
            # The response object runs to the next status key at the same
            # indent or the end of this operation definition.
            nxt = STATUS_KEY.search(body, status_match.end())
            segment = body[status_match.end() : nxt.start() if nxt else len(body)]
            # The @description comment immediately precedes the status key.
            before = body[: status_match.start()]
            comments = list(re.finditer(r"/\*\* @description (.*?) \*/", before))
            description = comments[-1].group(1) if comments else ""
            surface[status] = ("content?: never;" not in segment, description)
        out[name] = surface
    return out


def _snapshot_summaries(
    document: dict[str, Any],
) -> dict[tuple[str, str], tuple[str, str]]:
    """(METHOD, path) -> (operationId, summary) from the published snapshot."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            out[(method.upper(), path)] = (
                str(operation.get("operationId", "")),
                str(operation.get("summary", "")),
            )
    return out


def _summary_digest(summaries: dict[tuple[str, str], tuple[str, str]]) -> str:
    rows = [
        (method, path, operation_id, summary)
        for (method, path), (operation_id, summary) in summaries.items()
    ]
    blob = "\n".join(
        ["soymutdb-operation-summary/v1"]
        + ["|".join(row) for row in sorted(rows)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ``openapi-typescript`` emits the operation summary as the JSDoc block that
# immediately precedes the ``operations["symbol"]`` reference. Two spellings
# occur in the committed artifact: a one-line ``/** text */`` on its own line,
# and a multi-line ``/**`` whose first ``* text`` line is the summary (with
# ``@description`` lines after it).
_ONELINE_DOC = re.compile(r"^\s*/\*\* (.*) \*/\s*$")


def _generated_summaries(generated: str) -> dict[tuple[str, str], str]:
    """(METHOD, path) -> JSDoc summary, from the generated paths interface."""
    start = generated.find("export interface paths {")
    if start < 0:
        raise ValueError("generated client has no paths interface")
    end = generated.find("\nexport interface ", start + 10)
    lines = generated[start : end if end >= 0 else len(generated)].splitlines()
    path: str | None = None
    out: dict[tuple[str, str], str] = {}
    for index, line in enumerate(lines):
        path_match = PATH_LINE.match(line)
        if path_match:
            path = path_match.group(1)
            continue
        ref = OP_REF.match(line)
        if not ref or path is None:
            continue
        summary = ""
        if index > 0:
            one = _ONELINE_DOC.match(lines[index - 1])
            if one:
                summary = one.group(1).strip()
            else:
                doc: list[str] = []
                j = index - 1
                # Stop at the enclosing path object. Without this bound an
                # operation with no JSDoc of its own could inherit a
                # neighbouring path's summary instead of being named.
                while (
                    j >= 0
                    and lines[j].strip() != "/**"
                    and not PATH_LINE.match(lines[j])
                ):
                    doc.append(lines[j])
                    j -= 1
                if j >= 0 and lines[j].strip() == "/**":
                    for doc_line in reversed(doc):
                        stripped = doc_line.strip()
                        if stripped.startswith("* @") or stripped in (
                            "*", "*/", "/**"
                        ):
                            continue
                        if stripped.startswith("* "):
                            summary = stripped[2:].strip()
                            break
        out[(ref.group(1).upper(), path)] = summary
    return out



# ``openapi-typescript`` emits one requestBody line per operation in the
# generated ``operations`` interface. ``?: never`` means no body declared;
# ``: {`` means required; ``?: {`` means optional.
GEN_REQUEST_BODY = re.compile(
    r"^        requestBody(\??): (\{|never;)$", re.MULTILINE
)


def _snapshot_request_bodies(
    document: dict[str, Any],
) -> dict[tuple[str, str], tuple[str, str]]:
    """(METHOD, path) -> (operationId, required-state) from the snapshot."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            body = operation.get("requestBody")
            if body is None:
                state = "absent"
            elif isinstance(body, dict) and body.get("required"):
                state = "true"
            elif isinstance(body, dict):
                state = "false"
            else:
                raise ValueError(f"{method.upper()} {path} has a malformed requestBody")
            out[(method.upper(), path)] = (
                str(operation.get("operationId", "")),
                state,
            )
    return out


def _request_body_digest(
    bodies: dict[tuple[str, str], tuple[str, str]],
) -> str:
    rows = [
        (method, path, operation_id, state)
        for (method, path), (operation_id, state) in bodies.items()
    ]
    blob = "\n".join(
        ["soymutdb-request-body-surface/v1"]
        + ["|".join(row) for row in sorted(rows)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _generated_request_bodies(generated: str) -> dict[str, str]:
    """symbol -> required-state, from the generated operations interface."""
    start = generated.find("export interface operations {")
    if start < 0:
        raise ValueError("generated client has no operations interface")
    block = generated[start:]
    matches = list(OP_DEF.finditer(block))
    out: dict[str, str] = {}
    for i, match in enumerate(matches):
        body = block[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(block)
        ]
        hit = GEN_REQUEST_BODY.search(body)
        if hit is None:
            raise ValueError(f"{match.group(1)} has no requestBody line")
        optional, shape = hit.group(1), hit.group(2)
        if shape == "never;":
            state = "absent"
        elif optional:
            state = "false"
        else:
            state = "true"
        out[match.group(1)] = state
    return out


def failures(
    *,
    snapshot: str | None = None,
    generated: str | None = None,
    smoke: str | None = None,
    digest: str | None = None,
    expected_entries: int | None = None,
    expected_operations: int | None = None,
    summary_digest: str | None = None,
    expected_summary_operations: int | None = None,
    request_body_digest: str | None = None,
    expected_request_body_operations: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means the contract is pinned."""
    found: list[str] = []
    if snapshot is None:
        snapshot = SNAPSHOT.read_text(encoding="utf-8")
    if generated is None:
        generated = GENERATED.read_text(encoding="utf-8")
    if smoke is None:
        smoke = SMOKE.read_text(encoding="utf-8")
    pinned_digest = _RESPONSE_SURFACE_DIGEST if digest is None else digest
    pinned_entries = (
        _EXPECTED_RESPONSE_ENTRIES if expected_entries is None else expected_entries
    )
    pinned_ops = (
        _EXPECTED_OPERATION_COUNT
        if expected_operations is None
        else expected_operations
    )
    pinned_summary_digest = (
        _OPERATION_SUMMARY_DIGEST if summary_digest is None else summary_digest
    )
    pinned_summary_ops = (
        _EXPECTED_SUMMARY_OPERATIONS
        if expected_summary_operations is None
        else expected_summary_operations
    )
    pinned_request_body_digest = (
        _REQUEST_BODY_SURFACE_DIGEST
        if request_body_digest is None
        else request_body_digest
    )
    pinned_request_body_ops = (
        _EXPECTED_REQUEST_BODY_BEARING_OPERATIONS
        if expected_request_body_operations is None
        else expected_request_body_operations
    )

    try:
        document = json.loads(snapshot)
        rows = _snapshot_rows(document)
        snap = _snapshot_surface(document)
        summaries = _snapshot_summaries(document)
        request_bodies = _snapshot_request_bodies(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published responses from snapshot: {exc}"]
    try:
        path_map = _generated_path_map(generated)
        gen_ops = _generated_operations(generated)
        gen_summaries = _generated_summaries(generated)
        gen_request_bodies = _generated_request_bodies(generated)
    except ValueError as exc:
        return [f"cannot read generated client responses: {exc}"]

    # Door 1 -- independent fixed point. A coordinated edit of both halves
    # changes the row set, so the digest moves even when the consistency
    # checks below still agree.
    actual_digest = _digest(rows)
    if actual_digest != pinned_digest:
        found.append(
            f"published response surface drifted: _RESPONSE_SURFACE_DIGEST pins "
            f"{pinned_digest} but the snapshot derives {actual_digest}. A "
            "baseline is a fixed point for the artifacts, not a place to make "
            "a guard agree with itself -- regenerate the client and re-pin the "
            "digest in the same commit, with a reason."
        )
    if len(rows) != pinned_entries:
        found.append(
            f"published response entry count is {len(rows)}, "
            f"_EXPECTED_RESPONSE_ENTRIES pins {pinned_entries}: a response was "
            "added or dropped without moving the fixed point"
        )
    if len(snap) != pinned_ops:
        found.append(
            f"published operation count is {len(snap)}, "
            f"_EXPECTED_OPERATION_COUNT pins {pinned_ops}: an operation was "
            "added or dropped"
        )

    # Door 2 -- the two surfaces must name the same response identities. A
    # one-sided edit (snapshot only, or generated client only) is named.
    if set(path_map) != set(snap):
        found.append(
            "generated paths/operations references do not match the published "
            f"operation set (missing={sorted(set(snap) - set(path_map))[:3]}, "
            f"phantom={sorted(set(path_map) - set(snap))[:3]})"
        )
    gen: dict[tuple[str, str], dict[str, tuple[bool, str]]] = {}
    for key, symbol in path_map.items():
        if symbol not in gen_ops:
            found.append(f"{key}: generated operations interface lacks {symbol!r}")
            continue
        gen[key] = gen_ops[symbol]
    for key in sorted(set(snap) & set(gen)):
        if set(snap[key]) != set(gen[key]):
            found.append(
                f"{key[0]} {key[1]}: generated response codes disagree with the "
                f"snapshot (snapshot_only={sorted(set(snap[key]) - set(gen[key]))[:3]}, "
                f"generated_only={sorted(set(gen[key]) - set(snap[key]))[:3]})"
            )
            continue
        for status in sorted(set(snap[key]) & set(gen[key])):
            if snap[key][status] != gen[key][status]:
                found.append(
                    f"{key[0]} {key[1]} {status}: published response description "
                    f"or content presence disagrees with the generated client "
                    f"(snapshot={snap[key][status]}, generated={gen[key][status]})"
                )

    # Door 3 -- every operation must declare at least one response, and
    # duplicate (operation, status) keys are impossible after JSON parsing but
    # a generated interface can repeat them.
    for key, surface in sorted(snap.items()):
        if not surface:
            found.append(f"{key[0]} {key[1]}: declares no responses")

    # Door 4 -- independent fixed point on operation-level summaries. A
    # coordinated retype of both halves moves both artifacts together, so the
    # digest is the only door that can name it.
    actual_summary_digest = _summary_digest(summaries)
    if actual_summary_digest != pinned_summary_digest:
        found.append(
            f"published operation summaries drifted: _OPERATION_SUMMARY_DIGEST "
            f"pins {pinned_summary_digest} but the snapshot derives "
            f"{actual_summary_digest}. Re-pin the literal in the same commit "
            "as the two artifacts, with a reason -- do not make the guard "
            "agree with itself."
        )
    if len(summaries) != pinned_summary_ops:
        found.append(
            f"published summary-bearing operation count is {len(summaries)}, "
            f"_EXPECTED_SUMMARY_OPERATIONS pins {pinned_summary_ops}: an "
            "operation was added or dropped"
        )

    # Door 5 -- the generated JSDoc summary must equal the snapshot for every
    # operation. A one-sided edit is named by (METHOD, path); a phantom or
    # missing generated operation is named too.
    if set(gen_summaries) != set(summaries):
        found.append(
            "generated paths JSDoc summaries do not match the published "
            f"operation set (missing={sorted(set(summaries) - set(gen_summaries))[:3]}, "
            f"phantom={sorted(set(gen_summaries) - set(summaries))[:3]})"
        )
    for key in sorted(set(summaries) & set(gen_summaries)):
        published = summaries[key][1]
        rendered = gen_summaries[key]
        if published != rendered:
            found.append(
                f"{key[0]} {key[1]}: published summary {published!r} disagrees "
                f"with generated JSDoc {rendered!r}"
            )


    # Door 6 -- independent fixed point on the request-body surface. A
    # coordinated retype of both halves moves both artifacts together, so the
    # literal is the only door that can name it; the provenance blob ids are
    # re-pinned as part of that same reviewed regenerate.
    actual_request_body_digest = _request_body_digest(request_bodies)
    if actual_request_body_digest != pinned_request_body_digest:
        found.append(
            f"published request bodies drifted: _REQUEST_BODY_SURFACE_DIGEST "
            f"pins {pinned_request_body_digest} but the snapshot derives "
            f"{actual_request_body_digest}. Re-pin the literal in the same "
            "commit as the two artifacts, with a reason -- do not make the "
            "guard agree with itself."
        )
    bearing = sum(1 for _, state in request_bodies.values() if state != "absent")
    if bearing != pinned_request_body_ops:
        found.append(
            f"published request-body-bearing operation count is {bearing}, "
            f"_EXPECTED_REQUEST_BODY_BEARING_OPERATIONS pins "
            f"{pinned_request_body_ops}: a request body was added or dropped"
        )

    # Door 7 -- the generated optional marker must equal the published
    # ``required`` flag for every operation. A one-sided edit is named by
    # (METHOD, path); a missing/phantom generated symbol is named too.
    for key, (symbol, state) in sorted(request_bodies.items()):
        rendered = gen_request_bodies.get(symbol)
        if rendered is None:
            found.append(f"{key[0]} {key[1]}: generated operations lack {symbol!r}")
        elif rendered != state:
            found.append(
                f"{key[0]} {key[1]}: published requestBody state {state!r} "
                f"disagrees with generated client {rendered!r}"
            )

    if f"scripts/{SELF}" not in smoke:
        found.append(f"contracts smoke layer does not invoke {SELF}")
    return found


def self_test() -> int:
    """Every one-sided and coordinated drift must be caught; clean tree passes."""
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    generated = GENERATED.read_text(encoding="utf-8")
    smoke = SMOKE.read_text(encoding="utf-8")
    clean = failures(snapshot=snapshot, generated=generated, smoke=smoke)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    document = json.loads(snapshot)
    target_path = "/api/v1/auth/logout"
    cases: dict[str, tuple[str, str]] = {}

    # One-sided status rename: snapshot only.
    doc = copy.deepcopy(document)
    responses = doc["paths"][target_path]["post"]["responses"]
    responses["205"] = responses.pop("204")
    cases["one-sided snapshot status rename"] = (
        json.dumps(doc, indent=2),
        generated,
    )

    # One-sided status rename: generated client only.
    key = "    logout_api_v1_auth_logout_post: {"
    start = generated.find(key)
    block = generated[start : start + 1600]
    changed = block.replace("            204: {", "            205: {", 1)
    assert changed != block
    cases["one-sided generated status rename"] = (
        snapshot,
        generated[:start] + changed + generated[start + 1600 :],
    )

    # Coordinated status rename in both halves. The digest is the only door
    # that can see this: both artifacts agree with each other.
    drifted_generated = generated[:start] + changed + generated[start + 1600 :]
    cases["coordinated status rename"] = (
        json.dumps(doc, indent=2),
        drifted_generated,
    )

    # A dropped content-less response in both halves.
    doc2 = copy.deepcopy(document)
    del doc2["paths"][target_path]["post"]["responses"]["204"]
    block2 = generated[start : start + 1600]
    drop = STATUS_KEY.search(block2)
    assert drop and drop.group(1) == "204"
    end = STATUS_KEY.search(block2, drop.end())
    block2 = block2[: drop.start()] + block2[end.start() if end else len(block2) :]
    dropped_generated = generated[:start] + block2 + generated[start + 1600 :]
    cases["coordinated content-less response dropped"] = (
        json.dumps(doc2, indent=2),
        dropped_generated,
    )

    # A content-bearing response loses its content in both halves: the
    # has_content column of the digest and the per-code shape check move.
    doc3 = copy.deepcopy(document)
    live = doc3["paths"]["/api/v1/health/live"]["get"]["responses"]["200"]
    live.pop("content", None)
    key2 = "    liveness_api_v1_health_live_get: {"
    start2 = generated.find(key2)
    block3 = generated[start2 : start2 + 1600]
    changed3 = block3.replace(
        "                content: {", "                content?: never;", 1
    )
    assert changed3 != block3
    cases["coordinated content dropped"] = (
        json.dumps(doc3, indent=2),
        generated[:start2] + changed3 + generated[start2 + 1600 :],
    )

    # A coordinated response-description retype in both halves. The digest is
    # the only door that can see it: both artifacts agree with each other, no
    # status or content shape moves, and every other wired guard stays green.
    doc4 = copy.deepcopy(document)
    live4 = doc4["paths"]["/api/v1/health/live"]["get"]["responses"]["200"]
    live4["description"] = "OK"
    start4 = generated.find("    liveness_api_v1_health_live_get: {")
    block4 = generated[start4 : start4 + 1600]
    changed4 = block4.replace(
        "/** @description Successful Response */", "/** @description OK */", 1
    )
    assert changed4 != block4
    cases["coordinated response description retype"] = (
        json.dumps(doc4, indent=2),
        generated[:start4] + changed4 + generated[start4 + 1600 :],
    )

    # A coordinated operation-summary retype in both halves. Both artifacts
    # agree; the byte-provenance guards are re-pinned as their own documented
    # action; every other wired guard stays green. Only the independent
    # summary literal can catch it.
    doc5 = copy.deepcopy(document)
    doc5["paths"]["/api/v1/health/live"]["get"]["summary"] = "Liveness probe (edited)"
    changed5 = generated.replace(
        "         * Liveness\n", "         * Liveness probe (edited)\n", 1
    )
    assert changed5 != generated
    cases["coordinated operation summary retype"] = (
        json.dumps(doc5, indent=2),
        changed5,
    )

    # One-sided summary retype: snapshot only. Named by (METHOD, path).
    doc6 = copy.deepcopy(document)
    doc6["paths"]["/api/v1/health/live"]["get"]["summary"] = "Only snapshot changed"
    cases["one-sided snapshot summary retype"] = (
        json.dumps(doc6, indent=2),
        generated,
    )

    # One-sided summary retype: generated JSDoc only.
    changed7 = generated.replace(
        "         * Liveness\n", "         * Only client changed\n", 1
    )
    assert changed7 != generated
    cases["one-sided generated summary retype"] = (snapshot, changed7)

    # A summary dropped from the snapshot but kept in the client.
    doc8 = copy.deepcopy(document)
    del doc8["paths"]["/api/v1/health/live"]["get"]["summary"]
    cases["published summary dropped"] = (json.dumps(doc8, indent=2), generated)

    # Request-body surface: ``requestBody.required`` is published in the
    # snapshot and rendered as the optional marker on ``requestBody`` in the
    # generated operations interface. Both halves must agree with the literal.
    target = "/api/v1/auth/register"
    symbol = "register_api_v1_auth_register_post"
    op_key = f"    {symbol}: {{"
    op_start = generated.find(op_key)
    assert op_start >= 0
    op_slice = generated[op_start : op_start + 1200]
    assert "        requestBody: {" in op_slice

    def gen_with_request_body(replacement: str) -> str:
        changed = op_slice.replace("        requestBody: {", replacement, 1)
        assert changed != op_slice
        return generated[:op_start] + changed + generated[op_start + 1200 :]

    # One-sided required flag flip: snapshot only.
    doc9 = copy.deepcopy(document)
    doc9["paths"][target]["post"]["requestBody"]["required"] = False
    cases["one-sided snapshot requestBody required flip"] = (
        json.dumps(doc9, indent=2),
        generated,
    )

    # One-sided required flag flip: generated optional marker only.
    cases["one-sided generated requestBody optional marker"] = (
        snapshot,
        gen_with_request_body("        requestBody?: {"),
    )

    # Coordinated co-revert of both halves. The digest is the only door that
    # can see this: both artifacts still agree with each other, and the
    # provenance blob ids are re-pinned as part of the same reviewed act.
    cases["coordinated requestBody required co-revert"] = (
        json.dumps(doc9, indent=2),
        gen_with_request_body("        requestBody?: {"),
    )

    # A request body dropped from both halves (state absent -> never).
    doc10 = copy.deepcopy(document)
    del doc10["paths"][target]["post"]["requestBody"]
    cases["coordinated requestBody dropped"] = (
        json.dumps(doc10, indent=2),
        gen_with_request_body("        requestBody?: never;"),
    )

    # A same-count permutation: move a required body to another operation
    # while keeping 86 bearers. The digest must still move.
    doc11 = copy.deepcopy(document)
    donor = "/api/v1/auth/login"
    doc11["paths"][donor]["post"]["requestBody"] = doc11["paths"][target]["post"][
        "requestBody"
    ]
    del doc11["paths"][target]["post"]["requestBody"]
    cases["same-count requestBody permutation"] = (
        json.dumps(doc11, indent=2),
        generated,
    )

    failures_count = 0
    for name, (snap_text, gen_text) in cases.items():
        found = failures(snapshot=snap_text, generated=gen_text, smoke=smoke)
        if not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")
    if failures_count:
        return 1
    print(f"self-test: {len(cases)} cases, 0 failure(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    found = failures()
    if found:
        for problem in found:
            print(f"openapi-response-surface: FAIL: {problem}", file=sys.stderr)
        return 1
    print(
        f"openapi-response-surface: OK "
        f"({_EXPECTED_RESPONSE_ENTRIES} declared responses and "
        f"{_EXPECTED_SUMMARY_OPERATIONS} operation summaries and "
        f"{_EXPECTED_REQUEST_BODY_BEARING_OPERATIONS} request bodies pinned "
        f"across {_EXPECTED_OPERATION_COUNT} operations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

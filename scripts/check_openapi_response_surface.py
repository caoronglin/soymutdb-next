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
* ``_CLIENT_RESPONSE_SURFACE_DIGEST`` -- a SECOND hand-written sha256, over
  the canonical sorted ``(symbol, status, has_content, description)`` rows of
  the GENERATED ``operations`` interface, read from nowhere. Every literal
  above walks the snapshot and every agreement door compares the two halves
  to each other; a coordinated regenerate that retypes one response in both
  halves and honestly re-pins ``_RESPONSE_SURFACE_DIGEST`` in the same commit
  otherwise leaves nothing to object. One reviewed re-pin can no longer
  silence both digest doors;
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

The declared response ``headers`` are the same genus one level deeper: the
generated client prints each header's ``description`` as a JSDoc comment above
its property in the status's ``headers`` block. No landed guard reads
``responses.*.headers``; a coordinated retype of the ``Retry-After`` header in
both halves, with the provenance blob ids re-pinned, left all ten OpenAPI
guards, 212 pytest cases and ``SMOKE PASS`` green. ``_RESPONSE_HEADER_SURFACE_DIGEST``
is a fourth hand-written sha256 over the canonical sorted header rows, read
from nowhere, with a count door and a per-header cross-artifact agreement door.

The declared response **status order** is the same genus one level up.
``openapi-typescript`` prints each operation's response codes in the
snapshot's insertion order inside the generated ``operations`` interface, so
the sequence is a published fact (IDE completion order on the response union,
object key enumeration). Every landed digest above is a ``sorted()`` row set:
swapping two adjacent status blocks -- each keeping its own description and
content -- leaves ``_RESPONSE_SURFACE_DIGEST``, the client literal, all four
count doors and the three-way agreement unchanged. Both provenance blob ids
honestly re-pinned beside that regenerate keep the whole layer green.

Two independent hand-written literals close it, one per artifact half:

* ``_RESPONSE_STATUS_ORDER_DIGEST`` -- sha256 over canonical
  ``(METHOD, path, operationId, index, status)`` rows of the snapshot, in
  declaration order, read from nowhere;
* ``_CLIENT_RESPONSE_STATUS_ORDER_DIGEST`` -- the same positional rows parsed
  from the generated ``operations`` blocks, a second literal. A one-sided
  reorder re-pins one and stays red on the other; a coordinated co-revert of
  both halves moves both. Exact row-count doors plus a named positional door
  report the moved status by operation, index and code.

Re-deriving either literal from the artifact under guard would make the pin
self-referential -- the exact shape this file exists to refuse.

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

# Second independent fixed point, on the GENERATED half. Every literal above
# walks the snapshot; the three-way agreement below compares the two halves to
# each other. A coordinated regenerate that retypes one response description
# (or drops a content-bearing response) in BOTH halves and honestly re-pins
# _RESPONSE_SURFACE_DIGEST in the same commit leaves nothing to object: the
# snapshot digest agrees by construction and the agreement doors agree with
# themselves. This sha256 is read from nowhere -- it is over the canonical
# sorted (symbol, status, has_content, description) rows of the generated
# operations interface, so no single reviewed re-pin can silence both doors.
# Regenerate with _client_response_surface_digest() after an intentional
# reviewed regenerate, in the same commit as both artifacts and both literals,
# with a reason.
_CLIENT_RESPONSE_SURFACE_DIGEST = (
    "43c67d75eb298e9d42401738c12c856726aaacaa376755fd1a53cfedfe3408bc"
)
_EXPECTED_CLIENT_RESPONSE_ENTRIES = 808

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

# Independent fixed point for declared response headers. ``openapi-typescript``
# renders a response's ``headers`` entry as a named property in that status's
# ``headers: { ... }`` block, with the header ``description`` as a JSDoc
# ``@description`` line above it. That text is client-visible: a regenerate can
# retype it or move the header to another response while every status, body and
# count pin stays unchanged. No landed guard reads ``responses.*.headers`` --
# ``_RESPONSE_SURFACE_DIGEST`` walks (status, description, has_content) only,
# ``_BODY_PAIR_DIGEST`` sees ``$ref`` bodies, and ``_PINNED_ARTIFACTS`` is a
# provenance blob id a regenerate re-pins in the same reviewed act.
#
# sha256 of "\n".join(["soymutdb-response-headers/v1"] + sorted
#   "method|path|status|name|description|canonical-schema-json"). Read from
# nowhere; re-pin in the same commit as an intentional contract change.
_RESPONSE_HEADER_SURFACE_DIGEST = (
    "5685ec6bcfa376ed9dcdc38c322371b21d35ff18cde1d41e9b2c7bc935fc369b"
)
_EXPECTED_RESPONSE_HEADERS = 1

# Independent fixed points on the *declaration order* of response statuses.
# sha256 of "\n".join([label, *sorted("METHOD|path|operationId|index|status")])
# over the snapshot, and over the generated operations blocks respectively.
# Hand-written, NOT derived from either artifact under guard. A regenerate
# that reorders two statuses must re-pin BOTH in the same commit, with a reason.
_RESPONSE_STATUS_ORDER_DIGEST = (
    "6d5c2259fbe9376d06844192d795ddb692f09a7007efb9d2959a24ac4418e8a8"
)
_CLIENT_RESPONSE_STATUS_ORDER_DIGEST = (
    "7fc1f83a09b61f3e417f7420f56261c45b23c6b306e37055c2f3592418f60725"
)
_EXPECTED_RESPONSE_STATUS_ORDER_ROWS = 808

# Independent fixed point on the DECLARATION ORDER of the generated ``operations``
# interface symbols (268 ``export interface operations`` blocks). Every digest
# above reduces that interface to a sorted row set, the path map compares two
# halves to each other, and the byte fixed point re-emits the generator's own
# order. A regenerate that swaps two adjacent operation blocks -- each keeping
# its own parameters, requestBody, responses and doc comments -- moves no row
# any landed door reads: the published contract is unchanged, but the interface
# declaration sequence (IDE completion order, object key enumeration) silently
# drifts. ``openapi-typescript`` emits these blocks in an order that differs
# from the snapshot's path order at 10 positions, so a snapshot-side projection
# is not a substitute for reading the generated bytes.
#
# sha256 of "\n".join(["soymutdb-operation-symbol-order/v1"] +
#   "index|symbol" rows IN DECLARATION ORDER), read from nowhere; re-pin in the
# same commit as an intentional, reviewed regenerate, with a reason.
_OPERATION_SYMBOL_ORDER_DIGEST = (
    "1dc540216ab03dbce2641a15380466afcd1f01cad9930b287a230b4a5e019f48"
)
_EXPECTED_OPERATION_SYMBOLS = 268

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


def client_response_surface_rows(
    operations: dict[str, dict[str, tuple[bool, str]]]
) -> list[tuple[str, str, str, str]]:
    """Canonical (symbol, status, has_content, description) rows of the client half."""
    return [
        (symbol, status, str(has_content), description)
        for symbol, surface in operations.items()
        for status, (has_content, description) in surface.items()
    ]


def _client_response_surface_digest(
    rows: list[tuple[str, str, str, str]],
) -> str:
    canonical = sorted("|".join(row) for row in rows)
    blob = "\n".join(["soymutdb-client-response-surface/v1", *canonical])
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



def operation_symbol_order_rows(generated: str) -> list[tuple[str, str]]:
    """Canonical (index, symbol) rows IN DECLARATION ORDER of `operations`.

    The interface is the last top-level block in the generated file, so every
    ``OP_DEF`` match from its opening brace to EOF is an operation symbol.
    """
    start = generated.find("export interface operations {")
    if start < 0:
        raise ValueError("generated client has no operations interface")
    block = generated[start:]
    names = OP_DEF.findall(block)
    return [(str(index), name) for index, name in enumerate(names)]


def _operation_symbol_order_digest(rows: list[tuple[str, str]]) -> str:
    blob = "\n".join(
        ["soymutdb-operation-symbol-order/v1", *["|".join(row) for row in rows]]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

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


# The generated ``headers: { ... }`` block of a response carries each declared
# header as a named optional property, with its description in a JSDoc line
# immediately above it. ``[name: string]: unknown;`` is an index signature, not
# a declared header, and is skipped because it has no quoted name.
GEN_HEADER = re.compile(
    r"^                    (?:/\*\* @description (.*?) \*/\n"
    r"                    )?\"([^\"]+)\"\?: ([^;]+);$",
    re.MULTILINE,
)


def _snapshot_response_headers(
    document: dict[str, Any],
) -> list[tuple[str, str, str, str, str, str]]:
    """Canonical (METHOD, path, status, name, description, schema) rows."""
    rows: list[tuple[str, str, str, str, str, str]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            for status, response in (operation.get("responses") or {}).items():
                headers = response.get("headers") or {}
                for name, header in headers.items():
                    if not isinstance(header, dict):
                        raise ValueError(
                            f"{method.upper()} {path} {status} header {name!r} "
                            "is not an object"
                        )
                    rows.append(
                        (
                            method.upper(),
                            path,
                            str(status),
                            str(name),
                            str(header.get("description", "")),
                            json.dumps(
                                header.get("schema", {}),
                                sort_keys=True,
                                ensure_ascii=False,
                            ),
                        )
                    )
    return rows


def _response_header_digest(
    rows: list[tuple[str, str, str, str, str, str]],
) -> str:
    blob = "\n".join(
        ["soymutdb-response-headers/v1"] + ["|".join(row) for row in sorted(rows)]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _generated_response_headers(
    generated: str,
) -> dict[tuple[str, str], dict[str, str]]:
    """(symbol, status) -> {header name: JSDoc description} from the client."""
    start = generated.find("export interface operations {")
    if start < 0:
        raise ValueError("generated client has no operations interface")
    block = generated[start:]
    op_matches = list(OP_DEF.finditer(block))
    out: dict[tuple[str, str], dict[str, str]] = {}
    for i, op_match in enumerate(op_matches):
        symbol = op_match.group(1)
        body = block[
            op_match.end() : op_matches[i + 1].start()
            if i + 1 < len(op_matches)
            else len(block)
        ]
        rstart = body.find("        responses: {")
        if rstart < 0:
            continue
        for status_match in STATUS_KEY.finditer(body, rstart):
            nxt = STATUS_KEY.search(body, status_match.end())
            segment = body[
                status_match.end() : nxt.start() if nxt else len(body)
            ]
            hstart = segment.find("                headers: {")
            if hstart < 0:
                continue
            hend = segment.find("\n                };", hstart)
            hblock = segment[hstart : hend if hend >= 0 else len(segment)]
            named: dict[str, str] = {}
            for hit in GEN_HEADER.finditer(hblock):
                description, name = hit.group(1), hit.group(2)
                if description is None or name.startswith("["):
                    continue  # index signature, not a declared header
                named[name] = description
            if named:
                out[(symbol, status_match.group(1))] = named
    return out


def snapshot_status_order_rows(
    document: dict[str, Any],
) -> list[tuple[str, str, str, str, str]]:
    """Canonical (METHOD, path, operationId, index, status) rows, in order."""
    rows: list[tuple[str, str, str, str, str]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            oid = operation.get("operationId", "")
            for index, status in enumerate(operation.get("responses") or {}):
                rows.append((method.upper(), path, str(oid), str(index), str(status)))
    return rows


def generated_status_order_rows(generated: str) -> list[tuple[str, str, str]]:
    """Canonical (symbol, index, status) rows from generated operations blocks."""
    marker = "export interface operations {"
    if marker not in generated:
        raise ValueError("generated client declares no operations interface")
    block = generated.split(marker, 1)[1]
    starts = [(m.start(), m.group(1)) for m in OP_DEF.finditer(block)]
    rows: list[tuple[str, str, str]] = []
    for i, (position, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(block)
        body = block[position:end]
        rstart = body.find("        responses: {")
        if rstart < 0:
            continue
        for index, status in enumerate(STATUS_KEY.findall(body[rstart:])):
            rows.append((name, str(index), status))
    return rows


def _status_order_digest(rows: list[tuple[str, ...]]) -> str:
    canonical = sorted("|".join(row) for row in rows)
    blob = "\n".join(["soymutdb-response-status-order/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _client_status_order_digest(rows: list[tuple[str, ...]]) -> str:
    canonical = sorted("|".join(row) for row in rows)
    blob = "\n".join(["soymutdb-client-response-status-order/v1", *canonical])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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
    response_header_digest: str | None = None,
    expected_response_headers: int | None = None,
    client_response_surface_digest: str | None = None,
    expected_client_response_entries: int | None = None,
    response_status_order_digest: str | None = None,
    client_response_status_order_digest: str | None = None,
    expected_response_status_order_rows: int | None = None,
    operation_symbol_order_digest: str | None = None,
    expected_operation_symbols: int | None = None,
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
    pinned_response_header_digest = (
        _RESPONSE_HEADER_SURFACE_DIGEST
        if response_header_digest is None
        else response_header_digest
    )
    pinned_response_headers = (
        _EXPECTED_RESPONSE_HEADERS
        if expected_response_headers is None
        else expected_response_headers
    )
    pinned_client_response_surface_digest = (
        _CLIENT_RESPONSE_SURFACE_DIGEST
        if client_response_surface_digest is None
        else client_response_surface_digest
    )
    pinned_client_response_entries = (
        _EXPECTED_CLIENT_RESPONSE_ENTRIES
        if expected_client_response_entries is None
        else expected_client_response_entries
    )
    pinned_status_order = (
        _RESPONSE_STATUS_ORDER_DIGEST
        if response_status_order_digest is None
        else response_status_order_digest
    )
    pinned_client_status_order = (
        _CLIENT_RESPONSE_STATUS_ORDER_DIGEST
        if client_response_status_order_digest is None
        else client_response_status_order_digest
    )
    pinned_status_order_rows = (
        _EXPECTED_RESPONSE_STATUS_ORDER_ROWS
        if expected_response_status_order_rows is None
        else expected_response_status_order_rows
    )
    pinned_symbol_order = (
        _OPERATION_SYMBOL_ORDER_DIGEST
        if operation_symbol_order_digest is None
        else operation_symbol_order_digest
    )
    pinned_symbol_count = (
        _EXPECTED_OPERATION_SYMBOLS
        if expected_operation_symbols is None
        else expected_operation_symbols
    )

    try:
        document = json.loads(snapshot)
        rows = _snapshot_rows(document)
        snap = _snapshot_surface(document)
        summaries = _snapshot_summaries(document)
        request_bodies = _snapshot_request_bodies(document)
        header_rows = _snapshot_response_headers(document)
        status_order = snapshot_status_order_rows(document)
    except (ValueError, TypeError) as exc:
        return [f"cannot read published responses from snapshot: {exc}"]
    try:
        path_map = _generated_path_map(generated)
        gen_ops = _generated_operations(generated)
        gen_summaries = _generated_summaries(generated)
        gen_request_bodies = _generated_request_bodies(generated)
        gen_headers = _generated_response_headers(generated)
        client_status_order = generated_status_order_rows(generated)
        symbol_order = operation_symbol_order_rows(generated)
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

    # Door 1b -- a second independent fixed point, over the generated half.
    # Door 1 pins the snapshot; Doors 2/3 compare the halves to each other. A
    # coordinated regenerate with one honest re-pin of _RESPONSE_SURFACE_DIGEST
    # silences Door 1 and still agrees across Doors 2/3. This literal is read
    # from nowhere, so a reviewed change must re-pin BOTH digests.
    client_rows = client_response_surface_rows(gen_ops)
    actual_client_digest = _client_response_surface_digest(client_rows)
    if actual_client_digest != pinned_client_response_surface_digest:
        found.append(
            "generated client response surface drifted: "
            f"_CLIENT_RESPONSE_SURFACE_DIGEST pins "
            f"{pinned_client_response_surface_digest} but the client derives "
            f"{actual_client_digest}. A client-visible response description, "
            "content presence or code moved; re-pin BOTH digest literals in "
            "the same commit as both artifacts, with a reason."
        )
    if len(client_rows) != pinned_client_response_entries:
        found.append(
            f"generated client response entry count is {len(client_rows)}, "
            f"_EXPECTED_CLIENT_RESPONSE_ENTRIES pins "
            f"{pinned_client_response_entries}: a response was added or "
            "dropped without moving the client fixed point"
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

    # Door 8 -- independent fixed point on declared response headers. A
    # coordinated retype of one header's description (or schema) in BOTH halves
    # moves both artifacts together, so only the literal can name it; the body
    # baselines and response-surface digest never read ``headers``.
    actual_header_digest = _response_header_digest(header_rows)
    if actual_header_digest != pinned_response_header_digest:
        found.append(
            f"published response headers drifted: "
            f"_RESPONSE_HEADER_SURFACE_DIGEST pins "
            f"{pinned_response_header_digest} but the snapshot derives "
            f"{actual_header_digest}. Re-pin the literal in the same commit "
            "as the two artifacts, with a reason -- do not make the guard "
            "agree with itself."
        )
    if len(header_rows) != pinned_response_headers:
        found.append(
            f"published response header count is {len(header_rows)}, "
            f"_EXPECTED_RESPONSE_HEADERS pins {pinned_response_headers}: a "
            "declared header was added or dropped"
        )

    # Door 9 -- cross-artifact agreement. The snapshot's declared headers and
    # the generated ``headers`` blocks are compared as (symbol, status, name,
    # description) tuples, so a one-sided edit is named. A header moved to a
    # different response is caught by Door 8 even when the two halves agree.
    snap_header_set = set()
    for method, path, status, name, description, _schema in header_rows:
        symbol = path_map.get((method, path))
        if symbol is not None:
            snap_header_set.add((symbol, status, name, description))
    gen_header_set = {
        (symbol, status, name, description)
        for (symbol, status), named in gen_headers.items()
        for name, description in named.items()
    }
    for entry in sorted(snap_header_set - gen_header_set):
        found.append(
            f"declared response header {entry[2]!r} on {entry[0]} {entry[1]} "
            f"is not rendered with description {entry[3]!r} in the client"
        )
    for entry in sorted(gen_header_set - snap_header_set):
        found.append(
            f"generated client declares response header {entry[2]!r} on "
            f"{entry[0]} {entry[1]} the snapshot does not publish"
        )

    # Door 5 -- response-status *declaration order*. Every digest above is a
    # sorted row set; only positional literals can see two adjacent status
    # blocks swap places while each keeps its own description and content.
    actual_status_order = _status_order_digest(status_order)
    if actual_status_order != pinned_status_order:
        found.append(
            "published response status order drifted: "
            f"_RESPONSE_STATUS_ORDER_DIGEST pins {pinned_status_order} but the "
            f"snapshot derives {actual_status_order}. Re-pin BOTH status-order "
            "literals in the same commit as both artifacts, with a reason."
        )
    if len(status_order) != pinned_status_order_rows:
        found.append(
            f"published response status order row count is {len(status_order)}, "
            f"_EXPECTED_RESPONSE_STATUS_ORDER_ROWS pins "
            f"{pinned_status_order_rows}: a status was added or dropped without "
            "moving the fixed point"
        )
    actual_client_status_order = _client_status_order_digest(client_status_order)
    if actual_client_status_order != pinned_client_status_order:
        found.append(
            "generated client response status order drifted: "
            f"_CLIENT_RESPONSE_STATUS_ORDER_DIGEST pins "
            f"{pinned_client_status_order} but the client derives "
            f"{actual_client_status_order}. A one-sided reorder or a coordinated "
            "co-revert of both halves must not ship silently."
        )
    if len(client_status_order) != pinned_status_order_rows:
        found.append(
            f"generated client status order row count is {len(client_status_order)}, "
            f"_EXPECTED_RESPONSE_STATUS_ORDER_ROWS pins "
            f"{pinned_status_order_rows}"
        )

    # Door 6 -- generated ``operations`` symbol DECLARATION ORDER. Every digest
    # above is a sorted row set; only a positional literal can see two adjacent
    # operation blocks trade places while each keeps its own body.
    actual_symbol_order = _operation_symbol_order_digest(symbol_order)
    if actual_symbol_order != pinned_symbol_order:
        found.append(
            "generated client operation symbol order drifted: "
            f"_OPERATION_SYMBOL_ORDER_DIGEST pins {pinned_symbol_order} but "
            f"the client derives {actual_symbol_order}. A regenerate that "
            "reorders operation blocks without moving any published row must "
            "not ship silently. Re-pin the literal in the same commit as the "
            "generated client, with a reason."
        )
    if len(symbol_order) != pinned_symbol_count:
        found.append(
            f"generated client operation symbol count is {len(symbol_order)}, "
            f"_EXPECTED_OPERATION_SYMBOLS pins {pinned_symbol_count}: an "
            "operation was added or dropped without moving the fixed point"
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

    # Declared response headers: a coordinated retype of the one ``Retry-After``
    # header's description in BOTH halves. Before Door 8, all ten OpenAPI guards,
    # 212 pytest cases and the whole contracts layer stayed green on this shape
    # (the header text is client-visible JSDoc, not a body or status).
    old_header = "Seconds until this login attempt may be retried."
    new_header = "Seconds until this login attempt may be retried (edited)."
    header_gen_key = "    login_api_v1_auth_login_post: {"
    header_start = generated.find(header_gen_key)
    assert header_start >= 0
    header_slice = generated[header_start : header_start + 1600]
    assert f"/** @description {old_header} */" in header_slice

    def gen_with_header(text: str) -> str:
        changed = header_slice.replace(
            f"/** @description {old_header} */",
            f"/** @description {text} */",
            1,
        )
        assert changed != header_slice
        return generated[:header_start] + changed + generated[header_start + 1600 :]

    # One-sided retype: snapshot only. Door 9 names the disagreement.
    doc12 = copy.deepcopy(document)
    hdr12 = doc12["paths"]["/api/v1/auth/login"]["post"]["responses"]["429"][
        "headers"
    ]["Retry-After"]
    hdr12["description"] = new_header
    cases["one-sided snapshot response header retype"] = (
        json.dumps(doc12, indent=2),
        generated,
    )

    # One-sided retype: generated JSDoc only. Door 9 names it too.
    cases["one-sided generated response header retype"] = (
        snapshot,
        gen_with_header(new_header),
    )

    # Coordinated co-revert of both halves: the decisive drift. Only the
    # independent header digest can name it; both artifacts still agree with
    # each other, and re-pinning the provenance blob ids is the documented
    # reviewed action that accompanies a regenerate.
    cases["coordinated response header co-revert"] = (
        json.dumps(doc12, indent=2),
        gen_with_header(new_header),
    )

    # A declared header dropped from the snapshot only (count door + Door 9).
    doc13 = copy.deepcopy(document)
    del doc13["paths"]["/api/v1/auth/login"]["post"]["responses"]["429"]["headers"]
    cases["declared response header dropped"] = (
        json.dumps(doc13, indent=2),
        generated,
    )

    # The generated client half has its own fixed point. These three plants
    # prove it is load-bearing and not merely a duplicate of Door 1.
    client_doc = copy.deepcopy(document)
    client_live = client_doc["paths"]["/api/v1/health/live"]["get"]["responses"]["200"]
    client_live["description"] = "OK"
    start4b = generated.find("    liveness_api_v1_health_live_get: {")
    block4b = generated[start4b : start4b + 1600]
    changed4b = block4b.replace(
        "/** @description Successful Response */", "/** @description OK */", 1
    )
    assert changed4b != block4b
    co_reverted_generated = (
        generated[:start4b] + changed4b + generated[start4b + 1600 :]
    )
    honest_snapshot_digest = _digest(_snapshot_rows(client_doc))

    # Decisive: both halves move together AND the snapshot digest is honestly
    # re-pinned to the new rows. Door 1 goes silent, Doors 2/3 agree with
    # themselves; only the independent generated-client literal remains.
    cases["coordinated description co-revert with an honest snapshot re-pin"] = (
        json.dumps(client_doc, indent=2),
        co_reverted_generated,
    )
    # ---- Door 5: response-status declaration order --------------------
    # Coherent swap of two adjacent status blocks in BOTH halves. Each status
    # keeps its own description and content, so every sorted digest, every
    # count door and the three-way agreement stay silent; only the positional
    # literals can see it. This is the decisive fail-open the door closes.
    order_doc = copy.deepcopy(document)
    order_path = "/api/v1/health/live"
    order_op = order_doc["paths"][order_path]["get"]
    order_responses = order_op["responses"]
    first, second = list(order_responses)[:2]
    reordered: dict[str, Any] = {}
    for status in order_responses:
        if status == first:
            reordered[second] = order_responses[second]
        elif status == second:
            reordered[first] = order_responses[first]
        else:
            reordered[status] = order_responses[status]
    order_op["responses"] = reordered
    order_snapshot = json.dumps(order_doc, indent=2)

    order_symbol = "liveness_api_v1_health_live_get"
    order_start = generated.find(f"    {order_symbol}: {{")
    assert order_start >= 0
    order_following = OP_DEF.search(generated, order_start + 10)
    order_end = order_following.start() if order_following else len(generated)
    order_block = generated[order_start:order_end]
    status_matches = list(STATUS_KEY.finditer(order_block))
    assert len(status_matches) >= 2
    # Each block: the optional preceding @description line + the status body
    # up to the next status key. Moving them together keeps each description
    # beside its own code -- exactly what a regenerate emits.
    rstart = order_block.find("        responses: {")
    closer = re.search(r"^        \};$", order_block[rstart:], re.M)
    assert closer is not None
    rend = rstart + closer.start()
    prefix = order_block[: rstart + len("        responses: {\n")]
    suffix = order_block[rend:]
    segments: list[str] = []
    for i, m in enumerate(status_matches):
        nxt = status_matches[i + 1] if i + 1 < len(status_matches) else None
        begin = m.start()
        desc = order_block.rfind("/** @description ", rstart, begin)
        if desc >= 0:
            begin = desc
        end = nxt.start() if nxt else rend
        segments.append(order_block[begin:end])
    # Move the first two whole segments (description + status body) together.
    segments[0], segments[1] = segments[1], segments[0]
    swapped_block = prefix + "".join(segments) + suffix
    order_generated = generated[:order_start] + swapped_block + generated[order_end:]

    cases["coordinated response status order swap in both halves"] = (
        order_snapshot,
        order_generated,
    )
    # One-sided: snapshot only, and generated only. Both halves' literals are
    # independent, so each reorder is named by exactly one door.
    cases["one-sided snapshot response status order swap"] = (
        order_snapshot,
        generated,
    )
    cases["one-sided generated response status order swap"] = (
        snapshot,
        order_generated,
    )
    # Independence controls: re-pinning ONLY ONE of the two positional
    # literals beside a coordinated swap must leave the OTHER door red. A
    # single literal, or two literals derived from one artifact half, would
    # let the co-revert walk through. These are the load-bearing shape.
    honest_status_order = _status_order_digest(
        snapshot_status_order_rows(order_doc)
    )
    honest_client_status_order = _client_status_order_digest(
        generated_status_order_rows(order_generated)
    )

    overrides: dict[str, dict[str, Any]] = {
        "coordinated description co-revert with an honest snapshot re-pin": {
            "digest": honest_snapshot_digest,
        },
        "generated client response count door": {
            "expected_client_response_entries": _EXPECTED_CLIENT_RESPONSE_ENTRIES + 1,
        },
        "coordinated status swap with only the snapshot literal re-pinned": {
            "response_status_order_digest": honest_status_order,
        },
        "coordinated status swap with only the client literal re-pinned": {
            "client_response_status_order_digest": honest_client_status_order,
        },
        "coordinated status order swap with both literals re-pinned": {
            "response_status_order_digest": honest_status_order,
            "client_response_status_order_digest": honest_client_status_order,
        },
    }

    # One-sided generated-only retype: named by the client digest AND the
    # cross-artifact agreement (Door 2), never by the snapshot digest.
    cases["one-sided generated response description retype"] = (
        snapshot,
        co_reverted_generated,
    )
    # Exact count door on the generated half.
    cases["generated client response count door"] = (snapshot, generated)

    # One-sided re-pins: each must still be caught by the other door.
    cases["coordinated status swap with only the snapshot literal re-pinned"] = (
        order_snapshot,
        order_generated,
    )
    cases["coordinated status swap with only the client literal re-pinned"] = (
        order_snapshot,
        order_generated,
    )
    # Honest double re-pin of BOTH positional literals beside a reviewed
    # regenerate: the only green shape among the coordinated drifts.
    cases["coordinated status order swap with both literals re-pinned"] = (
        order_snapshot,
        order_generated,
    )

    # ---- Door 6: generated ``operations`` symbol declaration order -----
    # Coherent swap of two adjacent operation blocks (each keeps its own
    # body) in the generated half only: the snapshot is untouched, every
    # sorted digest and count door stays silent, and the three-way agreement
    # still holds (the symbols keep their own responses). Only the positional
    # literal sees the drift.
    sym_gen_start = generated.find("export interface operations {")
    sym_matches = list(OP_DEF.finditer(generated, sym_gen_start))
    assert len(sym_matches) >= 2
    sym_a, sym_b = sym_matches[0], sym_matches[1]
    sym_block_a = generated[sym_a.start() : sym_b.start()]
    sym_end = sym_matches[2].start() if len(sym_matches) > 2 else len(generated)
    sym_block_b = generated[sym_b.start() : sym_end]
    swapped_symbols_generated = (
        generated[: sym_a.start()]
        + sym_block_b
        + sym_block_a
        + generated[sym_end:]
    )
    cases["generated operation symbol order swapped"] = (
        snapshot,
        swapped_symbols_generated,
    )
    # Exact count door.
    cases["generated operation symbol count door"] = (snapshot, generated)
    overrides["generated operation symbol count door"] = {
        "expected_operation_symbols": _EXPECTED_OPERATION_SYMBOLS + 1
    }
    # Honest re-pin beside an intentional, reviewed reorder stays green --
    # the positive control that separates a real regenerate from a drift.
    honest_symbol_order = _operation_symbol_order_digest(
        operation_symbol_order_rows(swapped_symbols_generated)
    )
    cases["generated operation symbol order honestly re-pinned"] = (
        snapshot,
        swapped_symbols_generated,
    )
    overrides["generated operation symbol order honestly re-pinned"] = {
        "operation_symbol_order_digest": honest_symbol_order
    }
    # Negative control: deriving the literal from the artifact under guard
    # would make the door self-agreeing. Prove the plant is load-bearing.
    cases["generated operation symbol order with derived literal"] = (
        snapshot,
        swapped_symbols_generated,
    )
    overrides["generated operation symbol order with derived literal"] = {
        "operation_symbol_order_digest": _operation_symbol_order_digest(
            operation_symbol_order_rows(generated)
        )
    }

    failures_count = 0
    expect_clean = {
        "coordinated status order swap with both literals re-pinned",
        "generated operation symbol order honestly re-pinned",
    }
    for name, (snap_text, gen_text) in cases.items():
        found = failures(
            snapshot=snap_text,
            generated=gen_text,
            smoke=smoke,
            **overrides.get(name, {}),
        )
        if name in expect_clean:
            if found:
                print(f"SELF-TEST FAIL: {name!r} was rejected: {found}")
                failures_count += 1
            else:
                print(f"PASS self-test: {name!r} stays green")
        elif not found:
            print(f"SELF-TEST FAIL: {name!r} was NOT caught")
            failures_count += 1
        else:
            print(f"PASS self-test: {name!r} is caught -> {len(found)} failure(s)")
    # Positive control: a legitimate reviewed regenerate moves both halves
    # and BOTH digest literals. No door may object to that action.
    honest_client_digest = _client_response_surface_digest(
        client_response_surface_rows(_generated_operations(co_reverted_generated))
    )
    both_repinned = failures(
        snapshot=json.dumps(client_doc, indent=2),
        generated=co_reverted_generated,
        smoke=smoke,
        digest=honest_snapshot_digest,
        client_response_surface_digest=honest_client_digest,
    )
    if both_repinned:
        print(f"FAIL self-test: honest double re-pin was rejected: {both_repinned}")
        return 1
    print("PASS positive control: honest double re-pin is the reviewed regenerate")
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
        f"({_EXPECTED_RESPONSE_STATUS_ORDER_ROWS} response status order rows and "
        f"{_EXPECTED_RESPONSE_ENTRIES} declared responses and "
        f"{_EXPECTED_SUMMARY_OPERATIONS} operation summaries and "
        f"{_EXPECTED_REQUEST_BODY_BEARING_OPERATIONS} request bodies and "
        f"{_EXPECTED_RESPONSE_HEADERS} declared response header(s) and "
        f"{_EXPECTED_CLIENT_RESPONSE_ENTRIES} generated response entries and "
        f"{_EXPECTED_OPERATION_SYMBOLS} operation symbols in declaration order "
        f"pinned across {_EXPECTED_OPERATION_COUNT} operations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

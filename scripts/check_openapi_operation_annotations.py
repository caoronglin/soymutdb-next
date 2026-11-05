#!/usr/bin/env python3
"""Pin per-operation annotation prose to an independent literal fixed point.

Both ``openapi.json`` and ``src/generated/openapi.d.ts`` are exports of
``app.main:app``. Guards that compare them to each other prove
self-consistency, not truth. Every published operation carries ``summary``
and (optionally) ``description`` prose; ``openapi-typescript`` renders both
into the doc comment above each method in the generated ``paths`` interface.
A coordinated regenerate that rewrites one summary/description on *both*
halves moves both artifacts together, so none of the existing fixed points
can see it:

* ``_OPERATION_ID_DIGEST`` / ``_PARAMETER_DIGEST`` / ``_RESPONSE_SURFACE_DIGEST``
  pin identities and structural facts, not prose.
* ``openapi-document-metadata.golden.json`` freezes document-level ``info``
  and the tag catalog, not per-operation ``summary``/``description``.
* ``_BODY_PAIR_DIGEST`` / ``_INLINE_BODY_BASELINE`` see bodies only.
* ``_PINNED_ARTIFACTS`` is a provenance blob id: re-pinning both ids is the
  guard's own documented "one deliberate reviewed action" alongside a
  regenerate, so a co-revert that re-pins them stays green.

Decisive ablation on live bytes: rename one ``summary`` in the snapshot and
in the generated TS doc comment (byte-preserving, both halves agree), re-pin
the two blob ids as that guard instructs, and every wired OpenAPI guard stays
``rc=0`` with the whole contracts layer ``SMOKE PASS``. The generated
TypeScript doc comment silently changes -- a client-visible contract break
that nothing in the layer pins.

This guard reads committed bytes only (``json`` + ``re`` + stdlib): no Python
3.15, no API import, no wheel, no database, no workspace install. It pins:

* ``_ANNOTATION_DIGEST`` -- a hand-written sha256 over the canonical sorted
  ``(METHOD, path, operationId, summary, description, deprecated)`` tuple
  set, read from nowhere. Exported from both artifacts independently, so a
  co-revert of both halves still changes it;
* ``_EXPECTED_OPERATION_COUNT`` / ``_EXPECTED_DESCRIPTION_COUNT`` /
  ``_EXPECTED_DEPRECATED_COUNT`` -- exact count doors;
* three-way agreement: snapshot per-operation annotations == generated
  ``paths`` doc comments == generated ``operations`` interface symbols. A
  one-sided edit is named by method and path;
* the generated doc comment must render the summary as its first text line
  and the description under ``@description`` (both inline ``/** ... */`` and
  multi-line block shapes), and ``@deprecated`` exactly where the snapshot
  declares it.

A legitimate contract change must move the digest in the same commit as the
two artifacts and say why. Re-deriving the digest from the artifacts under
guard would make the pin self-referential, which is the whole failure this
file replaces. ``--self-test`` injects one-sided and coordinated drifts into
copies of the bytes and asserts each is caught; the clean tree must pass.

Usage:
    python3 scripts/check_openapi_operation_annotations.py
    python3 scripts/check_openapi_operation_annotations.py --self-test
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

# Reviewed, hand-written fixed point on the whole published annotation surface.
# sha256 of "\n".join(["soymutdb-operation-annotations/v1"] +
#   sorted(f"{method} {path} {operationId} {summary} {description} {deprecated}")).
# Regenerate with _digest() after an intentional contract change and update in
# the same commit, with a reason.
_ANNOTATION_DIGEST = (
    "db3cde4b0e275102840fc957e10ef1cab61f14d992875ed96974a141132aacaf"
)
_EXPECTED_OPERATION_COUNT = 268
_EXPECTED_DESCRIPTION_COUNT = 209
_EXPECTED_DEPRECATED_COUNT = 2

PATH_LINE = re.compile(r'^    "(/[^"]*)": \{$')
OP_REF = re.compile(
    r"^        (get|put|post|patch|delete|options|head|trace): "
    r'operations\["([^"]+)"\];$'
)
OP_DEF = re.compile(r"^    ([A-Za-z_][A-Za-z0-9_]*): \{$", re.MULTILINE)
INLINE_DOC = re.compile(r"^/\*\*\s*(.*?)\s*\*/$")


def _snapshot_rows(document: dict[str, Any]) -> list[tuple[str, str, str, str, str, str]]:
    """Canonical (METHOD, path, operationId, summary, description, deprecated)."""
    rows: list[tuple[str, str, str, str, str, str]] = []
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            rows.append(
                (
                    method.upper(),
                    path,
                    str(operation.get("operationId", "")),
                    str(operation.get("summary", "")),
                    str(operation.get("description", "")),
                    str(bool(operation.get("deprecated", False))),
                )
            )
    return rows


def _digest(rows: list[tuple[str, str, str, str, str, str]]) -> str:
    canonical = sorted(rows)
    blob = "\n".join(
        ["soymutdb-operation-annotations/v1"]
        + ["|".join(row) for row in canonical]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _generated_doc_blocks(
    generated: str,
) -> dict[tuple[str, str], tuple[str, list[str]]]:
    """(METHOD, path) -> (operations symbol, doc comment text lines).

    ``openapi-typescript`` emits either a one-line ``/** Summary */`` or a
    multi-line block whose first text line is the summary and whose
    ``@description``/``@deprecated`` lines carry the rest. Intervening
    ``?: never;`` rows and the ``parameters`` object do not reset the block.
    """
    out: dict[tuple[str, str], tuple[str, list[str]]] = {}
    in_paths = False
    path: str | None = None
    doc: list[str] = []
    for line in generated.splitlines():
        if line.startswith("export interface paths {"):
            in_paths = True
            continue
        if in_paths and line == "}":
            in_paths = False
            continue
        if not in_paths:
            continue
        match = PATH_LINE.match(line)
        if match:
            path = match.group(1)
            doc = []
            continue
        stripped = line.strip()
        inline = INLINE_DOC.match(stripped)
        if inline:
            doc.append("* " + inline.group(1))
            continue
        if stripped.startswith("*") or stripped.startswith("/**"):
            doc.append(stripped)
            continue
        match = OP_REF.match(line)
        if match and path is not None:
            out[(match.group(1).upper(), path)] = (match.group(2), list(doc))
            doc = []
            continue
        if (
            stripped.endswith("?: never;")
            or stripped.startswith("parameters:")
            or stripped in ("{", "};")
            or stripped.startswith(("query?:", "header?:", "path?:", "cookie?:"))
        ):
            continue
        doc = []
    return out


def _doc_text(lines: list[str]) -> list[str]:
    return [
        line.lstrip("* ").rstrip()
        for line in lines
        if line.startswith("*") and line.lstrip("* ").strip()
    ]


def _generated_symbols(generated: str) -> set[str]:
    """Operation symbols declared in the generated ``operations`` interface."""
    body = generated.split("export interface operations {", 1)
    if len(body) != 2:
        return set()
    return set(OP_DEF.findall(body[1]))


def _generated_annotations(
    document: dict[str, Any], generated: str
) -> dict[tuple[str, str], tuple[str, str, str]]:
    """(METHOD, path) -> (summary, description, deprecated) from TS doc blocks."""
    blocks = _generated_doc_blocks(generated)
    out: dict[tuple[str, str], tuple[str, str, str]] = {}
    for path, item in document.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in METHODS or not isinstance(operation, dict):
                continue
            key = (method.upper(), path)
            if key not in blocks:
                continue
            _symbol, lines = blocks[key]
            texts = _doc_text(lines)
            summary = texts[0] if texts else ""
            description = "\n".join(
                text[len("@description ") :]
                for text in texts
                if text.startswith("@description ")
            )
            deprecated = str(any(text.strip() == "@deprecated" for text in texts))
            out[key] = (summary, description, deprecated)
    return out


def _description_first_line(description: str) -> str:
    return description.splitlines()[0] if description else ""


def failures(
    document: dict[str, Any], generated: str, smoke: str, digest: str | None = None
) -> list[str]:
    rows = _snapshot_rows(document)
    found: list[str] = []
    pinned = _ANNOTATION_DIGEST if digest is None else digest

    if len(rows) != _EXPECTED_OPERATION_COUNT:
        found.append(
            f"operation count drifted: expected {_EXPECTED_OPERATION_COUNT}, got {len(rows)}"
        )
    described = sum(1 for row in rows if row[4])
    if described != _EXPECTED_DESCRIPTION_COUNT:
        found.append(
            f"description count drifted: expected {_EXPECTED_DESCRIPTION_COUNT}, "
            f"got {described}"
        )
    deprecated = sum(1 for row in rows if row[5] == "True")
    if deprecated != _EXPECTED_DEPRECATED_COUNT:
        found.append(
            f"deprecated count drifted: expected {_EXPECTED_DEPRECATED_COUNT}, "
            f"got {deprecated}"
        )

    actual_digest = _digest(rows)
    if actual_digest != pinned:
        found.append(
            f"published operation annotations drifted: _ANNOTATION_DIGEST pins "
            f"{pinned}, committed bytes hash to {actual_digest}"
        )

    identities = [(row[1], row[2]) for row in rows]
    if len(set(identities)) != len(identities):
        found.append("duplicate (path, operationId) pair in the snapshot")
    operation_ids = [row[2] for row in rows]
    if len(set(operation_ids)) != len(operation_ids):
        found.append("duplicate operationId in the snapshot")

    # Three-way agreement: snapshot annotations, generated doc comments and
    # generated operations symbols must all describe the same operation set.
    blocks = _generated_doc_blocks(generated)
    snapshot_keys = {(row[0], row[1]) for row in rows}
    for key in sorted(snapshot_keys - set(blocks)):
        found.append(f"{key[0]} {key[1]} has no generated paths doc block")
    for key in sorted(set(blocks) - snapshot_keys):
        found.append(f"{key[0]} {key[1]} has a generated doc block but no snapshot operation")

    rendered = _generated_annotations(document, generated)
    for row in sorted(rows):
        method, path, operation_id, summary, description, is_deprecated = row
        key = (method, path)
        if key not in rendered:
            continue
        got_summary, got_description, got_deprecated = rendered[key]
        if got_summary != summary:
            found.append(
                f"{method} {path} summary disagrees: snapshot {summary!r}, "
                f"generated doc comment {got_summary!r}"
            )
        if _description_first_line(description) != _description_first_line(got_description):
            found.append(
                f"{method} {path} description disagrees: snapshot "
                f"{_description_first_line(description)!r}, generated "
                f"{_description_first_line(got_description)!r}"
            )
        if got_deprecated != is_deprecated:
            found.append(
                f"{method} {path} deprecated flag disagrees: snapshot {is_deprecated}, "
                f"generated @deprecated {got_deprecated}"
            )

    symbols = _generated_symbols(generated)
    for row in rows:
        if row[2] and row[2] not in symbols:
            found.append(f"operationId {row[2]!r} has no generated operations symbol")
    for key in sorted(set(blocks)):
        symbol, _lines = blocks[key]
        if symbol not in symbols:
            found.append(f"generated paths reference {symbol!r} is not declared")

    # Wiring: the guard's own --self-test must be a standalone call in the
    # contracts layer, or a vacuous guard can never redden the layer. A
    # commented-out line still contains the path but never runs, so require
    # the active command shape from the start of the line.
    marker = "smoke_contracts() {"
    if marker not in smoke:
        found.append("smoke.sh no longer defines smoke_contracts()")
    else:
        body = smoke.split(marker, 1)[1].split("\n}\n", 1)[0]
        active = re.compile(
            r'^[ \t]*"\$\{PYTHON_BIN\}"\s+scripts/'
            + re.escape(SELF)
            + r"\s+--self-test\s*\|\|\s*rc=\$\?",
            re.MULTILINE,
        )
        if not active.search(body):
            found.append(f"{SELF} --self-test is not wired into the contracts layer")
    return found


def check() -> list[str]:
    try:
        document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        generated = GENERATED.read_text(encoding="utf-8")
        smoke = SMOKE.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [f"could not read committed bytes: {exc}"]
    return failures(document, generated, smoke)


def self_test() -> int:
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    generated = GENERATED.read_text(encoding="utf-8")
    smoke = SMOKE.read_text(encoding="utf-8")
    clean = failures(document, generated, smoke)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    cases: list[tuple[str, Any, Any, Any]] = []
    target = "/api/v1/health/live"
    summary = "Liveness"
    description = document["paths"][target]["get"]["description"]

    def plant_snapshot_summary(value: str) -> dict[str, Any]:
        copy_doc = copy.deepcopy(document)
        copy_doc["paths"][target]["get"]["summary"] = value
        return copy_doc, generated, smoke

    def plant_generated_summary(value: str) -> tuple[dict[str, Any], str, str]:
        return document, generated.replace(
            f"         * {summary}\n", f"         * {value}\n", 1
        ), smoke

    def plant_both(value: str) -> tuple[dict[str, Any], str, str]:
        copy_doc = copy.deepcopy(document)
        copy_doc["paths"][target]["get"]["summary"] = value
        return (
            copy_doc,
            generated.replace(f"         * {summary}\n", f"         * {value}\n", 1),
            smoke,
        )

    cases.append(("one-sided snapshot summary drift", *plant_snapshot_summary("Liveness v2")))
    cases.append(("one-sided generated summary drift", *plant_generated_summary("Liveness v2")))
    cases.append(("coordinated summary drift", *plant_both("Liveness v2")))

    desc_copy = copy.deepcopy(document)
    desc_copy["paths"][target]["get"]["description"] = description + " (changed)"
    cases.append(("one-sided description drift", desc_copy, generated, smoke))

    dep_copy = copy.deepcopy(document)
    dep_copy["paths"][target]["get"]["deprecated"] = True
    cases.append(("one-sided deprecated drift", dep_copy, generated, smoke))

    drop_copy = copy.deepcopy(document)
    del drop_copy["paths"][target]["get"]["summary"]
    cases.append(("dropped summary", drop_copy, generated, smoke))

    rewired = smoke.replace(f"{SELF} --self-test", f"# {SELF} --self-test", 1)
    cases.append(("dropped self-test wire", document, generated, rewired))

    failed = 0
    for name, doc, gen, smk in cases:
        problems = failures(doc, gen, smk)
        if problems:
            print(f"PASS self-test: {name} is caught -> {len(problems)} failure(s)")
        else:
            failed += 1
            print(f"FAIL self-test: {name} was NOT caught")
    print(f"self-test: {len(cases)} cases, {failed} failure(s)")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="plant drifts in copies of the bytes"
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    problems = check()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print(
        "openapi-operation-annotations: OK "
        f"({_EXPECTED_OPERATION_COUNT} published operation annotations pinned)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

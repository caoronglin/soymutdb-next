#!/usr/bin/env python3
"""Pin published component-schema ``description`` prose to an independent literal.

``openapi.json`` publishes 257 ``description`` strings on component-schema
property nodes across 169 schemas. ``openapi-typescript`` renders each one as
an ``@description`` line in the generated ``components["schemas"]`` JSDoc, so
the prose is client-visible: it is what an IDE shows a caller hovering a field.
Multi-line descriptions become ``@description <first line>`` plus indented
continuation lines; the generator also emits exactly one synthetic
``@description discriminator enum property added by openapi-typescript``.

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
  against the pins, not against the snapshot under guard.

A legitimate prose change must move the digest in the same commit as both
artifacts and say why. Re-deriving the digest from the artifact under guard
would make the pin self-referential.

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
        rows_ = rows(document)
        client = client_descriptions(generated)
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
        f"descriptions pinned across {_EXPECTED_SCHEMAS} schemas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

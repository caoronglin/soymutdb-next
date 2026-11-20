#!/usr/bin/env python3
"""Catch a hand-edited contract snapshot before the backend export does.

``check-contract.sh`` compares a fresh export against the committed snapshot,
so a snapshot nobody could have exported is reported as *backend* drift. The
message names a schema the author did edit, which sends the next reader to look
at a backend that is fine: in #63 a field's ``title`` had been deleted from
``AlleleFreqVariant``/``LdVariant`` by hand, and CI reported both as changed
schemas.

Two invariants hold across the whole committed document and cost nothing to
check -- no backend, no database, no pydantic:

* every property pydantic describes also carries its ``title``; and
* every property is spelled in the export's key order (``_title_last``), so a
  re-ordered one cannot masquerade as a change either.

Usage: check_snapshot_spelling.py <committed openapi.json>
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "export_contract.py"

#: Keys the export prints before everything else (see ``_title_last``).
_ORDERED_KEYS = ("anyOf", "oneOf", "allOf", "$ref", "type", "items", "enum")


def _export_order(prop: dict) -> list[str]:
    ordered = [key for key in _ORDERED_KEYS if key in prop]
    ordered += [k for k in prop if k not in ordered and k != "title"]
    if "title" in prop and "$ref" not in prop:
        ordered.append("title")
    return ordered


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    path = Path(argv[1])
    raw = path.read_text(encoding="utf-8")
    document = json.loads(raw)

    # The real export is serialized exactly this way; a snapshot that does not
    # round-trip it differs in whitespace alone and can never match.
    if json.dumps(document, indent=2) != raw:
        print(f"CONTRACT SNAPSHOT: {path} is not the output of the export writer.")
        print("  Run: pnpm --filter @soymutdb/api-client generate:api-client")
        return 1

    problems: list[str] = []

    def visit(node, path: str) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for name, prop in properties.items():
                    if not isinstance(prop, dict):
                        continue
                    where = f"{path}.{name}"
                    if "description" in prop and "title" not in prop:
                        problems.append(
                            f"  {where}: has a description but no title"
                        )
                    order = _export_order(prop)
                    if list(prop) != order:
                        problems.append(
                            f"  {where}: key order {list(prop)} != export {order}"
                        )
            for key, value in node.items():
                visit(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}[{index}]")

    visit(document.get("components", {}).get("schemas", {}), "schemas")

    if problems:
        print("CONTRACT SNAPSHOT: hand-edited, not what the backend exports.")
        print(
            "  CI compares a fresh export against this file, so it would report\n"
            "  these as backend drift the backend never made:"
        )
        for problem in problems[:20]:
            print(problem)
        if len(problems) > 20:
            print(f"  ... ({len(problems) - 20} more)")
        print("Run: pnpm --filter @soymutdb/api-client generate:api-client")
        return 1

    print("OK: contract snapshot is spelled the way the export writes it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

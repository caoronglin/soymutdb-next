#!/usr/bin/env python3
"""Name what moved between two OpenAPI documents.

``check-contract.sh`` compares a freshly exported document with the committed
snapshot, and both are single-line JSON exports. Reporting that comparison as a
plain ``diff`` prints the entire API description as line 1 and nothing about
the actual change, which leaves the gate with one message -- "CONTRACT DEBT" --
for every possible cause.

This prints schema and path *names* instead: the schemas whose definition
changed and the paths added or removed. It is advisory output (the caller keeps
its own exit code), so a document it cannot read degrades to no summary rather
than to a second, less useful failure.

Usage: summarize_contract_drift.py <committed.json> <fresh.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: Enough to recognize the change without turning a build log into a diff.
LIMIT = 20


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    return document.get("components", {}).get("schemas", {})


def _paths(document: dict[str, Any]) -> dict[str, Any]:
    return document.get("paths", {})


def _changed_schemas(committed: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    before, after = _schemas(committed), _schemas(fresh)
    return sorted(
        name
        for name in set(before) | set(after)
        if json.dumps(before.get(name), sort_keys=True)
        != json.dumps(after.get(name), sort_keys=True)
    )


def _print_names(label: str, names: list[str]) -> None:
    if not names:
        return
    listed = ", ".join(names[:LIMIT])
    if len(names) > LIMIT:
        listed += f", ... ({len(names) - LIMIT} more)"
    print(f"  {label}: {listed}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        committed = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        fresh = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"  (could not compare the documents: {error})")
        return 0

    _print_names("changed schemas", _changed_schemas(committed, fresh))
    before, after = _paths(committed), _paths(fresh)
    _print_names("added paths", sorted(set(after) - set(before)))
    _print_names("removed paths", sorted(set(before) - set(after)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

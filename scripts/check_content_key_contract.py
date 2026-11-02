#!/usr/bin/env python3
"""Content-key contract: every portal `get("<key>")` must be a registered setting.

The portal's backend-editable copy runs through
``useSiteContent().get("<key>", <i18n fallback>)``. A key that is read that way
but not registered in ``apps/api/app/core/settings_registry.py`` can never be
stored or overridden, so the read silently falls back to i18n forever and the
Admin console has no field for it. A key that is registered but never read is
an admin-editable setting that does nothing.

This guard checks the direction that can be decided statically and without
false positives:

    every literal get("<key>") consumer must be registered.

The reverse direction (registered but unread) is not gated here: consumers are
partly dynamic (`get(`tool.${key}.label`)`) and a static "no literal found"
check would flag live keys. Use the report mode (`--report`) to review it.

Usage:
    python3 scripts/check_content_key_contract.py            # gate
    python3 scripts/check_content_key_contract.py --report   # print drift, exit 0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "apps/api/app/core/settings_registry.py"
PORTAL_ROOT = REPO_ROOT / "apps/web/src"

# The portal helper is invoked bare: `get("key", fallback)`. Property access
# (`di.get("api")`, `map.get("x")`) is not part of the content contract.
GET_CALL = re.compile(r'(?<![.\w])get\(\s*["\']([A-Za-z][A-Za-z0-9_.]*)["\']')
CONTENT_DEFINITION = re.compile(r'_definition\(\s*"content"\s*,\s*"([^"]+)"')
SKIP_PARTS = {".umi", ".umi-production", ".umi-test", "node_modules", "dist"}
SKIP_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")


def registered_content_keys(registry_text: str) -> set[str]:
    return set(CONTENT_DEFINITION.findall(registry_text))


def portal_get_keys(portal_root: Path) -> dict[str, str]:
    """Map each literal get("key") to the first source file that reads it."""
    found: dict[str, str] = {}
    for path in sorted(portal_root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name.endswith(SKIP_SUFFIXES):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in GET_CALL.finditer(text):
            found.setdefault(match.group(1), str(path.relative_to(REPO_ROOT)))
    return found


def drift(registered: set[str], consumed: dict[str, str]) -> tuple[list[str], list[str]]:
    unregistered = sorted(set(consumed) - registered)
    unread = sorted(registered - set(consumed))
    return unregistered, unread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print both drift directions (informational) and always exit 0",
    )
    args = parser.parse_args(argv)

    registered = registered_content_keys(REGISTRY.read_text(encoding="utf-8"))
    consumed = portal_get_keys(PORTAL_ROOT)
    unregistered, unread = drift(registered, consumed)

    if args.report:
        print(f"registered content keys: {len(registered)}")
        print(f"literal portal get() keys: {len(consumed)}")
        print(f"consumed but unregistered ({len(unregistered)}):")
        for key in unregistered:
            print(f"  {key} <- {consumed[key]}")
        print(f"registered but no literal consumer ({len(unread)}):")
        for key in unread:
            print(f"  {key}")
        return 0

    if unregistered:
        print(
            "content-key contract failed: the portal reads keys that are not "
            "registered in apps/api/app/core/settings_registry.py, so they can "
            "never be stored or overridden:",
            file=sys.stderr,
        )
        for key in unregistered:
            print(f"  {key} <- {consumed[key]}", file=sys.stderr)
        return 1

    print(
        f"content-key contract OK ({len(consumed)} literal portal get() keys, "
        f"{len(registered)} registered content keys)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

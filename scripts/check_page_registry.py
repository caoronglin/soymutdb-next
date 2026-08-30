#!/usr/bin/env python3
"""Fail CI when the shared Page Builder contract drifts from its backend registry."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "apps/api/app/page_builder/registry.py"
SHARED = ROOT / "packages/shared/src/page-builder.ts"


def quoted_values(source: str, declaration: str) -> set[str]:
    match = re.search(declaration, source, re.DOTALL)
    if not match:
        raise ValueError(f"could not locate {declaration!r}")
    return set(re.findall(r'"([a-z0-9_]+)"', match.group(1)))


def main() -> int:
    registry_source = REGISTRY.read_text(encoding="utf-8")
    shared_source = SHARED.read_text(encoding="utf-8")
    backend = set(re.findall(r'ComponentDefinition\(\s*"([a-z0-9_]+)"', registry_source))
    shared = quoted_values(shared_source, r"PAGE_COMPONENT_TYPES\s*=\s*\[(.*?)\]\s+as const")
    backend_layouts = quoted_values(registry_source, r"_LAYOUT_CONTAINERS\s*=\s*\{(.*?)\}")
    shared_layouts = quoted_values(shared_source, r"PAGE_LAYOUT_CONTAINERS\s*=\s*\[(.*?)\]\s+as const")
    failures: list[str] = []
    for label, left, right in (("component keys", backend, shared), ("layout containers", backend_layouts, shared_layouts)):
        if left != right:
            failures.append(
                label + " differ\n  backend-only: " + repr(sorted(left - right))
                + "\n  shared-only: " + repr(sorted(right - left))
            )
    if failures:
        print("Page Builder registry contract drift detected:\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print(f"Page Builder registry contract is synchronized ({len(backend)} component keys).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

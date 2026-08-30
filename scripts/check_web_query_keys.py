#!/usr/bin/env python3
"""Keep shared Web assembly query keys from drifting across route modules."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CONSUMERS = (
    "apps/web/src/routes/search/location.tsx",
    "apps/web/src/routes/search/primer.tsx",
    "apps/web/src/routes/search/gbrowse.tsx",
    "apps/web/src/routes/search/genes.tsx",
    "apps/web/src/routes/tools/seqfetch.tsx",
)


def main() -> int:
    failures: list[str] = []
    for relative_path in CONSUMERS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        if "queryKeys.assemblies.all()" not in content:
            failures.append(f"{relative_path}: must use queryKeys.assemblies.all()")
        if "queryKey: [\"assemblies\"]" in content:
            failures.append(f"{relative_path}: contains a handwritten assemblies query key")

    if failures:
        print("Web query-key architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"Web query-key architecture check passed ({len(CONSUMERS)} assembly consumers).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

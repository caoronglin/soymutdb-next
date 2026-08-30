#!/usr/bin/env python3
"""Guard the query-key and URL-state boundary of migrated Admin content routes."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PAGES_TAB = ROOT / "apps/admin/src/routes/content/pages-tab.tsx"


def main() -> int:
    content = PAGES_TAB.read_text(encoding="utf-8")
    required = (
        "import { contentKeys } from \"./query-keys\";",
        "import { parseContentPageSearch, serializeContentPageSearch } from \"./search\";",
        "useSearch({ strict: false })",
        "queryKey: contentKeys.pages(",
        "queryClient.invalidateQueries({ queryKey: contentKeys.all })",
        "serializeContentPageSearch(next)",
    )
    failures = [token for token in required if token not in content]
    if "queryKey: [\"admin-pages\"" in content:
        failures.append("handwritten admin-pages query key")

    if failures:
        print("Admin content architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - missing or forbidden: {failure}", file=sys.stderr)
        return 1
    print("Admin content architecture check passed (query keys and URL state).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

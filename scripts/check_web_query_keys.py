#!/usr/bin/env python3
"""Keep the portal's assembly/reference reads on one cache identity.

The Vue portal gets its query keys from typed ``queryOptions`` factories in
``apps/web/src/lib/query-options.ts``. That indirection is what keeps a key and
its request in the same object, so a view cannot request assemblies with one
cache identity and read them with another.

Two rules are enforced over the portal's view modules:

1. A view that reads assemblies must call the factory
   (``assembliesQueryOptions()``), never build its own assemblies key.
2. No view may reference ``queryKeys.assemblies`` directly — the neutral key
   builder is the factory layer's job, and a second call site is how the React
   portal's keys drifted before this gate existed.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS_DIR = ROOT / "apps" / "web" / "src" / "views"
FACTORY = "assembliesQueryOptions()"
BANNED_KEY_RE = re.compile(r"queryKey:\s*\[\s*[\"']assemblies")
BANNED_NEUTRAL_KEYS_RE = re.compile(r"queryKeys\.assemblies")


def view_files() -> list[Path]:
    return sorted(path for path in VIEWS_DIR.glob("*.vue") if path.is_file())


def main() -> int:
    failures: list[str] = []
    consumers: list[str] = []

    for path in view_files():
        content = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        reads_assemblies = "getAssemblies" in content or "assembliesQueryOptions" in content

        if reads_assemblies:
            consumers.append(relative)
            if FACTORY not in content:
                failures.append(
                    f"{relative}: reads assemblies but does not call {FACTORY}"
                )
        if BANNED_KEY_RE.search(content):
            failures.append(f"{relative}: contains a handwritten assemblies query key")
        if BANNED_NEUTRAL_KEYS_RE.search(content):
            failures.append(
                f"{relative}: references queryKeys.assemblies directly — go through the "
                "queryOptions factory in apps/web/src/lib/query-options.ts"
            )

    if failures:
        print("Portal query-key architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(
        f"Portal query-key architecture check passed ({len(consumers)} assembly consumers)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

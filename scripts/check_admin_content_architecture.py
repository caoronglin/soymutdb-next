#!/usr/bin/env python3
"""Guard the admin console's session and transport boundary.

The previous version of this check pinned the React admin's content-pages tab to
its query-key helpers. That tab is retired with the page builder (ADR-0009), and
the console is Vue, so the check now guards the two properties that outlive any
particular page:

1. **One transport.** Every request goes through `@soymutdb/api-client` (or this
   app's `lib/api.ts`, which wraps it). A view that calls `fetch` directly would
   skip the CSRF attachment, the refresh-on-401 coordination and the release
   header, and it would do so silently.
2. **One session store.** The access token lives in module memory. A view that
   reads or writes `localStorage`/`sessionStorage` for auth is reintroducing the
   persisted-token design the console deliberately does not use.

Both are decided by scanning source, so a new page cannot opt out by accident.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_SRC = ROOT / "apps" / "admin" / "src"

# A direct network call that bypasses the shared client. `adminApi` and the
# api-client functions are the only sanctioned entry points.
DIRECT_FETCH_RE = re.compile(r"\bfetch\s*\(")
STORAGE_RE = re.compile(r"\b(?:local|session)Storage\b")

# Comments are stripped before scanning: the header of `lib/auth.ts` explains why
# the token is *not* persisted, and a guard that flags the explanation of its own
# rule is a guard that gets weakened on the first false positive.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    return _LINE_COMMENT_RE.sub("", text)


def sources() -> list[Path]:
    return sorted(
        path
        for path in ADMIN_SRC.rglob("*")
        if path.suffix in {".ts", ".vue"} and path.is_file()
    )


def main() -> int:
    failures: list[str] = []

    for path in sources():
        text = strip_comments(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()

        if DIRECT_FETCH_RE.search(text):
            failures.append(
                f"{relative}: calls fetch() directly — go through @soymutdb/api-client "
                "so CSRF, refresh-on-401 and the release header stay attached"
            )
        if STORAGE_RE.search(text):
            failures.append(
                f"{relative}: touches web storage — the admin access token is "
                "module-memory only (see src/lib/auth.ts)"
            )

    if failures:
        print("Admin transport/session architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"Admin transport/session architecture check passed "
        f"({len(sources())} source file(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

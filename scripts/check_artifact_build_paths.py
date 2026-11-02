#!/usr/bin/env python3
"""Fail when a published artifact leaks a build-machine path.

Webpack can inline `import.meta.url` (and similar build-time URLs) as an
absolute `file:///…` path when bundling a dependency that has a Node-only
branch. pdf.js did exactly that through its Node canvas factory, so the PDF
async chunk shipped `file:///home/<builder>/…/node_modules/pdfjs-dist/…`.

That is not a secret, but it discloses the build environment and is never
needed at runtime. This guard scans the emitted artifacts for absolute
host paths: the repository root, `/mnt/…`, `/home/<user>/…`, `/Users/…`,
`C:\\…` and `file:///` URLs.

Usage: python3 scripts/check_artifact_build_paths.py [dist-dir ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    REPO_ROOT / "apps/web/dist/external",
    REPO_ROOT / "apps/web/dist/internal",
    REPO_ROOT / "apps/admin/dist",
)
SCANNED_SUFFIXES = {".js", ".mjs", ".cjs", ".css", ".html", ".json", ".map"}

# Patterns are checked in addition to the literal repository root, because CI
# builds in a different absolute path than a developer workstation.
HOST_PATH_PATTERNS = (
    re.compile(r"file:///(?:mnt|home|Users|root|tmp)/"),
    re.compile(r"/mnt/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\?(?:Users|builds|workspace)\\\\"),
)


def find_leaks(root: Path) -> list[tuple[Path, str]]:
    leaks: list[tuple[Path, str]] = []
    if not root.exists():
        return leaks
    root_text = str(REPO_ROOT)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if path.stat().st_size > 20 * 1024 * 1024:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if root_text in text:
            leaks.append((path, root_text))
            continue
        for pattern in HOST_PATH_PATTERNS:
            match = pattern.search(text)
            if match:
                leaks.append((path, match.group(0)))
                break
    return leaks


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv] if argv else list(DEFAULT_TARGETS)
    found: list[tuple[Path, str]] = []
    for target in targets:
        found.extend(find_leaks(target))

    if found:
        print(
            "artifact build-path guard failed: published files contain "
            "absolute host paths (build environment is disclosed and the "
            "reference can never resolve at runtime):",
            file=sys.stderr,
        )
        for path, needle in found[:20]:
            try:
                shown = path.relative_to(REPO_ROOT)
            except ValueError:
                shown = path
            print(f"  {shown}: {needle}", file=sys.stderr)
        return 1

    scanned = ", ".join(str(t) for t in targets)
    print(f"artifact build-path guard: OK ({scanned})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

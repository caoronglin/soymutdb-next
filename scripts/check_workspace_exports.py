#!/usr/bin/env python3
"""Workspace source that a clean clone cannot rebuild.

Two failure modes are checked, both invisible on the machine that authored the
change and fatal on the first clean clone:

**A. An ignored source tree.** `.gitignore` line 16 is `build/`, which matches
a directory named `build` at *any* depth. It silently excluded
`packages/shared/src/build/`, the shared CSP composer and inline-script hasher
that `apps/web/scripts/finalize-csp.ts`,
`apps/jbrowse/scripts/inject-headers-origins.ts` and
`apps/web/src/lib/deployment.ts` all import. The files were on disk, so every
local build passed; `git ls-files` had never seen them, so a fresh clone had no
source for `@soymutdb/shared/build/*` and could not build the portal or JBrowse
at all. This is the same failure class the `.gitignore` already documents for
`.cnb/env/` being swallowed by the `env/` pattern.

**B. A subpath export that does not resolve.** A `package.json` `exports` map
may name a target that is missing, misspelled, or (as in A) ignored. Bundlers
resolve the same way, so the breakage surfaces at the furthest possible point
from the edit.

Both checks are decided by git's own ignore machinery (`git check-ignore`) and
index (`git ls-files`), not by a re-implementation, so a rule change cannot
make this guard disagree with what a clone actually receives. Staged files
count as tracked, so the guard is usable in a pre-commit hook and inside the
commit it is meant to protect.

Usage: python3 scripts/check_workspace_exports.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Source extensions worth protecting. Build outputs are excluded by the check
# itself (they are ignored on purpose), so this list describes authorable
# source, not compiled artefacts.
SOURCE_SUFFIXES = (".ts", ".tsx", ".py", ".css")

# Package roots whose src/ trees are authored by hand.
SOURCE_GLOBS = ("packages/*/src", "apps/*/src")

# `.gitignore` may legitimately exclude generated files that live beside
# source. Anything listed here must carry a reason.
IGNORED_SOURCE_ALLOWLIST: dict[str, str] = {}


def _git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def _workspace_packages() -> list[Path]:
    """Every package.json that pnpm-workspace.yaml's globs select."""
    manifests: list[Path] = []
    workspace = ROOT / "pnpm-workspace.yaml"
    if not workspace.is_file():
        return manifests
    patterns = []
    for line in workspace.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*-\s*['\"]?([^'\"#]+?)['\"]?\s*$", line)
        if match:
            patterns.append(match.group(1).strip())
    for pattern in patterns:
        for directory in sorted(ROOT.glob(pattern)):
            manifest = directory / "package.json"
            if manifest.is_file():
                manifests.append(manifest)
    return manifests


def _export_targets(manifest: Path) -> list[tuple[str, str]]:
    """(subpath, relative target) for every file-valued export condition."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    exports = data.get("exports")
    if not isinstance(exports, dict):
        return []
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for subpath, value in exports.items():
        candidates: list[str] = []
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            for condition in ("types", "import", "default", "require"):
                target = value.get(condition)
                if isinstance(target, str):
                    candidates.append(target)
        for target in candidates:
            # `types` and `import` normally name the same file; report the
            # subpath once per distinct target rather than once per condition.
            if target.startswith("./") and (subpath, target) not in seen:
                seen.add((subpath, target))
                found.append((subpath, target[2:]))
    return found


def check_ignored_source(errors: list[str]) -> int:
    """Report authorable source under a package src/ tree that git ignores."""
    reported = 0
    for glob in SOURCE_GLOBS:
        for root in sorted(ROOT.glob(glob)):
            for path in sorted(root.rglob("*")):
                # Umi writes its generated cache (`src/.umi`, `src/.umi-production`)
                # inside the source tree. Those are build output that `.gitignore`
                # is right to exclude, so they are not "authorable source" and must
                # not be reported. Skipping by path segment keeps the check honest
                # for real source files instead of allow-listing dozens of hashes.
                if any(part.startswith(".umi") for part in path.relative_to(root).parts):
                    continue
                if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                    continue
                rel = path.relative_to(ROOT).as_posix()
                if rel in IGNORED_SOURCE_ALLOWLIST:
                    continue
                code, out = _git("check-ignore", "-v", rel)
                if code == 0 and out:
                    rule = out.split(":", 1)[0]
                    errors.append(
                        f"{rel} is authorable source but git ignores it "
                        f"({out.strip()}). A clean clone will not have it. "
                        f"Re-include it in .gitignore (see the .cnb/env/ "
                        f"precedent) or move it out of the ignored pattern."
                    )
                    reported += 1
    return reported


def check_export_targets(errors: list[str]) -> int:
    """Report export targets that are missing or untracked."""
    reported = 0
    for manifest in _workspace_packages():
        name = manifest.parent.relative_to(ROOT).as_posix()
        for subpath, target in _export_targets(manifest):
            resolved = (manifest.parent / target).resolve()
            rel = resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else target
            if not resolved.exists():
                errors.append(
                    f"{name}: export '{subpath}' -> {target} does not exist"
                )
                reported += 1
                continue
            code, _ = _git("ls-files", "--cached", "--error-unmatch", rel)
            if code != 0:
                errors.append(
                    f"{name}: export '{subpath}' -> {target} exists on disk but "
                    f"is not in the git index; a clean clone cannot resolve it"
                )
                reported += 1
    return reported


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    errors: list[str] = []
    ignored = check_ignored_source(errors)
    exports = check_export_targets(errors)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "ignored_source": ignored,
                    "unresolved_exports": exports,
                    "errors": errors,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(
            f"workspace exports: {ignored} ignored source file(s), "
            f"{exports} unresolved export(s)"
        )
        print("workspace exports: OK" if not errors else "workspace exports: FAILED")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

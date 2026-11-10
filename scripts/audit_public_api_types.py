#!/usr/bin/env python3
"""Audit the public type surface of every workspace package.

The `knip` `types` category answers "is this exported type consumed anywhere?".
It cannot answer the two questions that decide whether a package's public
surface is *usable*:

1. does an exported signature expose `any` / a bare `object`, which erases the
   contract at the boundary (the caller can no longer tell what is expected)?
2. does a package export a type that nothing outside its own file imports, i.e.
   dead weight in the published surface?

Both are reported here, from the source, so the audit is reproducible and does
not depend on a tool's internal heuristics.

    python3 scripts/audit_public_api_types.py            # report
    python3 scripts/audit_public_api_types.py --strict   # exit 1 on any finding

The entry point for each package is the `types`/`import` target of its
`package.json` `exports["."]` — not a guessed `src/index.ts` — so a package that
re-exports from another file is audited where consumers actually enter.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: An exported declaration that mentions one of these in its signature has given
#: up its contract at the package boundary.
UNSAFE_TOKENS = ("any", "unknown", "object")

#: `export function f(...)`, `export const x: T`, `export type T = ...`, and the
#: re-export forms. One regex per shape keeps the report explainable.
DECLARATIONS = (
    re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE),
    re.compile(r"^export\s+const\s+(\w+)", re.MULTILINE),
    re.compile(r"^export\s+(?:type|interface)\s+(\w+)", re.MULTILINE),
    re.compile(r"^export\s+(?:class|enum)\s+(\w+)", re.MULTILINE),
)


@dataclass
class PackageAudit:
    name: str
    entry: Path | None
    exported: int = 0
    unsafe: list[str] = field(default_factory=list)
    unconsumed_types: list[str] = field(default_factory=list)
    error: str | None = None


def _entry_point(package_dir: Path) -> Path | None:
    manifest_path = package_dir / "package.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = manifest.get("exports", {}).get(".")
    if isinstance(target, dict):
        target = target.get("types") or target.get("import") or target.get("default")
    if not isinstance(target, str):
        return None
    resolved = (package_dir / target).resolve()
    return resolved if resolved.is_file() else None


def _exported_names(source: str) -> set[str]:
    names: set[str] = set()
    for pattern in DECLARATIONS:
        names.update(pattern.findall(source))
    # `export { a, b }` and `export type { a, b }` re-exports.
    for block in re.finditer(r"^export\s+(?:type\s+)?\{([^}]*)\}", source, re.MULTILINE):
        for item in block.group(1).split(","):
            name = item.split(" as ")[-1].strip()
            if name:
                names.add(name)
    return names


def _declaration_text(source: str, name: str) -> str:
    """The declaration of *name*, up to the end of its signature.

    Deliberately coarse: the audit is about which tokens appear in a public
    signature, and a conservative window avoids re-implementing a TS parser.
    """
    for match in re.finditer(
        rf"^export\s+(?:async\s+)?(?:function|const|type|interface|class|enum)\s+{re.escape(name)}\b",
        source,
        re.MULTILINE,
    ):
        start = match.start()
        end = source.find("\n\n", start)
        return source[start : end if end != -1 else start + 1200]
    return ""


def _word_tokens(text: str) -> set[str]:
    # Strip comments so a doc sentence ("never returns any rows") is not a hit.
    without_comments = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    without_comments = re.sub(r"//[^\n]*", "", without_comments)
    return set(re.findall(r"[A-Za-z_$][\w$]*", without_comments))


def _consumers(name: str, *, origin: Path, root: Path) -> int:
    """How many files outside *origin* mention *name* as an identifier."""
    hits = 0
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    for path in root.rglob("*.ts*"):
        if "node_modules" in path.parts or path == origin or path.name.endswith(".test.ts"):
            continue
        if path.name.endswith(".test.tsx"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern.search(text):
            hits += 1
            if hits > 0:
                return hits
    return hits


def audit() -> list[PackageAudit]:
    results: list[PackageAudit] = []
    for package_dir in sorted((ROOT / "packages").iterdir()):
        if not package_dir.is_dir():
            continue
        manifest_path = package_dir / "package.json"
        if not manifest_path.is_file():
            continue
        name = json.loads(manifest_path.read_text(encoding="utf-8")).get("name", package_dir.name)
        entry = _entry_point(package_dir)
        result = PackageAudit(name=name, entry=entry)
        if entry is None:
            result.error = "no resolvable exports['.'] entry point"
            results.append(result)
            continue

        source = entry.read_text(encoding="utf-8")
        names = _exported_names(source)
        result.exported = len(names)
        for exported in sorted(names):
            declaration = _declaration_text(source, exported)
            tokens = _word_tokens(declaration)
            offenders = sorted(tokens & set(UNSAFE_TOKENS))
            if offenders:
                result.unsafe.append(f"{exported}: {', '.join(offenders)}")
            # Only *type-like* exports are candidates for "unconsumed": a
            # function or constant is exercised at runtime and knip already
            # reports unused ones.
            is_type = re.search(
                rf"^export\s+(?:type|interface)\s+{re.escape(exported)}\b", source, re.MULTILINE
            )
            if is_type and _consumers(exported, origin=entry, root=ROOT / "packages") == 0:
                result.unconsumed_types.append(exported)
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any finding is reported",
    )
    args = parser.parse_args(argv)

    results = audit()
    findings = 0
    print(f"{'package':32s} {'exports':>7s}  {'unsafe':>6s}  {'dead types':>10s}")
    print("-" * 68)
    for result in results:
        print(
            f"{result.name:32s} {result.exported:7d}  {len(result.unsafe):6d}  "
            f"{len(result.unconsumed_types):10d}"
        )
        if result.error:
            print(f"    error: {result.error}")
            findings += 1
        for item in result.unsafe:
            print(f"    unsafe signature: {item}")
            findings += 1
        for name in result.unconsumed_types:
            print(f"    exported type with no consumer outside its own file: {name}")
            findings += 1

    print()
    print(f"public API type audit: {findings} finding(s) across {len(results)} package(s)")
    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

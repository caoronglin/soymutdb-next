#!/usr/bin/env python3
"""Enforce the Phase C framework-neutral seam.

Packages in ``FRAMEWORK_NEUTRAL_PACKAGES`` are the shared, framework-agnostic
layer that both the current React apps and the incoming Vue apps consume
(see ``plan.md`` §7 / Phase C). They MUST NOT import a UI framework. If a
framework binding sneaks in, the "one neutral layer, two consumers" guarantee
breaks and Vue would end up pulling a second React runtime (H8/H9).

The check is intentionally dependency-free (stdlib only) so it runs in every
CI job that already runs Python. It scans the declared packages' source for
banned bare module specifiers in ``import``/``export ... from``, side-effect
``import '...'``, dynamic ``import('...')`` and ``require('...')``.

Usage:
    python3 scripts/check_framework_neutral_packages.py            # scan repo
    python3 scripts/check_framework_neutral_packages.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# The framework-neutral seam grows as we extract packages in Phase C. A package
# is listed here by its workspace ``name`` (not its directory) so the mapping
# survives directory moves. Every entry MUST currently have zero framework
# imports; ``scripts/test_framework_neutral_packages.py`` fails otherwise.
FRAMEWORK_NEUTRAL_PACKAGES: tuple[str, ...] = (
    "@soymutdb/shared",
    "@soymutdb/api-client",
    "@soymutdb/query-keys",
)

# Packages join this tuple as Phase C extracts them (one reviewed commit each),
# so the guard grows with the seam and never lags behind a new neutral package.

# Banned exact bare module names (React, Vue, Ant Design, chart runtime).
_BANNED_EXACT: frozenset[str] = frozenset(
    {
        "react",
        "react-dom",
        "react-i18next",
        "react-router",
        "react-router-dom",
        "antd",
        "pinia",
        "echarts",
        "vue",
    }
)

# Banned bare-module *name* prefixes. Catches scoped and sub-path imports such
# as ``@ant-design/icons``, ``@tanstack/react-query`` and ``react-hook-form``.
_BANNED_PREFIXES: tuple[str, ...] = (
    "react-",
    "@ant-design/",
    "@tanstack/react-",
    "@tanstack/vue-",
    "@vue/",
    "vue-",
    "ant-design-vue",
)

_SCANNED_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})
_PRUNE_DIRS = frozenset({"node_modules", "dist", ".turbo", "coverage", "__pycache__"})

# Import/require specifier extractors. Relative specifiers (``./``, ``../``) and
# absolute paths are internal and ignored; only bare module names are checked.
_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # import x from "spec" / import { a } from "spec" / import type ...
    re.compile(r"""\bimport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]"""),
    # import type A from "spec" (covered above) and re-export ... from "spec"
    re.compile(r"""\bexport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]"""),
    # side-effect only: import "spec"
    re.compile(r"""\bimport\s*['"]([^'"]+)['"]"""),
    # dynamic import("spec")
    re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    # CommonJS require("spec")
    re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)


def is_bare_module(specifier: str) -> bool:
    """True when *specifier* names an external package (not relative/absolute)."""
    return not specifier.startswith((".", "/", "#"))


def is_banned(specifier: str) -> bool:
    """True when *specifier* resolves to a banned UI-framework module."""
    if specifier in _BANNED_EXACT:
        return True
    return any(specifier.startswith(prefix) for prefix in _BANNED_PREFIXES)


def _iter_source_files(package_dir: Path):
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SCANNED_SUFFIXES:
            continue
        if any(part in _PRUNE_DIRS for part in path.parts):
            continue
        yield path


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan_package(package_dir: Path) -> list[str]:
    """Return one ``"path:line: ..."`` violation string per banned import."""
    violations: list[str] = []
    for source in _iter_source_files(package_dir):
        text = source.read_text(encoding="utf-8")
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(text):
                specifier = match.group(1)
                if not is_bare_module(specifier):
                    continue
                if is_banned(specifier):
                    line = _line_of(text, match.start(1))
                    violations.append(
                        f"{source.as_posix()}:{line}: "
                        f"framework-neutral package imports '{specifier}'"
                    )
    return violations


def _package_dirs(packages_root: Path) -> dict[str, Path]:
    """Map workspace package ``name`` -> directory for every package present."""
    mapping: dict[str, Path] = {}
    for manifest in sorted(packages_root.glob("*/package.json")):
        try:
            name = json.loads(manifest.read_text(encoding="utf-8")).get("name")
        except (OSError, json.JSONDecodeError):
            continue
        if name:
            mapping[name] = manifest.parent
    return mapping


def find_violations(repo_root: Path) -> list[str]:
    """Scan every declared framework-neutral package under *repo_root*."""
    available = _package_dirs(repo_root / "packages")
    violations: list[str] = []
    for name in FRAMEWORK_NEUTRAL_PACKAGES:
        package_dir = available.get(name)
        if package_dir is None:
            violations.append(f"{name}: declared framework-neutral package is missing")
            continue
        violations.extend(scan_package(package_dir))
    return violations


def self_test() -> None:
    """Prove detection works: a dirty fixture is caught, a clean one is not."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        packages = root / "packages"
        clean = packages / "clean"
        dirty = packages / "dirty"
        (clean / "src").mkdir(parents=True)
        (dirty / "src").mkdir(parents=True)
        (clean / "package.json").write_text(
            json.dumps({"name": "@acme/clean"}), encoding="utf-8"
        )
        (dirty / "package.json").write_text(
            json.dumps({"name": "@acme/dirty"}), encoding="utf-8"
        )
        (clean / "src" / "index.ts").write_text(
            'import { cn } from "@soymutdb/shared";\n'
            "export const ok = cn;\n",
            encoding="utf-8",
        )
        (dirty / "src" / "index.tsx").write_text(
            'import { useState } from "react";\n'
            'import Button from "antd";\n'
            'const Vue = await import("vue");\n'
            "export const bad = () => [useState, Button, Vue];\n",
            encoding="utf-8",
        )

        global FRAMEWORK_NEUTRAL_PACKAGES
        saved = FRAMEWORK_NEUTRAL_PACKAGES
        try:
            FRAMEWORK_NEUTRAL_PACKAGES = ("@acme/clean", "@acme/dirty")
            violations = find_violations(root)
        finally:
            FRAMEWORK_NEUTRAL_PACKAGES = saved

        dirty_violations = [v for v in violations if "packages/dirty/" in v]
        clean_violations = [v for v in violations if "packages/clean/" in v]
        assert not clean_violations, f"clean fixture flagged: {clean_violations}"
        found = {spec for spec in ("react", "antd", "vue")}
        for banned in found:
            assert any(f"'{banned}'" in v for v in dirty_violations), (
                f"self-test missed {banned}: {dirty_violations}"
            )
        # The missing-package guard must also fire.
        try:
            FRAMEWORK_NEUTRAL_PACKAGES = ("@acme/absent",)
            missing = find_violations(root)
        finally:
            FRAMEWORK_NEUTRAL_PACKAGES = saved
        assert missing == ["@acme/absent: declared framework-neutral package is missing"], (
            f"missing-package guard failed: {missing}"
        )
    print("framework-neutral package guard self-test passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0

    repo_root = args.repo_root or Path(__file__).resolve().parent.parent
    violations = find_violations(repo_root)
    if violations:
        print("framework-neutral seam violations:", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    names = ", ".join(FRAMEWORK_NEUTRAL_PACKAGES)
    print(f"framework-neutral seam clean: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

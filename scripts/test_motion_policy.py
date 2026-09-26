"""Restore the retired motion-policy guard for the Vue portal.

packages/motion (React) carried motion-policy-contract.test.mjs, which failed
when 'gsap', 'lenis' or '@soymutdb/motion' appeared in apps/web/src or the
app/package manifests. Retiring the package deleted the guard while the
invariant it protected is still load-bearing: the Vue portal renders motion with
bounded, accessible primitives (CSS transitions + IntersectionObserver) and
must not acquire a heavyweight animation engine (GSAP/ScrollTrigger) or a
smooth-scroll hijacker (Lenis) that fights the router, deep links and
prefers-reduced-motion.

This module restores that invariant as a dependency-free scanner plus the tests
that run it. The scanner keeps the same shape as the retired one:

* every source file under apps/web/src (.ts/.tsx/.mts/.cts/.js/.jsx/.mjs/.cjs/
  .vue) is checked for import / export ... from / import(...) / require(...) of a
  banned module, and for the bare tokens gsap / lenis / ScrollTrigger;
* every workspace manifest (root package.json, apps/*/package.json,
  packages/*/package.json, e2e/package.json when present, and
  pnpm-workspace.yaml) is checked for a banned dependency or catalog key.

test_scanner_catches_a_planted_violation builds a throwaway tree, plants a
banned import and a banned dependency, and proves both are reported, so a
scanner that silently stopped matching cannot pass the suite.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BANNED_MODULES: tuple[str, ...] = ("gsap", "lenis", "@soymutdb/motion")
BANNED_TOKENS: tuple[str, ...] = ("gsap", "lenis", "ScrollTrigger")
DEPENDENCY_SECTIONS: tuple[str, ...] = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)

_SOURCE_SUFFIXES = frozenset(
    {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue"}
)
_PRUNE_DIRS = frozenset({"node_modules", "dist", ".turbo", "coverage", "__pycache__"})

# Same extractor shapes as scripts/check_framework_neutral_packages.py so the two
# source guards cannot drift on what a module import even looks like.
_IMPORT_PATTERNS = (
    re.compile(r"""\bimport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    re.compile(r"""\bexport\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    re.compile(r"""\bimport\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.IGNORECASE),
    re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.IGNORECASE),
)
_BANNED_TOKEN_RE = re.compile(r"\b(?:gsap|lenis|ScrollTrigger)\b")
_MANIFEST_KEY_RE = re.compile(r"""(?m)^[ \t]*['"]?([@\w./-]+)['"]?[ \t]*:""")


def is_banned_specifier(specifier: str) -> bool:
    """True when *specifier* resolves to a banned motion module (or a subpath)."""
    return any(
        specifier == banned or specifier.startswith(banned + "/")
        for banned in BANNED_MODULES
    )


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _iter_source_files(source_dir: Path):
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        if any(part in _PRUNE_DIRS for part in path.parts):
            continue
        yield path


def scan_source(source_dir: Path) -> list[str]:
    """Return one violation per banned import or bare token under *source_dir*."""
    if not source_dir.is_dir():
        return [f"{source_dir.as_posix()}: portal source directory is missing"]
    violations: list[str] = []
    for source in _iter_source_files(source_dir):
        text = source.read_text(encoding="utf-8")
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(text):
                specifier = match.group(1)
                if is_banned_specifier(specifier):
                    violations.append(
                        f"{source.as_posix()}:{_line_of(text, match.start(1))}: "
                        f"imports banned motion module '{specifier}'"
                    )
        token = _BANNED_TOKEN_RE.search(text)
        if token is not None:
            violations.append(
                f"{source.as_posix()}:{_line_of(text, token.start())}: "
                f"contains banned motion token '{token.group(0)}'"
            )
    return violations


def _manifest_paths(root: Path) -> list[Path]:
    candidates = [root / "package.json", root / "e2e" / "package.json"]
    for base in ("apps", "packages"):
        candidates.extend(sorted((root / base).glob("*/package.json")))
    return [path for path in candidates if path.is_file()]


def scan_manifests(root: Path) -> list[str]:
    """Return one violation per banned dependency declared in a workspace manifest."""
    violations: list[str] = []
    for manifest in _manifest_paths(root):
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            violations.append(f"{manifest.as_posix()}: invalid JSON ({error})")
            continue
        relative = manifest.relative_to(root).as_posix()
        for section in DEPENDENCY_SECTIONS:
            declared = document.get(section)
            if not isinstance(declared, dict):
                continue
            for name in declared:
                if name in BANNED_MODULES:
                    violations.append(f"{relative}: {section} declares '{name}'")
    # pnpm-workspace.yaml carries the shared catalog/overrides; a banned module
    # there re-enters every consumer through the catalog: protocol.
    workspace = root / "pnpm-workspace.yaml"
    if workspace.is_file():
        for number, line in enumerate(
            workspace.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = _MANIFEST_KEY_RE.match(line)
            if match and match.group(1) in BANNED_MODULES:
                violations.append(
                    f"pnpm-workspace.yaml:{number}: declares '{match.group(1)}'"
                )
    return violations


def find_violations(root: Path) -> list[str]:
    """Scan the portal source and every workspace manifest under *root*."""
    return scan_source(root / "apps" / "web" / "src") + scan_manifests(root)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def self_test(root: Path) -> None:
    """Prove the scanner catches a planted violation and leaves clean code alone."""
    _write(
        root / "apps" / "web" / "src" / "motion-utils.ts",
        'import { ref } from "vue";\n'
        'import { cn } from "@soymutdb/shared";\n'
        "export const ok = ref(cn);\n",
    )
    _write(
        root / "package.json",
        json.dumps({"name": "fixture", "dependencies": {"vue": "^3.5.0"}}),
    )
    clean = find_violations(root)
    assert clean == [], f"clean fixture was flagged: {clean}"

    # A planted import inside a .vue SFC and a planted dependency must surface.
    _write(
        root / "apps" / "web" / "src" / "views" / "Planted.vue",
        '<script setup lang="ts">\nimport gsap from "gsap";\n</script>\n',
    )
    _write(
        root / "apps" / "web" / "package.json",
        json.dumps({"name": "web", "dependencies": {"lenis": "^1.3.0"}}),
    )
    violations = find_violations(root)
    assert any("'gsap'" in item and "Planted.vue" in item for item in violations), (
        f"self-test missed the planted source import: {violations}"
    )
    assert any("lenis" in item and "dependencies" in item for item in violations), (
        f"self-test missed the planted dependency: {violations}"
    )


def test_portal_source_and_workspace_manifests_are_motion_policy_clean() -> None:
    violations = find_violations(ROOT)
    assert violations == [], (
        "gsap/lenis/@soymutdb/motion re-entered apps/web/src or a workspace "
        "manifest:\n" + "\n".join(f"  {item}" for item in violations)
    )


def test_scanner_catches_a_planted_violation(tmp_path: Path) -> None:
    self_test(tmp_path)


def test_banned_specifier_classifier_rejects_subpaths_and_allows_lookalikes() -> None:
    for banned in (
        "gsap",
        "gsap/ScrollTrigger",
        "lenis",
        "lenis/react",
        "@soymutdb/motion",
    ):
        assert is_banned_specifier(banned), banned
    for allowed in ("vue", "@soymutdb/shared", "./motion-utils", "gsapish", "smooth"):
        assert not is_banned_specifier(allowed), allowed

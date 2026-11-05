#!/usr/bin/env python3
"""Keep `smoke.sh --profile contracts` runnable on a clean checkout.

The contracts layer is documented (docs/ops/ci-cd.md section 5) as having no
prerequisite. It used to invoke `node scripts/check_visible_i18n_react.mjs
--self-test`, whose module-level `import ts from "typescript"` resolves only
after `pnpm install`. On CNB the layer passed because the Frontend verification
stage had already left a `node_modules` in the shared /workspace -- a sibling
stage's side effect, not something this layer owns. A clean checkout, a
standalone stage rerun, or a reordered stage produced a bare
`ERR_MODULE_NOT_FOUND: Cannot find package 'typescript'`. The acceptance
pipeline's `Delivery contracts` stage runs on `python:3.15`, which has no node
at all, so the same call failed there too.

The React guard's self-test and its real scan are owned by
`scripts/verify-frontend-artifacts.sh`, which bootstraps the workspace on both
providers. This module asserts that the contracts layer no longer carries a
workspace-dependent Node call, that the frontend gate still runs both forms of
the React guard, that `typescript` remains declared, and that the checker is
still wired into smoke.sh. Every assertion is mutation-tested here, so a guard
that would pass vacuously fails.

Run directly (stdlib only, no pytest needed) or collect with pytest:
    python3 scripts/test_contracts_layer_self_containment.py
    pytest scripts/test_contracts_layer_self_containment.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"
FRONTEND_GATE = ROOT / "scripts" / "verify-frontend-artifacts.sh"
REACT_GUARD = ROOT / "scripts" / "check_visible_i18n_react.mjs"
PACKAGE = ROOT / "package.json"
SELF = Path(__file__).name

GUARD_NAME = re.escape(REACT_GUARD.name)
NODE_SCRIPT_CALL = re.compile(r"(^|[^\w-])node\s+\S+\.(mjs|js|cjs)\b")


def active_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def contracts_body(text: str) -> str:
    start = text.index("smoke_contracts() {")
    return text[start : text.index("\n}\n", start)]


def failures(smoke: str, frontend: str, guard: str, package: str) -> list[str]:
    found: list[str] = []

    for line in active_lines(contracts_body(smoke)):
        if NODE_SCRIPT_CALL.search(line):
            found.append(
                "contracts layer invokes a Node script that needs an installed "
                f"workspace: {line.strip()}"
            )

    active = "\n".join(active_lines(frontend))
    if not re.search(rf"node\s+scripts/{GUARD_NAME}\s+--self-test\b", active):
        found.append("frontend gate no longer runs the React i18n guard self-test")
    if not re.search(rf"node\s+scripts/{GUARD_NAME}\s*$", active, re.MULTILINE):
        found.append("frontend gate no longer runs the React i18n guard scan")

    imports = re.findall(r'^import\s+.*?\s+from\s+"([^"]+)";', guard, re.MULTILINE)
    third_party = sorted({name for name in imports if not name.startswith("node:")})
    if third_party != ["typescript"]:
        found.append(f"React guard third-party imports changed: {third_party}")

    manifest = json.loads(package)
    declared = {
        **manifest.get("dependencies", {}),
        **manifest.get("devDependencies", {}),
    }
    if "typescript" not in declared:
        found.append(
            "typescript is no longer declared, so the frontend gate cannot install it"
        )

    if f"scripts/{SELF}" not in contracts_body(smoke):
        found.append("contracts layer no longer invokes the self-containment checker")

    return found


def current() -> tuple[str, str, str, str]:
    return (
        SMOKE.read_text(encoding="utf-8"),
        FRONTEND_GATE.read_text(encoding="utf-8"),
        REACT_GUARD.read_text(encoding="utf-8"),
        PACKAGE.read_text(encoding="utf-8"),
    )


def test_committed_tree_is_self_contained() -> None:
    assert not (found := failures(*current())), found


def test_reintroducing_a_node_call_is_rejected() -> None:
    smoke, frontend, guard, package = current()
    mutant = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n',
        '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n'
        f"  node scripts/{REACT_GUARD.name} --self-test || rc=$?\n",
    )
    assert mutant != smoke
    assert any(
        "contracts layer invokes a Node script" in line
        for line in failures(mutant, frontend, guard, package)
    )


def test_dropping_the_frontend_guard_is_rejected() -> None:
    smoke, frontend, guard, package = current()
    cases = (
        (
            "frontend gate no longer runs the React i18n guard self-test",
            f"node scripts/{REACT_GUARD.name} --self-test\n",
        ),
        (
            "frontend gate no longer runs the React i18n guard scan",
            f"node scripts/{REACT_GUARD.name}\n",
        ),
    )
    for expected, needle in cases:
        reduced = frontend.replace(needle, "")
        assert reduced != frontend
        assert expected in failures(smoke, reduced, guard, package)


def test_undeclared_typescript_is_rejected() -> None:
    smoke, frontend, guard, package = current()
    manifest = json.loads(package)
    manifest["devDependencies"].pop("typescript", None)
    assert any(
        "typescript is no longer declared" in line
        for line in failures(smoke, frontend, guard, json.dumps(manifest))
    )


def test_dropping_the_checker_wiring_is_rejected() -> None:
    smoke, frontend, guard, package = current()
    unwired = smoke.replace(f"    scripts/{SELF}\n", "")
    assert unwired != smoke
    assert any(
        "no longer invokes the self-containment checker" in line
        for line in failures(unwired, frontend, guard, package)
    )


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            problems.append(f"{test.__name__}: {str(exc) or 'assertion failed'}")
    if problems:
        for problem in problems:
            print(f"contracts-layer self-containment: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"contracts-layer self-containment: OK ({len(tests)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

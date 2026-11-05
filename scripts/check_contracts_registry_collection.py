#!/usr/bin/env python3
"""Pin the contracts-layer registry to suites pytest can actually collect.

``scripts/smoke.sh`` hands a literal array of paths to pytest. A path that
exists but defines no collectible test is silently ignored: the layer still
prints ``SMOKE PASS`` with an unchanged test count. A hand-merge that keeps a
bogus entry, or a rename that turns a suite into a non-test module, therefore
ships a green gate that verifies nothing -- the "registered but not collected"
shape that has recurred in this repository (hardcoded counts, ``Ran 0 tests,
OK``, and the two independent wiring slots of the interval-visibility guard).

The same function invokes a floor of stdlib guards as separate
``${PYTHON_BIN} scripts/check_*.py ... || rc=$?`` calls. That is a second
wiring mechanism: a merge can drop one without touching the array, and the
layer stays green because the remaining guards still pass.

This guard reads committed bytes only. It does not run pytest, import the
suites, need Python 3.15, a wheel, a database or a workspace install, so it
can run before the expensive build. It is a *static* proxy for collection:
pytest's real discovery is richer, but this repository uses only module-level
``def test_*`` and ``unittest.TestCase`` subclasses with ``test_*`` methods,
which the guard checks with the ``ast`` module. ``--self-test`` injects
one-sided drifts into copies of the sources and asserts each is caught.

Usage:
    python3 scripts/check_contracts_registry_collection.py --self-test
    python3 scripts/check_contracts_registry_collection.py
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"

ARRAY_ENTRY = re.compile(
    r"^\s+((?:scripts|infra)/[A-Za-z0-9_./-]+\.py)\s*$", re.MULTILINE
)
# Optional arguments (``--static``, ``--self-test``) sit between the path and
# ``|| rc=$?``; the path alone is what must resolve to a committed file.
GUARD_CALL = re.compile(
    r'"\$\{PYTHON_BIN\}"\s+(scripts/[A-Za-z0-9_./-]+\.py)'
    r'(?:\s+[^|]*?)?\s*\|\|\s*rc=\$\?'
)

# A dropped guard call is invisible to a validator that only checks paths:
# "fewer calls" and "intentionally removed" look identical. Pin the known
# floor explicitly. Adding a new guard call does not require editing this
# list (the check only requires these to still be present); removing one does.
REQUIRED_GUARD_CALLS: frozenset[str] = frozenset(
    {
        "scripts/check-toolchain-pins.py",
        "scripts/check_bio_core_wheel.py",
        "scripts/check_workspace_exports.py",
        "scripts/check_app_shell_assets.py",
        "scripts/check_visible_i18n.py",
        "scripts/check_nginx_security_headers.py",
    }
)


def contracts_function(smoke: str) -> str:
    """Return just the body of smoke_contracts(), up to its closing brace."""
    marker = "smoke_contracts() {"
    if marker not in smoke:
        raise ValueError("smoke.sh no longer defines smoke_contracts()")
    return smoke.split(marker, 1)[1].split("\n}\n", 1)[0]


def registry(smoke: str) -> list[str]:
    """The gating ``tests=()`` array, not the environment-bound list."""
    body = contracts_function(smoke)
    head = body.split("environment_bound=(", 1)[0]
    return ARRAY_ENTRY.findall(head.split("(", 1)[1] if "(" in head else head)


def guard_calls(smoke: str) -> list[str]:
    """Standalone ``check_*.py`` invocations inside smoke_contracts()."""
    return GUARD_CALL.findall(contracts_function(smoke))


def collectible_tests(source: str, path: str) -> list[str]:
    """Names of tests pytest would discover in a plain module's AST."""
    tree = ast.parse(source, filename=path)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name.startswith("test")
                ):
                    names.append(f"{node.name}::{item.name}")
    return names


def check(smoke: str, files: dict[str, str]) -> list[str]:
    """Return human-readable failures; empty means the wiring is sound."""
    errors: list[str] = []

    entries = registry(smoke)
    if not entries:
        errors.append("could not read the contracts-layer tests=() array")
    seen: set[str] = set()
    for relative in entries:
        if relative in seen:
            errors.append(f"duplicate registry entry {relative!r}")
        seen.add(relative)
        if relative not in files:
            errors.append(f"registry entry {relative!r} does not exist")
            continue
        try:
            tests = collectible_tests(files[relative], relative)
        except SyntaxError as exc:
            errors.append(f"registry entry {relative!r} does not parse: {exc}")
            continue
        if not tests:
            errors.append(
                f"registry entry {relative!r} defines no collectible test "
                "(pytest would silently collect 0 from it)"
            )

    calls = set(guard_calls(smoke))
    if not calls:
        errors.append("could not read any standalone guard calls")
    for relative in sorted(REQUIRED_GUARD_CALLS - calls):
        errors.append(f"standalone guard call {relative!r} was dropped")
    for relative in sorted(calls):
        if relative not in files:
            errors.append(f"standalone guard call {relative!r} does not exist")

    return errors


def load_sources() -> dict[str, str]:
    """Read the committed bytes of every path the two wirings reference."""
    smoke = SMOKE.read_text(encoding="utf-8")
    referenced = set(registry(smoke)) | set(guard_calls(smoke)) | set(
        REQUIRED_GUARD_CALLS
    )
    return {
        p: (ROOT / p).read_text(encoding="utf-8")
        for p in referenced
        if (ROOT / p).is_file()
    }


def self_test() -> int:
    """Every one-sided drift must be caught; the clean tree must pass."""
    smoke = SMOKE.read_text(encoding="utf-8")
    files = load_sources()
    clean = check(smoke, files)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    cases: list[tuple[str, str, dict[str, str]]] = []

    target = "scripts/test_ci_job_contracts.py"
    mutant = dict(files)
    mutant[target] = re.sub(r"\bdef test_", "def _hidden_", files[target])
    cases.append(("a registered suite loses every collectible name", smoke, mutant))

    phantom = "scripts/test_phantom_wiring_probe.py"
    smoke2 = smoke.replace(
        "    infra/clickhouse/test_schema_contract.py\n",
        f"    {phantom}\n    infra/clickhouse/test_schema_contract.py\n",
        1,
    )
    mutant2 = dict(files)
    mutant2[phantom] = "def check_not_a_test():\n    return 1\n"
    cases.append(("a phantom registry entry collects nothing", smoke2, mutant2))

    smoke3 = smoke.replace(
        "    infra/clickhouse/test_schema_contract.py\n",
        "    scripts/test_deleted_wiring_probe.py\n",
        1,
    )
    cases.append(("a registry entry is dropped on disk", smoke3, dict(files)))

    smoke4 = smoke.replace(
        "    scripts/test_ci_job_contracts.py\n",
        "    scripts/test_ci_job_contracts.py\n    scripts/test_ci_job_contracts.py\n",
        1,
    )
    cases.append(("a registry entry is duplicated", smoke4, dict(files)))

    smoke5 = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        "",
        1,
    )
    cases.append(("a standalone guard call is dropped", smoke5, dict(files)))

    mutant6 = dict(files)
    mutant6.pop("scripts/check_nginx_security_headers.py", None)
    cases.append(("a called guard disappears from disk", smoke, mutant6))

    # Positive control: adding a NEW guard call must not require an edit here.
    extra = "scripts/check_extra_wiring_probe.py"
    smoke7 = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        '  "${PYTHON_BIN}" ' + extra + ' || rc=$?\n'
        '  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        1,
    )
    mutant7 = dict(files)
    mutant7[extra] = "# a real guard\n"

    failures = 0
    for label, mutated_smoke, mutated_files in cases:
        found = check(mutated_smoke, mutated_files)
        if found:
            print(f"PASS self-test: {label} -> {len(found)} failure(s)")
        else:
            print(f"FAIL self-test: {label} was NOT caught")
            failures += 1
    fresh = check(smoke7, mutant7)
    if fresh:
        print(f"FAIL self-test: adding a new guard call was rejected: {fresh}")
        failures += 1
    else:
        print("PASS self-test: adding a new guard call needs no allowlist edit")

    print(f"self-test: {len(cases) + 1} cases, {failures} failure(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="run the mutation self-test"
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    text = SMOKE.read_text(encoding="utf-8")
    errors = check(text, load_sources())
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"contracts registry collection: {len(errors)} failure(s)")
        return 1
    print(
        f"contracts registry collection: OK "
        f"({len(registry(text))} gating suites, "
        f"{len(guard_calls(text))} guard calls)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

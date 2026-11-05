#!/usr/bin/env python3
"""Pin the contracts-layer registry to suites pytest can actually collect.

``scripts/smoke.sh`` hands a literal array of paths to pytest. A path that
exists but defines no collectible test is silently ignored: the layer still
prints ``SMOKE PASS`` with an unchanged test count. A hand-merge that keeps a
bogus entry, or a rename that turns a suite into a non-test module, therefore
ships a green gate that verifies nothing -- the "registered but not collected"
shape that has recurred in this repository (hardcoded counts, ``Ran 0 tests,
OK``, and the two independent wiring slots of the interval-visibility guard).

The guard is wired through two independent entry points: ``smoke.sh`` invokes
it directly, and ``ci-job-steps.sh`` runs its ``--self-test`` before the
contracts layer on both providers. A merge that drops the CI-side line leaves
``--self-test`` unreachable while the local layer stays green, so the CI
disappearance is silent. This guard reads both files' committed bytes.

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
CI_STEPS = ROOT / "scripts" / "ci-job-steps.sh"
GUARD_NAME = "check_contracts_registry_collection.py"

# The CI-side wiring: `python3 "${REPO_ROOT}/scripts/<guard>.py" --self-test`
# inside smoke_contracts_run(). A path/flag change must fail loudly, not drift.
#
# The pin is anchored to the WHOLE line, not to a substring of it. A substring
# pin answers "do these bytes occur?" -- which is not the same question as
# "does bash execute this line and does its exit status reach the pipeline".
# `... --self-test || true`, `... --self-test 2>/dev/null`, `... --self-test |
# tail -1`, `... --self-test # note`, `( ... ) &` and `dead() { ...; }` all keep
# the substring and all keep the gate dead. Anchoring (with no `$` alternative
# and no `re.MULTILINE`) means any trailing operator, redirection, comment,
# wrapper or deeper indentation stops matching, so it is reported instead.
CI_SELF_TEST = re.compile(
    r"^(?P<indent>[ \t]*)python3[ \t]+\"\$\{REPO_ROOT\}/scripts/"
    + re.escape(GUARD_NAME)
    + r"\"[ \t]+--self-test[ \t]*$"
)
# The CI line exists to gate the layer *before* it runs. A hand-merge can move
# it below the smoke.sh call while still matching, inverting the ordering.
# Match the `bash .../smoke.sh` invocation itself, not its arguments: the
# ordering reference is the call to the layer runner, whatever profile it is
# given. Pinning the literal `--profile contracts` would lose the reference
# (and skip the assertion) the moment a hand-merge edits that argument.
CI_LAYER_CALL = re.compile(
    r'^[ \t]*bash[ \t]+"\$\{REPO_ROOT\}/scripts/smoke\.sh"(?:[ \t][^\n]*)?$',
    re.MULTILINE,
)

ARRAY_ENTRY = re.compile(
    r"^\s+((?:scripts|infra)/[A-Za-z0-9_./-]+\.py)\s*$", re.MULTILINE
)
# Optional arguments (``--static``, ``--self-test``) sit between the path and
# ``|| rc=$?``; the path alone is what must resolve to a committed file.
# A commented-out call still matches its text but never runs, so the match
# must begin at the command itself, not at a `#` (allow leading whitespace).
GUARD_CALL = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"\s+(scripts/[A-Za-z0-9_./-]+\.py)'
    r'(?:\s+[^|]*?)?\s*\|\|\s*rc=\$\?',
    re.MULTILINE,
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


DRIVER_MARKER = "if should_run contracts; then"


def driver_propagates(smoke: str) -> bool | None:
    """Whether the driver-level registry guard's failure reaches the exit.

    ``None`` means there is no driver to check (synthetic ``smoke.sh`` text
    passed by the unit tests). At top-level scope ``rc`` is never read --
    only the ``FAILED`` array decides the final exit status -- so a bare
    ``|| rc=$?`` prints the guard's diagnostics but still yields SMOKE PASS.
    """
    if DRIVER_MARKER not in smoke:
        return None
    block = smoke.split(DRIVER_MARKER, 1)[1].split("\nfi", 1)[0]
    for line in block.splitlines():
        if not line.lstrip().startswith("#") and (
            "check_contracts_registry_collection.py" in line and "||" in line
        ):
            return "FAILED" in line and "rc=$?" not in line
    return False


def contracts_function(smoke: str) -> str:
    """Return just the body of smoke_contracts(), up to its closing brace."""
    marker = "smoke_contracts() {"
    if marker not in smoke:
        raise ValueError("smoke.sh no longer defines smoke_contracts()")
    return smoke.split(marker, 1)[1].split("\n}\n", 1)[0]


def ci_contracts_function(ci_steps: str) -> str:
    """Return the body of smoke_contracts_run() from ci-job-steps.sh."""
    marker = "smoke_contracts_run() {"
    if marker not in ci_steps:
        raise ValueError("ci-job-steps.sh no longer defines smoke_contracts_run()")
    return ci_steps.split(marker, 1)[1].split("\n}\n", 1)[0]


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


def _width(indent: str) -> int:
    """Columns an indent occupies; a tab advances to the next multiple of 8."""
    column = 0
    for char in indent:
        column = column + 8 - column % 8 if char == "\t" else column + 1
    return column


def _indent(line: str) -> str:
    """Leading whitespace of a line."""
    return line[: len(line) - len(line.lstrip(" \t"))]


def ci_wiring_errors(ci_body: str) -> list[str]:
    """Failures in the CI-side wiring of the guard's ``--self-test``.

    Three properties are checked, each one measured rather than assumed:
    the line is a bare statement (nothing chained, piped, redirected, wrapped
    or commented onto it), it is not structurally inside a compound command
    (which is exactly how a gate goes dead while staying "present"), and it
    runs ahead of the layer it is supposed to gate.
    """
    lines = ci_body.splitlines()
    hits = [line for line in lines if CI_SELF_TEST.match(line)]
    if not hits:
        return [
            f"{GUARD_NAME} --self-test is not wired as a standalone statement "
            "in scripts/ci-job-steps.sh (smoke_contracts_run): a chained, piped, "
            "redirected, wrapped or commented-out call never gates the layer"
        ]
    if len(hits) > 1:
        return [
            f"{GUARD_NAME} --self-test is wired {len(hits)} times in "
            "scripts/ci-job-steps.sh (smoke_contracts_run)"
        ]

    # Nesting: a line written inside a compound command (`foo() {`,
    # `if ...; then`, `( ... )`, `case ... do`) sits one indent deeper than the
    # line that opened it, and bash records that call's status per command
    # rather than propagating it. `dead() { ...; }` is the shape: the substring
    # survives, the gate does not. The reference is the previous statement, so a
    # cosmetic re-indent of the whole body moves both and is still accepted,
    # while a line that jumps a level relative to what came before it is
    # reported. Width alone cannot tell those apart -- and this repository mixes
    # tabs with spaces -- hence the structural reading.
    openers = (";", "then", "do", "{", "(", "&")
    target = next(n for n, line in enumerate(lines) if line == hits[0])
    previous = ""
    for line in lines[:target]:
        if line.strip() and not line.lstrip().startswith("#"):
            previous = line.rstrip()
    # An empty body (`smoke_contracts_run() {` then `}`) has no reference
    # statement; the line is then the body's first, which is not nesting.
    nested = bool(previous) and (
        previous.endswith(openers)
        or _width(_indent(previous)) != _width(_indent(hits[0]))
    )
    if nested:
        return [
            f"{GUARD_NAME} --self-test is nested inside a compound command in "
            "scripts/ci-job-steps.sh (smoke_contracts_run), so its exit status "
            "never reaches the pipeline"
        ]

    layer = CI_LAYER_CALL.search(ci_body)
    if layer is None:
        # Fail closed. If the `bash .../smoke.sh` call is dropped or its
        # arguments change, there is no reference point for the ordering
        # assertion; skipping it would leave the gate "present" while the layer
        # it is supposed to precede no longer exists in this function.
        return [
            f"{GUARD_NAME} --self-test must run before the contracts layer in "
            "scripts/ci-job-steps.sh (smoke_contracts_run), but the "
            "'bash .../smoke.sh' call is missing"
        ]
    if ci_body.index(hits[0]) > layer.start():
        return [
            f"{GUARD_NAME} --self-test runs after the contracts layer in "
            "scripts/ci-job-steps.sh (must gate it beforehand)"
        ]
    return []


def check(
    smoke: str, files: dict[str, str], ci_steps: str | None = None
) -> list[str]:
    """Return human-readable failures; empty means the wiring is sound."""
    errors: list[str] = []

    if ci_steps is not None:
        try:
            ci_body = ci_contracts_function(ci_steps)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            errors.extend(ci_wiring_errors(ci_body))

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

    if driver_propagates(smoke) is False:
        errors.append(
            "the driver-level registry guard's failure is not propagated "
            "(a bare '|| rc=$?' at top-level scope never reaches the exit status)"
        )

    return errors


def load_sources() -> tuple[str, str, dict[str, str]]:
    """Read the committed bytes of both wirings and their referenced files."""
    smoke = SMOKE.read_text(encoding="utf-8")
    ci_steps = CI_STEPS.read_text(encoding="utf-8")
    referenced = set(registry(smoke)) | set(guard_calls(smoke)) | set(
        REQUIRED_GUARD_CALLS
    )
    files = {
        p: (ROOT / p).read_text(encoding="utf-8")
        for p in referenced
        if (ROOT / p).is_file()
    }
    return smoke, ci_steps, files


def self_test() -> int:
    """Every one-sided drift must be caught; the clean tree must pass."""
    smoke, ci_steps, files = load_sources()
    clean = check(smoke, files, ci_steps)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    cases: list[tuple[str, str, dict[str, str], str]] = []

    target = "scripts/test_ci_job_contracts.py"
    mutant = dict(files)
    mutant[target] = re.sub(r"\bdef test_", "def _hidden_", files[target])
    cases.append(("a registered suite loses every collectible name", smoke, mutant, ci_steps))

    phantom = "scripts/test_phantom_wiring_probe.py"
    smoke2 = smoke.replace(
        "    infra/clickhouse/test_schema_contract.py\n",
        f"    {phantom}\n    infra/clickhouse/test_schema_contract.py\n",
        1,
    )
    mutant2 = dict(files)
    mutant2[phantom] = "def check_not_a_test():\n    return 1\n"
    cases.append(("a phantom registry entry collects nothing", smoke2, mutant2, ci_steps))

    smoke3 = smoke.replace(
        "    infra/clickhouse/test_schema_contract.py\n",
        "    scripts/test_deleted_wiring_probe.py\n",
        1,
    )
    cases.append(("a registry entry is dropped on disk", smoke3, dict(files), ci_steps))

    smoke4 = smoke.replace(
        "    scripts/test_ci_job_contracts.py\n",
        "    scripts/test_ci_job_contracts.py\n    scripts/test_ci_job_contracts.py\n",
        1,
    )
    cases.append(("a registry entry is duplicated", smoke4, dict(files), ci_steps))

    smoke5 = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        "",
        1,
    )
    cases.append(("a standalone guard call is dropped", smoke5, dict(files), ci_steps))

    mutant6 = dict(files)
    mutant6.pop("scripts/check_nginx_security_headers.py", None)
    cases.append(("a called guard disappears from disk", smoke, mutant6, ci_steps))

    ci_line = f'  python3 "${{REPO_ROOT}}/scripts/{GUARD_NAME}" --self-test\n'
    ci_missing = ci_steps.replace(ci_line, "", 1)
    cases.append(("the CI-side --self-test line is dropped", smoke, dict(files), ci_missing))

    smoke8 = smoke.replace(
        '|| FAILED+=("contracts registry")',
        "|| rc=$?",
        1,
    )
    assert smoke8 != smoke, "self-test could not locate the driver registry guard call"
    cases.append(
        (
            "the driver swallows the registry guard's failure",
            smoke8,
            dict(files),
            ci_steps,
        )
    )

    # Ordering: the guard must gate the layer *before* it runs. A hand-merge
    # can move the line below the smoke.sh call while it still matches.
    bash_line = '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
    assert bash_line in ci_steps, "self-test could not locate the layer call"
    ci_after = ci_steps.replace(ci_line, "", 1).replace(
        bash_line, bash_line + ci_line, 1
    )
    cases.append(("the CI --self-test line runs after the layer",
                  smoke, dict(files), ci_after))

    # The CI line is now pinned as a statement, but the other two wiring slots
    # are still read by text: a commented-out standalone guard or driver line
    # passes bash -n yet never executes. Assert both are reported.
    smoke_comment = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        '  # "${PYTHON_BIN}" scripts/check_nginx_security_headers.py || rc=$?\n',
        1,
    )
    cases.append(("a standalone guard call is commented out",
                  smoke_comment, dict(files), ci_steps))

    driver_line = (
        '  "${PYTHON_BIN}" scripts/check_contracts_registry_collection.py '
        '|| FAILED+=("contracts registry")\n'
    )
    assert driver_line in smoke, "self-test could not locate the driver guard line"
    smoke_driver_comment = smoke.replace(
        driver_line, "  # " + driver_line.strip() + "\n", 1
    )
    cases.append(("the driver registry guard line is commented out",
                  smoke_driver_comment, dict(files), ci_steps))

    # Fail closed when the layer call itself disappears: with no reference
    # point, the ordering assertion must not silently skip.
    ci_no_layer = ci_steps.replace(bash_line, "", 1)
    assert ci_no_layer != ci_steps, "self-test could not remove the layer call"
    cases.append(("the contracts layer call is dropped from the CI job",
                  smoke, dict(files), ci_no_layer))

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
    for label, mutated_smoke, mutated_files, mutated_ci in cases:
        found = check(mutated_smoke, mutated_files, mutated_ci)
        if found:
            print(f"PASS self-test: {label} -> {len(found)} failure(s)")
        else:
            print(f"FAIL self-test: {label} was NOT caught")
            failures += 1
    fresh = check(smoke7, mutant7, ci_steps)
    if fresh:
        print(f"FAIL self-test: adding a new guard call was rejected: {fresh}")
        failures += 1
    else:
        print("PASS self-test: adding a new guard call needs no allowlist edit")

    # Indentation was previously *accepted* for any width, on the reading that
    # bash runs the line either way. That reading is what let `dead() { ...; }`
    # pass: `{` ends its line, the call is deeper, and the gate is dead. Width
    # outside the body's own is now a nesting signal, so every variant below
    # must fail while the uniform re-indent control still passes.
    for label, lead in {
        "a one-space CI --self-test line": " ",
        "a tab-indented CI --self-test line": "\t",
        "a four-space CI --self-test line": "    ",
        "a tab-indented CI --self-test line in a tab-indented body": "\t\t",
    }.items():
        mutated_ci = ci_steps.replace(ci_line, f"{lead}{ci_line.strip()}\n", 1)
        assert mutated_ci != ci_steps, label
        found = check(smoke, files, mutated_ci)
        if found:
            print(f"PASS self-test: {label} is caught")
        else:
            print(f"FAIL self-test: {label} was accepted")
            failures += 1

    # Positive control for the nesting probe: re-indent the whole body by one
    # space. Nothing moved relative to anything, so the clean tree must stay
    # clean -- a guard that fails this is measuring a column, not a structure.
    shifted = re.sub(
        r"^(?=  \S)", " ", ci_contracts_function(ci_steps), flags=re.MULTILINE
    )
    shifted_ci = ci_steps.replace(
        ci_contracts_function(ci_steps), shifted, 1
    )
    found = check(smoke, files, shifted_ci)
    if found:
        print(f"FAIL self-test: a uniform re-indent was rejected: {found}")
        failures += 1
    else:
        print("PASS self-test: a uniform body re-indent is accepted")

    # Operand blind spot: `--self-test` present but unable to gate. Each of
    # these kept a substring pin green while the exit status was discarded.
    neutralised = {
        "|| true": " || true",
        "|| :": " || :",
        "2>/dev/null": " 2>/dev/null",
        "a trailing comment": "  # do not gate",
        "| tail -1": " | tail -1",
    }
    for label, suffix in neutralised.items():
        mutated_ci = ci_steps.replace(
            ci_line, f"{ci_line.rstrip()}{suffix}\n", 1
        )
        assert mutated_ci != ci_steps, label
        found = check(smoke, files, mutated_ci)
        if found:
            print(f"PASS self-test: a --self-test line with {label} is caught")
        else:
            print(f"FAIL self-test: a --self-test line with {label} was accepted")
            failures += 1

    wrapped = {
        "an if-false wrapper": f"  if false; then {ci_line.strip()}; fi\n",
        "a backgrounded subshell": f"  ( {ci_line.strip()} ) &\n",
        "a function that is never called": f"  dead() {{ {ci_line.strip()}; }}\n",
        "a call chained after &&": f"  true && {ci_line.strip()}\n",
    }
    for label, replacement in wrapped.items():
        mutated_ci = ci_steps.replace(ci_line, replacement, 1)
        assert mutated_ci != ci_steps, label
        found = check(smoke, files, mutated_ci)
        if found:
            print(f"PASS self-test: {label} around --self-test is caught")
        else:
            print(f"FAIL self-test: {label} around --self-test was accepted")
            failures += 1

    duplicated = ci_steps.replace(ci_line, ci_line + ci_line, 1)
    found = check(smoke, files, duplicated)
    if found:
        print("PASS self-test: a duplicated --self-test line is caught")
    else:
        print("FAIL self-test: a duplicated --self-test line was accepted")
        failures += 1

    print(f"self-test: {len(cases) + 15} cases, {failures} failure(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="run the mutation self-test"
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    smoke, ci_steps, files = load_sources()
    errors = check(smoke, files, ci_steps)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"contracts registry collection: {len(errors)} failure(s)")
        return 1
    print(
        f"contracts registry collection: OK "
        f"({len(registry(smoke))} gating suites, "
        f"{len(guard_calls(smoke))} guard calls, "
        f"CI --self-test wired)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pin the contracts layer's zero-test verdict on both of its entry points.

``scripts/smoke.sh`` ends with a decision that reads ``${#FAILED[@]}``: an
empty ``FAILED`` array is ``SMOKE PASS`` and exit status 0. That is correct for
a layer whose suites all passed and wrong for a layer that ran nothing. pytest
exits 5 for "no tests collected" -- but ``smoke_contracts()`` funnels every
failing command into ``rc=$?``, and a ``local tests=()`` array that expands to
nothing reaches pytest as a bare ``-q``, which then collects **this
repository's** whatever pytest happens to discover rather than "nothing":

    $ bash scripts/smoke.sh --profile contracts   # with tests=() emptied
    layer contracts FAILED                        # only if pytest itself is red

Worse, the two neighbouring shapes are already indistinguishable in the
summary: ``passed: 0 / failed: 0 / skipped: 0`` followed by ``SMOKE PASS``.
``run_layer`` appends to ``PASSED`` on a function's return status alone, so a
layer that returns 0 because it never collected a test is counted as a pass and
a clean checkout reports a green contracts gate that verified nothing. The same
holds on the CI side: ``smoke_contracts_run()`` in ``scripts/ci-job-steps.sh``
runs the wiring guard and one ``bash .../smoke.sh`` call, so if the layer
reports "nothing to run" as success, the Contract suites stage is green and no
telemetry says otherwise.

Why a static guard and not a runtime one: the verdict is a property of the
committed script text (does the empty case still reach a non-zero exit, and is
that non-zero still wired into the driver?), and a runtime probe would have to
run the whole layer to observe it. This guard reads committed bytes only --
no pytest, no workspace install, no service -- and ``--self-test`` plants the
one-sided drifts that turn the verdict back into a false green.

Usage:
    python3 scripts/check_contracts_empty_layer_verdict.py --self-test
    python3 scripts/check_contracts_empty_layer_verdict.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"
CI_STEPS = ROOT / "scripts" / "ci-job-steps.sh"
GUARD_NAME = "check_contracts_empty_layer_verdict.py"
PY = '"${PYTHON_BIN}"'

# The layer's exit status is ``$rc``, and ``$rc`` starts at 0. A layer that
# proves it collected something must therefore be able to raise ``rc`` -- and
# the only reviewed way to do that is the ``|| rc=$?`` tail every sibling guard
# call already uses. Match the whole line so a trailing operator, pipe,
# redirection or comment is reported instead of silently accepted.
GUARD_CALL = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"[ \t]+scripts/'
    + re.escape(GUARD_NAME)
    + r"[ \t]+--self-test[ \t]*\|\|[ \t]*rc=\$\?[ \t]*$",
    re.MULTILINE,
)
# And the plain (non-self-test) read must be wired too, or the layer only
# proves the guard has a signal while never auditing its own committed bytes.
REAL_CALL = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"[ \t]+scripts/'
    + re.escape(GUARD_NAME)
    + r"[ \t]*\|\|[ \t]*rc=\$\?[ \t]*$",
    re.MULTILINE,
)

# The two verdict shapes below are ``{passed, failed, skipped}`` counts taken
# from the driver. ``SMOKE PASS`` is printed only when ``failed == 0``, so the
# invariant this guard pins is exactly that binding -- a hand-merge that
# reorders or rewrites it, or that prints the verdict before the layers run,
# re-opens the hole.
SUMMARY_PASS = re.compile(
    r"^if \[\[\s*\"\$\{#FAILED\[@\]\}\"\s*-gt\s*0\s*\]\]; then[ \t]*$",
    re.MULTILINE,
)
PASS_BANNER = re.compile(
    r"^printf '\\n\\033\[32mSMOKE PASS\\033\[0m\\n'[ \t]*$", re.MULTILINE
)


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


def wiring_errors(smoke: str, ci_steps: str) -> list[str]:
    """Return human-readable failures; empty means the verdict still holds."""
    errors: list[str] = []
    try:
        body = contracts_function(smoke)
    except ValueError as exc:
        return [str(exc)]

    # 1. The layer must ask the guard whether it collected anything, twice:
    #    once to prove the guard has a signal (it plants both drifts and
    #    requires each to be caught) and once to read the committed bytes.
    if not GUARD_CALL.search(body):
        errors.append(
            f"{GUARD_NAME} --self-test is not wired into scripts/smoke.sh "
            "(smoke_contracts) as a `|| rc=$?` statement: an unwired, piped, "
            "redirected or commented-out call cannot raise the layer's exit "
            "status, so an empty run stays SMOKE PASS"
        )
    if not REAL_CALL.search(body):
        errors.append(
            f"{GUARD_NAME} is only wired through --self-test in scripts/smoke.sh "
            "(smoke_contracts): the layer then proves the guard has a signal "
            "while never auditing the committed scripts it is supposed to pin"
        )

    # 2. The verdict itself: SMOKE PASS is printed *outside* the failed branch.
    #    A rewrite that prints it unconditionally, or that compares the wrong
    #    array, makes every empty run green no matter what rc said.
    if not SUMMARY_PASS.search(smoke):
        errors.append(
            "scripts/smoke.sh no longer prints SMOKE PASS only when the FAILED "
            "array is empty: a layer that returns 0 without collecting anything "
            "would be reported as a pass"
        )
    if not PASS_BANNER.search(smoke):
        errors.append(
            "scripts/smoke.sh no longer prints the SMOKE PASS banner as a bare "
            "printf statement (a chained, redirected or commented-out banner "
            "cannot be distinguished from a real pass)"
        )

    # 3. Zero collected must be a FAILURE, not a skip. `skip_layer` is the
    #    shape that reads honest while reporting the layer as not-run; reusing
    #    it for "nothing collected" would make the empty plan a clean skip.
    if "skip_layer" in body:
        errors.append(
            "smoke_contracts() calls skip_layer: a layer that decides it has "
            "nothing to collect must fail, not skip -- SKIPPED is reported "
            "separately and never reddens the run"
        )

    # 4. The CI entry point runs the layer under `set -euo pipefail`, so the
    #    layer's non-zero status is the stage's status only while the call
    #    stays bare. `|| true`, a pipe or a redirect swallows it.
    try:
        ci_body = ci_contracts_function(ci_steps)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if not re.search(
            r'^[ \t]*bash[ \t]+"\$\{REPO_ROOT\}/scripts/smoke\.sh"'
            r"(?:[ \t]+--profile[ \t]+contracts)?[ \t]*$",
            ci_body,
            re.MULTILINE,
        ):
            errors.append(
                "the contracts layer call in scripts/ci-job-steps.sh "
                "(smoke_contracts_run) is not a bare statement: a chained, "
                "piped or redirected call turns an empty-layer failure into a "
                "green Contract suites stage"
            )
    return errors


def _self_test() -> int:
    smoke = SMOKE.read_text(encoding="utf-8")
    ci_steps = CI_STEPS.read_text(encoding="utf-8")
    clean = wiring_errors(smoke, ci_steps)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1
    results = 0
    failures = 0

    def report(passed: bool, ok_msg: str, fail_msg: str) -> None:
        nonlocal results, failures
        results += 1
        print(ok_msg if passed else fail_msg)
        if not passed:
            failures += 1

    try:
        body = contracts_function(smoke)
    except ValueError as exc:  # pragma: no cover - reported by wiring_errors
        print(f"FAIL self-test: {exc}")
        return 1

    self_line = next(
        (line for line in body.splitlines() if GUARD_CALL.fullmatch(line)), None
    )
    real_line = next(
        (
            line
            for line in body.splitlines()
            if REAL_CALL.fullmatch(line) and line != self_line
        ),
        None,
    )
    assert self_line is not None, (
        "self-test could not locate the guard self-test wiring"
    )
    assert real_line is not None, "self-test could not locate the guard real wiring"

    cases: list[tuple[str, str, str]] = [
        (
            "the layer stops auditing its own committed bytes",
            smoke.replace(real_line + "\n", "", 1),
            ci_steps,
        ),
        (
            "the layer stops proving the guard has a signal",
            smoke.replace(self_line + "\n", "", 1),
            ci_steps,
        ),
        (
            "the self-test wiring is neutralised with || true",
            smoke.replace(self_line, self_line.replace("|| rc=$?", "|| true"), 1),
            ci_steps,
        ),
        (
            "the self-test wiring redirects its diagnostics",
            smoke.replace(
                self_line, self_line.replace("--self-test", "--self-test >/dev/null"), 1
            ),
            ci_steps,
        ),
        (
            "the self-test wiring is commented out",
            smoke.replace(self_line, "  # " + self_line.strip(), 1),
            ci_steps,
        ),
        (
            "the self-test wiring is backgrounded",
            smoke.replace(
                self_line, self_line.replace("|| rc=$?", "&") + " || rc=$?", 1
            ),
            ci_steps,
        ),
        (
            "SMOKE PASS is printed regardless of the FAILED array",
            smoke.replace(
                'if [[ "${#FAILED[@]}" -gt 0 ]]; then',
                "if false; then",
                1,
            ),
            ci_steps,
        ),
    ]
    # A skip in place of a failure: the empty plan must redden, not be excused.
    cases.append(
        (
            "the layer reports an empty plan as a skip",
            smoke.replace(
                'echo "pytest is required for the contracts smoke layer" >&2',
                'skip_layer contracts "nothing collected"',
                1,
            ),
            ci_steps,
        )
    )
    # The CI side: the stage's status is the layer's status only while the call
    # is a bare statement.
    for label, suffix in {
        "|| true": " || true",
        "2>/dev/null": " 2>/dev/null",
        "a trailing comment": "  # ignore",
        "| tail -1": " | tail -1",
    }.items():
        layer = '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts'
        cases.append(
            (
                f"the CI layer call carries {label}",
                smoke,
                ci_steps.replace(layer, layer + suffix, 1),
            )
        )
    layer = '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
    cases.append(
        (
            "the CI layer call is deleted",
            smoke,
            ci_steps.replace(layer, "", 1),
        )
    )

    for label, mutated_smoke, mutated_ci in cases:
        found = wiring_errors(mutated_smoke, mutated_ci)
        report(
            bool(found),
            f"PASS self-test: {label} -> {len(found)} failure(s)",
            f"FAIL self-test: {label} was NOT caught",
        )

    print(f"self-test: {results} cases, {failures} failure(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test", action="store_true", help="run the mutation self-test"
    )
    args = parser.parse_args()
    smoke = SMOKE.read_text(encoding="utf-8")
    ci_steps = CI_STEPS.read_text(encoding="utf-8")
    if args.self_test:
        return _self_test()
    errors = wiring_errors(smoke, ci_steps)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"contracts empty-layer verdict: {len(errors)} failure(s)")
        return 1
    print(
        "contracts empty-layer verdict: OK (both entry points keep zero collected RED)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

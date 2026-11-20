"""Regression coverage for the discarded-verdict guard.

The guard is stdlib-only and runs before pytest is guaranteed. These tests
prove its failure directions from a second file, so a one-file edit to
``discarded_verdicts()`` cannot silence them: the decisive case is that a guard
which keeps its own ``--self-test`` green while throwing the verdict away is
still reported, and that a clean self-test is not.

The wiring half is read from the committed ``smoke.sh`` bytes, so a hand-merge
that drops the ``--self-test`` call is caught here too. The registry guard
pins that the call exists; this file pins that the call reaches a guard with a
signal.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_guard_self_test_verdict.py"

spec = importlib.util.spec_from_file_location("check_guard_self_test_verdict", GUARD_PATH)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


# The historical shape, verbatim: the status is initialised, the plants record
# their verdicts, and then the status is reset to a pass before the exit.
DISCARDING = """\
def _self_test():
    result = 0
    for label, planted in plants:
        problems = failures(planted)[0]
        if not problems:
            print(f"FAIL: {label} was not caught")
            result = 1
    result = 0
    for label, mutate in cases:
        if not mutate():
            result = 1
    return result
"""

HONEST = """\
def _self_test():
    result = 0
    for label, planted in plants:
        problems = failures(planted)[0]
        if not problems:
            print(f"FAIL: {label} was not caught")
            result = 1
    return result
"""


def test_a_discarded_verdict_is_reported() -> None:
    found = guard.discarded_verdicts(DISCARDING)
    assert len(found) == 1, found
    assert "'result'" in found[0]
    assert "discarded" in found[0]


def test_an_honest_self_test_is_not_reported() -> None:
    assert guard.discarded_verdicts(HONEST) == []


def test_a_sole_initialiser_is_not_a_reset() -> None:
    assert guard.discarded_verdicts("def _self_test():\n    result = 0\n    return result\n") == []


def test_a_counter_sharing_a_prefix_is_not_a_verdict() -> None:
    """``results = 0`` counts cases; reporting it would be a false positive."""
    source = (
        "def self_test():\n"
        "    results = 0\n"
        "    failures_seen = 0\n"
        "    for label in cases:\n"
        "        results += 1\n"
        "    return 1 if failures_seen else 0\n"
    )
    assert guard.discarded_verdicts(source) == []


def test_an_expression_status_is_not_a_reset() -> None:
    """``problems = [] if x else problems`` filters; it does not discard."""
    source = (
        "def self_test():\n"
        "    problems = ['a']\n"
        "    problems = [] if not problems else problems\n"
        "    return 1 if problems else 0\n"
    )
    assert guard.discarded_verdicts(source) == []


def test_the_fixed_enum_guard_is_clean_on_committed_bytes() -> None:
    """The guard that carried this bug now keeps its verdict."""
    path = ROOT / "scripts/check_openapi_published_enums.py"
    resolved = guard.resolve_status_source(path)
    assert resolved is not None
    assert guard.discarded_verdicts(resolved[1]) == []


def test_the_delegating_guard_is_followed_not_skipped() -> None:
    """``--self-test`` handed to another module still has a status to read."""
    path = ROOT / "scripts/check_mcp_manifest_reconcile.py"
    resolved = guard.resolve_status_source(path)
    assert resolved is not None
    label, source = resolved
    assert label == "test_mcp_manifest_reconcile.py"
    assert guard._status_function(__import__("ast").parse(source)) is not None


def test_an_unresolvable_guard_fails_closed(tmp_path: Path) -> None:
    stub = tmp_path / "check_stub.py"
    stub.write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    errors = guard.guard_errors(str(stub), root=tmp_path)
    assert errors and "no status function" in errors[0]


def test_a_clean_tree_passes() -> None:
    assert guard.check() == []


def test_the_guard_is_wired_into_the_contracts_layer() -> None:
    smoke = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    assert "scripts/check_guard_self_test_verdict.py --self-test" in smoke


def test_the_wired_call_gates_the_layer() -> None:
    """The call must be a bare ``|| rc=$?`` statement, not a swallowed one."""
    smoke = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    lines = [
        line
        for line in smoke.splitlines()
        if "check_guard_self_test_verdict.py --self-test" in line
    ]
    assert len(lines) == 1, lines
    assert lines[0].rstrip().endswith("|| rc=$?")


def test_the_guard_reports_a_drifted_tree_through_its_exit_code() -> None:
    """End to end: mutate a wired guard's bytes and read the real rc."""
    target = ROOT / "scripts/check_openapi_field_constraints.py"
    original = target.read_text(encoding="utf-8")
    anchor = '    print(f"self-test: {total} cases, {failures_count} failure(s)")'
    assert anchor in original
    planted = original.replace(
        anchor,
        '    failures_count = 0  # planted: the historical discarded-verdict shape\n' + anchor,
        1,
    )
    try:
        target.write_text(planted, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(GUARD_PATH)],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
            check=False,
        )
    finally:
        target.write_text(original, encoding="utf-8")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "discarded" in result.stdout + result.stderr


def test_removing_the_wire_is_reported() -> None:
    smoke = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    stripped = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_guard_self_test_verdict.py --self-test || rc=$?\n',
        "",
    )
    assert stripped != smoke
    assert guard.check(smoke=stripped) == []
    # The wire is gone, so the guard has nothing to audit there. The registry
    # guard owns the "call must exist" floor; this asserts the split, not a
    # second copy of that floor.
    assert guard.wired_self_tests(stripped) == [
        path
        for path in guard.wired_self_tests(smoke)
        if path != guard.SELF
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

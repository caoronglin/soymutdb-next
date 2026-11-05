#!/usr/bin/env python3
"""Regression contract for the wired --self-test teeth guard.

A second file must pin the wiring and the probe's teeth from outside the
guard, so a single-file edit cannot drop both the behaviour and its own
self-test plant. Collected by ``scripts/smoke.sh`` (``tests=()``).
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"
GUARD = ROOT / "scripts" / "check_contracts_self_test_teeth.py"

spec = importlib.util.spec_from_file_location("teeth_guard", GUARD)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def _smoke() -> str:
    return SMOKE.read_text(encoding="utf-8")


# One real probe per test process. Every test that needs clean results reuses
# it instead of spawning 13 guards again; the guard's own --self-test still
# runs its own probe when invoked as a process by smoke.sh.
_RESULTS: dict[str, tuple[int, str]] = {}


def _results() -> dict[str, tuple[int, str]]:
    if not _RESULTS:
        _RESULTS.update(guard.probe(guard.wired_self_tests(_smoke())))
    return dict(_RESULTS)


class TeethGuardContract(unittest.TestCase):
    def test_committed_tree_is_clean(self) -> None:
        self.assertEqual(guard.check(smoke=_smoke(), results=_results()), [])

    def test_the_guard_is_wired_into_the_contracts_layer(self) -> None:
        smoke = _smoke()
        call = (
            '  "${PYTHON_BIN}" scripts/check_contracts_self_test_teeth.py '
            "--self-test || rc=$?\n"
        )
        self.assertIn(call, smoke, "standalone --self-test call was dropped")
        body = smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(call, body, "the call sits outside smoke_contracts()")
        self.assertIn(
            "scripts/test_contracts_self_test_teeth.py",
            body,
            "companion suite is not collected in tests=()",
        )

    def test_the_wire_propagates_its_status(self) -> None:
        call = (
            '  "${PYTHON_BIN}" scripts/check_contracts_self_test_teeth.py '
            "--self-test || rc=$?\n"
        )
        self.assertIn(call, _smoke())
        self.assertNotIn(
            '  "${PYTHON_BIN}" scripts/check_contracts_self_test_teeth.py '
            "--self-test || true\n",
            _smoke(),
            "a swallowed status keeps SMOKE PASS while the probe is dead",
        )

    def test_the_guard_is_pinned_in_the_registry_floor(self) -> None:
        registry = importlib.util.spec_from_file_location(
            "registry_guard", ROOT / "scripts" / "check_contracts_registry_collection.py"
        )
        assert registry and registry.loader
        mod = importlib.util.module_from_spec(registry)
        registry.loader.exec_module(mod)
        self.assertIn(
            "scripts/check_contracts_self_test_teeth.py",
            mod.REQUIRED_GUARD_CALLS,
            "a wired guard outside REQUIRED_GUARD_CALLS fails #223's floor",
        )

    def test_the_literal_floor_cannot_be_derived_from_the_layer(self) -> None:
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("_WIRED_SELF_TESTS: frozenset[str] = frozenset(", source)
        self.assertIn("_SIGNATURES: dict[str, re.Pattern[str]] = {", source)
        self.assertGreaterEqual(len(guard._WIRED_SELF_TESTS), 10)

    def test_a_no_op_self_test_is_rejected(self) -> None:
        wired = guard.wired_self_tests(_smoke())
        gutted = dict(_results())
        gutted["scripts/check_app_shell_assets.py"] = (0, "")
        found = guard.teeth_errors(wired, gutted)
        self.assertTrue(
            any("no pinned evidence" in f for f in found),
            "a no-op self-test must not be accepted",
        )

    def test_a_failing_self_test_is_rejected(self) -> None:
        wired = guard.wired_self_tests(_smoke())
        results = dict(_results())
        results["scripts/check_openapi_baseline_sync.py"] = (1, "boom")
        self.assertTrue(
            any(
                "check_openapi_baseline_sync.py" in f
                for f in guard.teeth_errors(wired, results)
            )
        )

    def test_dropping_a_wire_is_rejected(self) -> None:
        smoke = _smoke()
        dropped = smoke.replace(
            '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n',
            "",
            1,
        )
        self.assertNotEqual(dropped, smoke, "setup is not a control")
        self.assertTrue(
            any(
                "was dropped" in f
                for f in guard.floor_errors(guard.wired_self_tests(dropped))
            )
        )

    def test_an_unpinned_wire_is_rejected(self) -> None:
        smoke = _smoke()
        added = smoke.replace(
            '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n',
            '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n'
            '  "${PYTHON_BIN}" scripts/check_new_guard.py --self-test || rc=$?\n',
            1,
        )
        self.assertNotEqual(added, smoke, "setup is not a control")
        self.assertTrue(
            any(
                "not pinned" in f
                for f in guard.floor_errors(guard.wired_self_tests(added))
            )
        )

    def test_removing_a_signature_is_rejected(self) -> None:
        smoke = _smoke()
        source = GUARD.read_text(encoding="utf-8")
        # A guard pinned in the floor but with no success signature is a
        # fail-closed error, not a silent skip.
        removed = source.replace(
            '    "scripts/check_visible_i18n.py": re.compile(r"visible i18n self-test passed"),\n',
            "",
            1,
        )
        self.assertNotEqual(removed, source, "setup is not a control")
        # Re-evaluate floor_errors with the signature table emptied for one key.
        original = guard._SIGNATURES
        guard._SIGNATURES = dict(original)
        guard._SIGNATURES.pop("scripts/check_visible_i18n.py")
        try:
            found = guard.floor_errors(guard.wired_self_tests(smoke))
        finally:
            guard._SIGNATURES = original
        self.assertTrue(any("no success signature" in f for f in found))

    def test_the_guards_own_self_test_has_teeth(self) -> None:
        # The --self-test must actually plant a no-op and catch it. A body that
        # only prints PASS lines without asserting would still exit 0.
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("control = probe(wired)", source)
        self.assertIn("if teeth_errors(wired, control):", source)
        self.assertIn("len(lost) == 1 and not others", source)


if __name__ == "__main__":
    unittest.main()

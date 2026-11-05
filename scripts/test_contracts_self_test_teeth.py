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
# it instead of spawning every wired guard again; the guard's own --self-test still
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

    def test_a_reachable_but_unreached_ablation_set_is_rejected(self) -> None:
        """The #256-forgery: keep the cases dict, empty the loop, print a count.

        A signature can only pin the shape of the success line, and the guard
        writes that line from a number it chooses. This shape is what the
        printed evidence cannot distinguish from a real run, so the source is
        read instead: the declared ablations have to be *reached*.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            target = tree / "scripts/check_error_code_catalog.py"
            target.parent.mkdir(parents=True)
            text = (ROOT / "scripts/check_error_code_catalog.py").read_text(encoding="utf-8")
            forged = text.replace(
                "    for name, plant in cases.items():", "    for name, plant in []:", 1
            )
            self.assertNotEqual(forged, text, "setup is not a control")
            target.write_text(forged, encoding="utf-8")
            found = guard.declared_case_errors(tree)
        self.assertTrue(
            any("no longer iterates its cases mapping" in f for f in found),
            f"an emptied self-test loop must be rejected, got {found}",
        )

    def test_the_case_floor_is_read_from_source_not_from_output(self) -> None:
        """Dropping the ablations entirely is the other half of the same hole."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            target = tree / "scripts/check_error_code_catalog.py"
            target.parent.mkdir(parents=True)
            text = (ROOT / "scripts/check_error_code_catalog.py").read_text(encoding="utf-8")
            start = text.index("    cases = {")
            end = text.index("\n    }\n", start) + len("\n    }\n")
            target.write_text(text[:start] + "    cases = {}\n" + text[end:], encoding="utf-8")
            found = guard.declared_case_errors(tree)
        self.assertTrue(
            any("below the pinned floor" in f for f in found),
            f"an emptied cases dict must be rejected, got {found}",
        )

    def test_the_committed_tree_declares_its_ablations(self) -> None:
        self.assertEqual(guard.declared_case_errors(), [])

    def test_a_summary_only_self_test_is_rejected(self) -> None:
        """The evidence floor: N declared cases need N per-case lines.

        A body gutted to ``print(<pinned summary>); return 0`` keeps both the
        signature and the count, because both are strings a mutator copies. The
        lines it does not print are the only thing a stub cannot fake.
        """
        target = "scripts/check_openapi_response_surface.py"
        self.assertIn(target, guard._EVIDENCE_PER_CASE, "setup is not a control")
        forged = (0, "self-test: 10 cases, 0 failure(s)\n")
        self.assertEqual(guard.evidence_lines(forged[1]), (10, 0))
        found = guard.evidence_errors({target: forged})
        self.assertTrue(
            any("printed 0 per-case line(s)" in f for f in found),
            f"a summary-only self-test must be rejected, got {found}",
        )

    def test_the_evidence_floor_is_clean_on_the_committed_tree(self) -> None:
        self.assertEqual(guard.evidence_errors(_results()), [])

    def test_every_evidence_row_states_its_declared_count(self) -> None:
        """A row whose success line declares nothing enforces nothing."""
        for path, (rc, output) in sorted(_results().items()):
            if path not in guard._EVIDENCE_PER_CASE or rc != 0:
                continue
            self.assertIsNotNone(
                guard._declared_case_count(output),
                f"{path} is in _EVIDENCE_PER_CASE but declares no case count",
            )

    def test_evidence_for_guards_outside_the_floor_is_not_audited(self) -> None:
        """Otherwise this becomes a format audit of every wired self-test."""
        thin = "scripts/check_app_shell_assets.py"
        self.assertNotIn(thin, guard._EVIDENCE_PER_CASE, "setup is not a control")
        self.assertEqual(guard.evidence_errors({thin: (0, "self-test: 9 cases\n")}), [])
        self.assertNotIn("check_app_shell_assets.py", str(guard.evidence_errors(_results())))

    def test_a_legitimate_count_increase_stays_green(self) -> None:
        """An added ablation moves both numbers; neither is pinned."""
        target = "scripts/check_openapi_response_surface.py"
        declared, emitted = guard.evidence_lines(_results()[target][1])
        self.assertGreaterEqual(emitted, declared or 0, "setup is not a control")
        widened = f"self-test: {emitted + 5} cases, 0 failure(s)\n" + "\n".join(
            f"PASS self-test: case {i} is caught -> 1 failure(s)" for i in range(emitted + 5)
        )
        self.assertEqual(guard.evidence_errors({target: (0, widened)}), [])

    def test_a_failing_evidence_row_is_reported_by_teeth_not_here(self) -> None:
        """One cause, one owner: an unreachable self-test is teeth_errors'."""
        target = "scripts/check_openapi_response_surface.py"
        self.assertEqual(guard.evidence_errors({target: (1, "boom")}), [])

    def test_an_ambiguous_count_is_rejected(self) -> None:
        """``5 cases`` next to ``7 cases`` is not one answer to "how many"."""
        self.assertIsNone(guard._declared_case_count("self-test: 5 cases, 7 cases\n"))
        self.assertEqual(guard._declared_case_count("self-test: 5 cases\n"), 5)
        self.assertEqual(guard._declared_case_count("self-test: 12 negative cases + clean\n"), 12)
        self.assertEqual(guard._declared_case_count("SELF-TEST PASS: 9 mutations\n"), 9)

    def test_the_guards_own_self_test_has_teeth(self) -> None:
        # The --self-test must actually plant a no-op and catch it. A body that
        # only prints PASS lines without asserting would still exit 0.
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("control = probe(wired)", source)
        self.assertIn("if teeth_errors(wired, control):", source)
        self.assertIn("len(lost) == 1 and not others", source)


if __name__ == "__main__":
    unittest.main()

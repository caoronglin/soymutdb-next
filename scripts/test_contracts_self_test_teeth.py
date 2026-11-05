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
        self.assertIn(target, guard.EVIDENCE_MEMBERS, "setup is not a control")
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
            if path not in guard.EVIDENCE_MEMBERS or rc != 0:
                continue
            self.assertIsNotNone(
                guard._declared_case_count(output),
                f"{path} is in EVIDENCE_MEMBERS but declares no case count",
            )

    def test_evidence_for_guards_outside_the_floor_is_not_audited(self) -> None:
        """Otherwise this becomes a format audit of every wired self-test."""
        thin = "scripts/check_app_shell_assets.py"
        self.assertNotIn(thin, guard.EVIDENCE_MEMBERS, "setup is not a control")
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

    def test_a_loop_shrunken_below_the_reviewed_floor_is_rejected(self) -> None:
        """A loop-counter summary shrinks declared and emitted together.

        ``check_openapi_operation_id_floor.py`` prints ``{results}``, so an
        edited loop that runs N-1 cases prints ``N-1 cases`` with N-1 per-case
        lines. ``emitted < declared`` never fires; the literal ``_CASE_FLOOR``
        is what still names it. Both limbs are asserted: the short run is
        coherent on the one-sided check, and the floor reports it.
        """
        target = "scripts/check_openapi_operation_id_floor.py"
        self.assertIn(target, guard.EVIDENCE_MEMBERS, "setup is not a control")
        floor = guard._CASE_FLOOR[target][3]
        few = floor - 1
        output = f"self-test: {few} cases, 0 failure(s)\n" + "\n".join(
            f"PASS self-test: case {i} is caught -> 1 failure(s)" for i in range(few)
        )
        self.assertEqual(guard.evidence_lines(output), (few, few))
        found = guard.evidence_errors({target: (0, output)})
        self.assertEqual(len(found), 1, "one cause, one owner")
        self.assertIn(f"below its reviewed floor of {floor}", found[0])

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

    def test_every_wire_carries_both_plants(self) -> None:
        # A guard whose plain run can be gutted while its self-test replays
        # PASS lines is the shape the signature floor cannot see. Nothing is
        # exempt: the two sets are checked against each other and the wire set.
        wired = guard.wired_self_tests(_smoke())
        for path in sorted(wired):
            self.assertIn(path, guard._DRIFT_COVERED, f"{path} has no detection plant")
            self.assertIn(path, guard._GUT_COVERED, f"{path} has no self-test plant")
        self.assertEqual(guard.drift_floor_errors(), [])

    def test_a_gutted_entry_point_keeps_the_self_test_green(self) -> None:
        # Two limbs, or the case tests the detection plant twice: the replayed
        # self-test must still satisfy the signature floor, and the plain run
        # must be the thing that catches it.
        wired = guard.wired_self_tests(_smoke())
        gutted = "scripts/check_error_code_catalog.py"
        replayed = (
            0,
            "  ok: planted 'extra code' -> caught (1 problem(s))\n"
            "error-code catalog self-test passed (12 negative cases + clean tree)\n",
        )
        self.assertEqual(guard.teeth_errors(wired, {**_results(), gutted: replayed}), [])
        planted = {(gutted, "self-test"): replayed, (gutted, "plain"): (1, "")}
        caught = guard.gut_errors(wired, planted)
        self.assertTrue(any(gutted in f for f in caught), caught)

    def test_an_unplanted_entry_point_gut_is_reported(self) -> None:
        # One cause, one owner: the plain run staying green after the plant is
        # the failure this leg exists for.
        self.assertIn(
            "still failed its plain run",
            " ".join(
                guard.gut_errors(
                    guard.wired_self_tests(_smoke()),
                    {
                        ("scripts/check_error_code_catalog.py", "self-test"): (0, ""),
                        ("scripts/check_error_code_catalog.py", "plain"): (1, ""),
                    },
                )
            ),
        )

    def test_every_evidence_member_pins_a_case_floor(self) -> None:
        """An audited per-case guard with no _CASE_FLOOR row fails closed."""
        self.assertEqual(guard.evidence_floor_errors(), [])
        self.assertEqual(set(guard._CASE_FLOOR), set(guard.EVIDENCE_MEMBERS))
        original = guard._CASE_FLOOR
        guard._CASE_FLOOR = dict(original)
        guard._CASE_FLOOR.pop("scripts/check_openapi_operation_id_floor.py")
        try:
            found = guard.evidence_floor_errors()
        finally:
            guard._CASE_FLOOR = original
        self.assertTrue(
            any("has no _CASE_FLOOR row" in f for f in found),
            f"an audited guard without a floor must be named, got {found}",
        )

    def test_a_deleted_case_is_reported_by_name(self) -> None:
        """Both plants disable a check or an entry point, not a case."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            target = tree / "scripts/check_openapi_operation_id_floor.py"
            target.parent.mkdir(parents=True)
            text = (ROOT / "scripts/check_openapi_operation_id_floor.py").read_text(
                encoding="utf-8"
            )
            anchor = (
                '    cases.append(\n        (\n'
                '            "a coordinated operationId retype in both halves"'
            )
            start = text.index(anchor)
            end = text.index("    # 2. Snapshot-only retype", start)
            deleted = text[:start] + text[end:]
            self.assertNotEqual(deleted, text, "setup is not a control")
            target.write_text(deleted, encoding="utf-8")
            found = guard.declared_case_errors(tree)
        self.assertTrue(
            any("below the pinned floor" in f for f in found),
            f"a deleted case must be named, got {found}",
        )

    def test_the_case_floor_is_a_literal_not_derived_from_output(self) -> None:
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("_CASE_FLOOR: dict[str, tuple[str, str, str, int]] = {", source)
        self.assertIn("declared = _declared_cases(target, function, mapping)", source)
        self.assertIn("evidence_floor_errors()", source)
        self.assertIn("floor = _CASE_FLOOR.get(path)", source)
        self.assertIn("emitted < floor[3]", source)

    def test_the_re_pin_case_is_load_bearing_from_a_second_file(self) -> None:
        """Both limbs of the coordinated retype must live in the case list."""
        for name in (
            "check_openapi_operation_id_floor.py",
            "check_openapi_operation_parameter_floor.py",
        ):
            source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("with its digest re-pinned", source)
            self.assertIn("expect_clean=True", source)
            self.assertIn('kwargs.pop("expect_clean", False)', source)
    def test_every_gut_anchor_sits_on_the_plain_run_path(self) -> None:
        # A gut registered against self_test() cannot reach the plain run, and
        # gut_probe() only reads exit codes: plain_rc == 0 then means either
        # "the guard survived" or "the plant never ran". Fail closed on the
        # source shape so a new wire cannot reintroduce the empty leg silently.
        self.assertEqual(guard.gut_anchor_errors(), [])
        for path, _fragment, _replacement in guard._SELF_TEST_GUTS:
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertIn(
                "def main(", source, f"{path} has no plain-run entry point"
            )

    def test_a_self_test_scoped_gut_anchor_is_reported_by_name(self) -> None:
        # From a second file: point one registered anchor back at self_test()
        # and the structural check must name it, not stay green on exit codes.
        path = "scripts/check_error_code_catalog.py"
        original = guard._SELF_TEST_GUTS
        try:
            guard._SELF_TEST_GUTS = tuple(
                (p, "    clean = check_tree(ROOT)\n", r) if p == path else (p, f, r)
                for p, f, r in original
            )
            found = guard.gut_anchor_errors()
            self.assertTrue(any(path in f and "not in main()" in f for f in found), found)
        finally:
            guard._SELF_TEST_GUTS = original

    def test_the_guards_own_self_test_has_teeth(self) -> None:
        # The --self-test must actually plant a no-op and catch it. A body that
        # only prints PASS lines without asserting would still exit 0.
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("control = probe(wired)", source)
        self.assertIn("if teeth_errors(wired, control):", source)
        self.assertIn("len(lost) == 1 and not others", source)

    def test_both_calls_floor_is_a_hand_written_literal(self) -> None:
        """A floor derived from the layer would green-light its own deletion."""
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("BOTH_CALLS: frozenset[str] = frozenset(", source)
        self.assertIn("both_call_errors(text, wired)", source)
        self.assertEqual(
            guard.BOTH_CALLS,
            {
                "scripts/check_api_error_code_vocabulary.py",
                "scripts/check_error_code_catalog.py",
                "scripts/check_variant_summary_assembly_consistency.py",
            },
        )

    def test_committed_layer_has_every_pinned_plain_run(self) -> None:
        smoke = _smoke()
        self.assertIn(
            "scripts/check_variant_summary_assembly_consistency.py",
            guard.plain_guard_calls(smoke),
        )
        self.assertEqual(
            guard.both_call_errors(smoke, guard.wired_self_tests(smoke)), []
        )

    def test_deleting_a_pinned_plain_run_is_named(self) -> None:
        """The registry floor pins a path, not a call count: deletion is green."""
        smoke = _smoke()
        victim = "scripts/check_variant_summary_assembly_consistency.py"
        dropped = "\n".join(
            line for line in smoke.splitlines()
            if line.strip() != f'"${{PYTHON_BIN}}" {victim} || rc=$?'
        ) + "\n"
        self.assertNotEqual(dropped, smoke, "setup is not a control")
        found = guard.both_call_errors(dropped, guard.wired_self_tests(dropped))
        self.assertTrue(any(victim in f and "lost its plain run" in f for f in found), found)

    def test_an_unpinned_plain_run_fails_closed(self) -> None:
        """A new second call without a pin is reported, not silently adopted."""
        smoke = _smoke()
        extra = (
            '  "${PYTHON_BIN}" scripts/check_openapi_response_surface.py '
            '|| rc=$?\n'
        )
        added = smoke.replace(
            '  "${PYTHON_BIN}" scripts/check_openapi_response_surface.py '
            '--self-test || rc=$?\n',
            '  "${PYTHON_BIN}" scripts/check_openapi_response_surface.py '
            '--self-test || rc=$?\n' + extra,
            1,
        )
        self.assertNotEqual(added, smoke, "setup is not a control")
        found = guard.both_call_errors(added, guard.wired_self_tests(added))
        self.assertTrue(any("not in BOTH_CALLS" in f for f in found), found)

    def test_the_deletion_ablation_reaches_the_guards_own_self_test(self) -> None:
        source = GUARD.read_text(encoding="utf-8")
        self.assertIn("dropped_plain != smoke", source)
        self.assertIn("both_call_errors(dropped_plain, wired)", source)


if __name__ == "__main__":
    unittest.main()

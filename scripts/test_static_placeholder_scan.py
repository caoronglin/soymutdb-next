#!/usr/bin/env python3
"""Wiring + non-vacuity pin for the static placeholder-scan guard.

``check_static_placeholder_scan.py`` pins both scanners' token floors and
their corpora against reviewed literals, and reads the behavioural suite back
for both marker literals and a real rejection assertion. It only helps if
(a) the contracts layer actually runs it, (b) its call is pinned in
``REQUIRED_GUARD_CALLS``, (c) its own ``--self-test`` still fails on a one-sided
drift, (d) the pinned corpora are not silently mutable, and (e) the assertion
floor itself is not vacuous. Each is asserted here from a second file, so
deleting a pin, dropping the wire, gutting the self-test, drifting an
``--include`` set or deleting the behavioural assertion fails the contracts
layer instead of shipping a green layer with an unguarded scanner (§4a, PR #206).

Stdlib only. Run directly or collect with pytest.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_static_placeholder_scan.py"
SMOKE = ROOT / "scripts" / "smoke.sh"
REGISTRY = ROOT / "scripts" / "check_contracts_registry_collection.py"
SELF = Path(__file__).name

_spec = importlib.util.spec_from_file_location("check_static_placeholder_scan", GUARD)
assert _spec and _spec.loader
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


class TestStaticPlaceholderScan(unittest.TestCase):
    def test_guard_exists_and_layer_runs_it(self) -> None:
        self.assertTrue(GUARD.is_file())
        smoke = SMOKE.read_text(encoding="utf-8")
        self.assertIn("scripts/check_static_placeholder_scan.py || rc=$?", smoke)
        # It must sit inside smoke_contracts(), not some other layer.
        body = smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("check_static_placeholder_scan.py", body)

    def test_call_is_pinned_in_registry_floor(self) -> None:
        spec = importlib.util.spec_from_file_location("registry", REGISTRY)
        assert spec and spec.loader
        registry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)
        self.assertIn(
            "scripts/check_static_placeholder_scan.py",
            registry.REQUIRED_GUARD_CALLS,
        )

    def test_committed_bytes_are_clean(self) -> None:
        self.assertEqual(module.check(), [])

    def test_witness_rejects_a_byte_intact_but_blind_scanner(self) -> None:
        """Pinned tokens + corpora are bytes; a scanner can keep all of them
        and still match nothing. Adding --exclude='*' to the decision grep
        must be caught behaviourally, not by the byte floor."""
        smoke = SMOKE.read_text(encoding="utf-8")
        blind = smoke.replace(
            " --include='*.json' >/dev/null 2>&1; then",
            " --include='*.json' --exclude='*' >/dev/null 2>&1; then",
            1,
        )
        self.assertNotEqual(blind, smoke, "the plant changed nothing")
        self.assertEqual(module.check(blind, witness_scan=False), [],
                         "the byte pin must be green for this plant to prove the witness")
        problems = module.witness(blind)
        self.assertTrue(any("stayed green" in e for e in problems), problems)
        self.assertEqual(module.check(blind, witness_scan=True), problems)

    def test_witness_requires_a_clean_control(self) -> None:
        """A broken clean control must not read as 'four drifts caught'."""
        smoke = SMOKE.read_text(encoding="utf-8").replace(
            '  [[ -d "${dir}" ]] ||', "  false ||", 1,
        )
        self.assertNotEqual(smoke, SMOKE.read_text(encoding="utf-8"))
        problems = module.witness(smoke)
        self.assertTrue(any("clean control is not green" in e for e in problems), problems)

    def test_self_test_has_teeth(self) -> None:
        # Exercised in-process, like test_contracts_registry_collection.py:
        # wiring a second --self-test call here would need a row in the teeth
        # guard's _WIRED_SELF_TESTS floor, which other in-flight PRs owned.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.self_test()
        out = buf.getvalue()
        self.assertEqual(rc, 0, out)
        self.assertIn("cases, 0 failure(s)", out)
        # Each plant must actually have produced a PASS line.
        passes = [l for l in out.splitlines() if l.startswith("PASS self-test:")]
        self.assertGreaterEqual(len(passes), 5, out)

    def test_self_test_rejects_a_gutted_check(self) -> None:
        """Weakening check() to return [] must make the self-test fail."""
        original = module.check
        module.check = lambda *a, **k: []  # type: ignore[assignment]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = module.self_test()
        finally:
            module.check = original
        self.assertNotEqual(rc, 0, "a vacuous self-test passed")

    def test_corpora_are_pinned_and_not_equal(self) -> None:
        """The two scanners' corpora are reviewed, different, and non-empty."""
        smoke = SMOKE.read_text(encoding="utf-8")
        corpus = module.smoke_greps(smoke)
        self.assertEqual(len(corpus), 2)
        for _, includes in corpus:
            self.assertEqual(includes, module.SMOKE_CORPUS)
        self.assertNotIn("_headers", includes)
        self.assertEqual(module.PRODUCTION_CORPUS, frozenset())
        self.assertEqual(
            module.PRODUCTION_SCAN_EXCLUDES,
            frozenset({"manifest.json", "SHA256SUMS"}),
        )
        self.assertEqual(len(module.PRODUCTION_LOOPBACK_EXCLUDES), 5)
        # The pin must not bless an equality the bytes do not have.
        self.assertNotEqual(set(module.SMOKE_CORPUS), module.PRODUCTION_CORPUS)

    def test_smoke_include_drift_is_detected(self) -> None:
        """A widened --include set must be reported as a divergence."""
        smoke = SMOKE.read_text(encoding="utf-8")
        widened = smoke.replace(
            "--include='*.json'", "--include='*.json' --include='_headers'",
        )
        errors = module.check(smoke=widened)
        self.assertTrue(
            any("corpus drifted" in e for e in errors), errors,
        )

    def test_production_loopback_corpus_is_read_back(self) -> None:
        """Dropping a scan_loopback() --exclude must be a divergence too."""
        production = (ROOT / "scripts" / "check-production-artifact.sh").read_text(
            encoding="utf-8",
        )
        narrowed = production.replace("      --exclude='*.map' \\\n", "", 1)
        errors = module.check(production=narrowed)
        self.assertTrue(
            any("corpus drifted" in e for e in errors), errors,
        )

    def test_self_test_plants_each_corpus_drift(self) -> None:
        """Each of the three corpus drifts must produce its own PASS line."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module.self_test()
        self.assertEqual(rc, 0, buf.getvalue())
        corpus_passes = [
            line for line in buf.getvalue().splitlines()
            if line.startswith("PASS self-test:")
            and ("corpus" in line or "_headers" in line)
        ]
        self.assertGreaterEqual(len(corpus_passes), 3, buf.getvalue())

    def test_rejection_floor_pins_signal_not_literals(self) -> None:
        """The read-back floor must reject an assertion-deleted suite.

        Literal presence is not signal: every marker (and the scan() call) can
        survive while the one assertion that fails a broken scanner is gone.
        A gutted rejection_is_asserted() returning True must be caught too,
        or this floor is as vacuous as the bytes it replaces.
        """
        behaviour = (ROOT / "scripts" / "test_production_artifact_scan.py").read_text(
            encoding="utf-8"
        )
        assertion = (
            "    assert result.returncode == 1, "
            "(marker, result.stdout, result.stderr)\n"
        )
        self.assertIn(assertion, behaviour, "ablation anchor moved")
        self.assertTrue(module.rejection_is_asserted(behaviour))
        gutted = behaviour.replace(assertion, "", 1)
        self.assertEqual(
            module.check(behaviour=gutted, witness_scan=False),
            [
                "test_production_artifact_scan.py no longer asserts that the "
                "scanner rejects a planted marker (returncode == 1)"
            ],
        )
        # A commented-out assertion is still not signal.
        commented = behaviour.replace(assertion, "    # " + assertion.strip() + "\n", 1)
        self.assertIn(
            "no longer asserts",
            " ".join(module.check(behaviour=commented, witness_scan=False)),
        )

        original = module.rejection_is_asserted
        module.rejection_is_asserted = lambda _b: True  # type: ignore[assignment]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = module.self_test()
        finally:
            module.rejection_is_asserted = original
        self.assertNotEqual(rc, 0, "a vacuous assertion floor passed")

    def test_companion_suite_is_collected(self) -> None:
        smoke = SMOKE.read_text(encoding="utf-8")
        body = smoke.split("smoke_contracts() {", 1)[1]
        block = body.split("environment_bound=(", 1)[0]
        self.assertIn(f"    scripts/{SELF}\n", block)


if __name__ == "__main__":
    unittest.main()

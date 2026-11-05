#!/usr/bin/env python3
"""Wiring + non-vacuity pin for the static placeholder-scan guard.

``check_static_placeholder_scan.py`` pins both copies of the placeholder-origin
regex against a reviewed floor. It only helps if (a) the contracts layer
actually runs it, (b) its call is pinned in ``REQUIRED_GUARD_CALLS``, and (c)
its own ``--self-test`` still fails on a one-sided drift. Each is asserted here
from a second file, so deleting a pin, dropping the wire, or gutting the
self-test fails the contracts layer instead of shipping a green layer with an
unguarded scanner (§4a, PR #206).

Stdlib only. Run directly or collect with pytest.
"""
from __future__ import annotations

import importlib.util
import io
import contextlib
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

    def test_self_test_has_teeth(self) -> None:
        # Exercised in-process, like test_contracts_registry_collection.py:
        # wiring a second --self-test call here would need a row in the teeth
        # guard's _WIRED_SELF_TESTS floor, which three in-flight PRs own.
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

    def test_companion_suite_is_collected(self) -> None:
        smoke = SMOKE.read_text(encoding="utf-8")
        body = smoke.split("smoke_contracts() {", 1)[1]
        block = body.split("environment_bound=(", 1)[0]
        self.assertIn(f"    scripts/{SELF}\n", block)


if __name__ == "__main__":
    unittest.main()

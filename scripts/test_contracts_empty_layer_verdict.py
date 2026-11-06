#!/usr/bin/env python3
"""Regression contract for the empty-layer verdict guard.

The guard pins "zero collected never reads green" on both contracts entry
points (``scripts/smoke.sh`` and ``scripts/ci-job-steps.sh``). This file pins
it from the outside, so a single edit cannot drop the guard, its wiring and its
own self-test plant together. Collected by ``scripts/smoke.sh`` (``tests=()``).

The behavioural cases run the real ``smoke.sh`` in a scratch copy: the verdict
is a property of executed bash, and a text-only assertion would be the very
shape this repository keeps getting bitten by.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"
CI_STEPS = ROOT / "scripts" / "ci-job-steps.sh"
GUARD = ROOT / "scripts" / "check_contracts_empty_layer_verdict.py"

spec = importlib.util.spec_from_file_location("empty_layer_guard", GUARD)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def _smoke() -> str:
    return SMOKE.read_text(encoding="utf-8")


def _ci() -> str:
    return CI_STEPS.read_text(encoding="utf-8")


def _contracts_body(smoke: str) -> str:
    return smoke.split("smoke_contracts() {", 1)[1].split("\n}\n", 1)[0]


class EmptyLayerVerdictContract(unittest.TestCase):
    def test_committed_tree_is_clean(self) -> None:
        self.assertEqual(guard.wiring_errors(_smoke(), _ci()), [])

    def test_the_guard_is_wired_twice_inside_the_contracts_layer(self) -> None:
        body = _contracts_body(_smoke())
        self.assertIn(
            '  "${PYTHON_BIN}" scripts/check_contracts_empty_layer_verdict.py '
            "--self-test || rc=$?\n",
            body,
            "the self-test wiring was dropped or moved outside smoke_contracts()",
        )
        self.assertIn(
            '  "${PYTHON_BIN}" scripts/check_contracts_empty_layer_verdict.py '
            "|| rc=$?\n",
            body,
            "the plain run was dropped: the layer proves the guard has a signal "
            "but never audits the committed scripts",
        )
        # The companion row is what makes the guard's own red block a run; a
        # wired guard with no collected suite can be gutted in one edit.
        registry_spec = importlib.util.spec_from_file_location(
            "registry_guard_rows",
            ROOT / "scripts" / "check_contracts_registry_collection.py",
        )
        assert registry_spec and registry_spec.loader
        registry = importlib.util.module_from_spec(registry_spec)
        registry_spec.loader.exec_module(registry)
        self.assertIn(
            "scripts/test_contracts_empty_layer_verdict.py",
            registry.registry(_smoke()),
            "the companion suite is not collected by the contracts layer",
        )

    def test_the_self_test_wiring_precedes_the_gating_pytest_call(self) -> None:
        body = _contracts_body(_smoke())
        wire = body.index("check_contracts_empty_layer_verdict.py --self-test")
        gating = body.index('-m pytest "${tests[@]}"')
        self.assertLess(
            wire,
            gating,
            "the verdict must be pinned before the layer decides to run nothing",
        )

    def test_the_ci_entry_point_pins_the_verdict_before_the_layer(self) -> None:
        ci_body = _ci().split("smoke_contracts_run() {", 1)[1].split("\n}\n", 1)[0]
        line = (
            '  python3 "${REPO_ROOT}/scripts/check_contracts_empty_layer_verdict.py" '
            "--self-test\n"
        )
        self.assertIn(line, ci_body, "the CI-side pin was dropped or neutralised")
        layer = ci_body.index('bash "${REPO_ROOT}/scripts/smoke.sh"')
        self.assertLess(
            ci_body.index(line),
            layer,
            "the pin runs after the layer it is supposed to gate",
        )

    def test_the_guard_is_pinned_in_the_registry_floor(self) -> None:
        registry_spec = importlib.util.spec_from_file_location(
            "registry_guard",
            ROOT / "scripts" / "check_contracts_registry_collection.py",
        )
        assert registry_spec and registry_spec.loader
        registry = importlib.util.module_from_spec(registry_spec)
        registry_spec.loader.exec_module(registry)
        self.assertIn(
            "scripts/check_contracts_empty_layer_verdict.py",
            registry.REQUIRED_GUARD_CALLS,
            "a wired guard outside REQUIRED_GUARD_CALLS can be dropped silently",
        )

    def test_a_dropped_wire_is_rejected(self) -> None:
        smoke = _smoke()
        wire = (
            '  "${PYTHON_BIN}" scripts/check_contracts_empty_layer_verdict.py '
            "|| rc=$?\n"
        )
        self.assertNotEqual(smoke.replace(wire, "", 1), smoke, "setup is not a control")
        self.assertTrue(guard.wiring_errors(smoke.replace(wire, "", 1), _ci()))

    def test_a_skip_in_place_of_the_empty_plan_failure_is_rejected(self) -> None:
        smoke = _smoke()
        mutated = smoke.replace(
            'echo "pytest is required for the contracts smoke layer" >&2',
            'skip_layer contracts "nothing collected"',
            1,
        )
        self.assertNotEqual(mutated, smoke, "setup is not a control")
        self.assertTrue(guard.wiring_errors(mutated, _ci()))

    def test_an_unconditional_pass_banner_is_rejected(self) -> None:
        smoke = _smoke()
        mutated = smoke.replace(
            'if [[ "${#FAILED[@]}" -gt 0 ]]; then', "if false; then", 1
        )
        self.assertNotEqual(mutated, smoke, "setup is not a control")
        self.assertTrue(guard.wiring_errors(mutated, _ci()))

    def test_a_neutralised_ci_layer_call_is_rejected(self) -> None:
        line = '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts'
        mutated = _ci().replace(line, line + " || true", 1)
        self.assertNotEqual(mutated, _ci(), "setup is not a control")
        self.assertTrue(guard.wiring_errors(_smoke(), mutated))


class EmptyPlanIsRedOnBothEntryPoints(unittest.TestCase):
    """Execute the real entry points with a plan that collects nothing.

    ``SOYMUTDB_SMOKE_PYTHON`` is the layer's own interpreter selector, so the
    scratch copy runs under the interpreter that runs this suite: no workspace
    install, no venv, no fixture in the repository. ``PYTHONPATH`` is stripped
    so a leaked ``sitecustomize`` cannot change the outcome.
    """

    def _scratch_smoke(self, directory: Path) -> Path:
        """A copy of smoke.sh whose layer collects nothing.

        The gating pytest call is replaced by ``rc=5`` -- pytest's own status
        for "no tests collected", which is what a registry that expanded to
        nothing produces. Every stdlib guard above it still runs, so the copy
        is a real layer with an empty plan, not a stub that exits early.
        """
        text = _smoke()
        text = text.replace(
            '  "${PYTHON_BIN}" -m pytest "${tests[@]}" -q || rc=$?\n',
            "  # pytest reported: no tests collected\n  rc=5\n",
            1,
        )
        self.assertNotEqual(text, _smoke(), "setup is not a control")
        scratch = directory / "smoke.sh"
        scratch.write_text(text, encoding="utf-8")
        scratch.chmod(0o755)
        return scratch

    def _run(self, script: Path) -> subprocess.CompletedProcess[str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "SOYMUTDB_SMOKE_PYTHON"}
        }
        env["SOYMUTDB_SMOKE_PYTHON"] = sys.executable
        env["SOYMUTDB_CI_PYTHON_VERSION"] = (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        return subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            check=False,
        )

    def test_smoke_sh_reports_an_empty_plan_as_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result = self._run(self._scratch_smoke(directory))
        output = result.stdout + result.stderr
        self.assertNotIn("SMOKE PASS", output, output[-2000:])
        self.assertIn("layer contracts FAILED", output, output[-2000:])
        self.assertNotEqual(result.returncode, 0, "an empty plan exited 0")

    def test_ci_job_steps_propagates_that_failure(self) -> None:
        """The stage is green only while the layer's status reaches it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            smoke_copy = self._scratch_smoke(directory)
            # ci-job-steps.sh runs the layer from REPO_ROOT, so the copy there
            # is the only way to make the real job body execute a plan that
            # collects nothing. Swap the committed script out and restore it in
            # a finally block: a leak would edit the working tree.
            backup = SMOKE.read_bytes()
            SMOKE.write_text(smoke_copy.read_text(encoding="utf-8"), encoding="utf-8")
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "SOYMUTDB_SMOKE_PYTHON"}
            }
            env["SOYMUTDB_SMOKE_PYTHON"] = sys.executable
            env["SOYMUTDB_CI_PYTHON_VERSION"] = (
                f"{sys.version_info.major}.{sys.version_info.minor}"
            )
            try:
                result = subprocess.run(
                    ["bash", str(CI_STEPS), "run", "smoke-contracts"],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=str(ROOT),
                    check=False,
                )
            finally:
                SMOKE.write_bytes(backup)
        output = result.stdout + result.stderr
        # Before this wiring existed the registry guard was the last thing in
        # the stage and the layer never ran, so nothing upstream of the plan
        # turned red. Either red is a pass here; a green is not.
        self.assertTrue(
            "clean tree drifts" in output or "SMOKE FAIL" in output,
            output[-2000:],
        )
        self.assertNotEqual(
            result.returncode,
            0,
            "the Contract suites stage exited 0 after collecting nothing",
        )


if __name__ == "__main__":
    unittest.main()

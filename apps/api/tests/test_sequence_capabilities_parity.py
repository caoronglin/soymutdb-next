"""The published capabilities surface must match the Rust kernel.

``scripts/check_sequence_capabilities_parity.py`` is the complement to the
merged ``check_bio_core_capability_parity.py`` (PR #135): that guard reads the
Python *module constants*, this one reads the ``SequenceCapabilitiesResponse``
field defaults, the programs/formats lists, and the router. Both are collected
by ``verify-backend-tests.sh``'s ``pytest tests -q`` from ``apps/api``, so a
one-sided edit fails the backend lane without touching a shared gate file.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "scripts" / "check_sequence_capabilities_parity.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_sequence_capabilities_parity", GUARD)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_committed_capabilities_match_the_kernel() -> None:
    guard = _load()
    assert guard.check(ROOT) == [], "run scripts/check_sequence_capabilities_parity.py"


def test_guard_catches_a_one_sided_constant_edit() -> None:
    guard = _load()
    case = next(c for c in guard.synthetic_cases() if c.name == "python max_inline drifts")
    assert guard.run_case(case, ROOT), "a Python-only limit edit must be caught"


def test_guard_catches_a_field_default_drift_invisible_to_pr_135() -> None:
    """#135 reads the module constant, not the published field default."""
    guard = _load()
    case = next(c for c in guard.synthetic_cases()
                if c.name == "field default drifts from its module constant")
    assert guard.run_case(case, ROOT), "a response-default drift must be caught"


def test_guard_catches_a_dropped_response_field_invisible_to_pr_135() -> None:
    guard = _load()
    case = next(c for c in guard.synthetic_cases()
                if c.name == "response field dropped, module constant intact")
    assert guard.run_case(case, ROOT), "a dropped field must be caught"


def test_guard_self_test_is_not_vacuous() -> None:
    guard = _load()
    assert sum(1 for c in guard.synthetic_cases() if c.expect_error) >= 10


def test_guard_cli_is_fail_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(GUARD), "--self-test"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[FAIL]" not in result.stdout

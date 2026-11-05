"""Regression coverage for the error-code gate wiring guard.

``scripts/check_error_code_gate_wiring.py`` proves the two error-code guards
are consumed by the contracts layer. Its own ``--self-test`` plants a
coordinated rename on a *copy* of the tree and reads the vocabulary guard's
exit status. That probe is only meaningful if the copied tree is complete:
``check_api_error_code_vocabulary.py`` reads ``export_contract.py``
unconditionally, so a copy that omits it crashes on the clean control too
(rc=1, bare traceback, no diagnostics) and a bare ``rc != 0`` assertion mistakes
that crash for a caught co-rename.

These tests pin the differential shape from a second file: the clean control
must be green, the co-renamed copy must report named ``FAIL:`` lines, and
dropping ``EXPORT`` from ``COPY_FILES`` must make the self-test fail. They run
on a bare interpreter with no API venv or third-party imports.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_error_code_gate_wiring.py"

spec = importlib.util.spec_from_file_location("check_error_code_gate_wiring", GUARD_PATH)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def _run_vocab(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tree / guard.VOCAB)],
        capture_output=True,
        text=True,
        check=False,
    )


def _copied_tree(plant=None) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    tmp = tempfile.TemporaryDirectory()
    tree = Path(tmp.name) / "repo"
    guard._copy_tree(tree)
    if plant is not None:
        plant(tree)
    return tree, tmp


def test_clean_control_is_green() -> None:
    """A complete copy must pass; otherwise the co-rename probe is vacuous."""
    tree, tmp = _copied_tree()
    try:
        result = _run_vocab(tree)
        assert result.returncode == 0, result.stderr
        assert "OK (" in result.stdout, result.stdout
        assert "Traceback" not in result.stderr, result.stderr
    finally:
        tmp.cleanup()


def test_co_rename_reports_named_contract_failures() -> None:
    tree, tmp = _copied_tree(guard._plant_co_rename)
    try:
        result = _run_vocab(tree)
        assert result.returncode != 0
        assert result.stderr.count("FAIL:") > 0, result.stderr
        assert "Traceback" not in result.stderr, result.stderr
    finally:
        tmp.cleanup()


def test_dropping_export_from_the_copied_tree_is_detected() -> None:
    """The self-test must fail when COPY_FILES loses a file the guard reads.

    Pins the fix: with the generator's export script absent, the clean control
    crashes with rc=1 and zero ``FAIL:`` lines -- exactly the false positive a
    bare-exit-status probe used to accept as a caught co-rename.
    """
    assert str(guard.EXPORT) in guard.COPY_FILES, (
        "the committed COPY_FILES no longer includes export_contract.py: the "
        "clean-control probe would crash instead of detecting a co-rename"
    )
    original = guard.COPY_FILES
    reduced = tuple(f for f in original if f != str(guard.EXPORT))
    guard.COPY_FILES = reduced
    try:
        assert guard._self_test() != 0
    finally:
        guard.COPY_FILES = original


def test_committed_wiring_is_sound() -> None:
    assert guard.check(ROOT) == []
    assert guard._self_test() == 0

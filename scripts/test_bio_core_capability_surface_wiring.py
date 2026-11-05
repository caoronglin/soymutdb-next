"""Pin the capability-surface guard's registration in the bio-core gate.

Standalone suite (like the numeric parity wiring pin) because
``scripts/test_ci_job_contracts.py`` is a shared hotspot with several open PRs
editing it. This file only reads bytes, so it needs no wheel, no Rust toolchain
and no Python 3.15 API venv.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/verify-bio-core.sh"
GUARD = ROOT / "scripts/check_bio_core_capability_surface.py"
REGRESSION = ROOT / "scripts/test_bio_core_capability_surface.py"
WIRING = ROOT / "scripts/test_bio_core_capability_surface_wiring.py"


def _verify() -> str:
    return VERIFY.read_text(encoding="utf-8")


def test_guard_exists_and_runs_before_the_build() -> None:
    text = _verify()
    assert GUARD.is_file(), "the surface guard must be committed"
    assert "scripts/check_bio_core_capability_surface.py --self-test" in text
    assert "scripts/check_bio_core_capability_surface.py" in text
    guard_at = text.index("advertised capability surface")
    build_at = text.index('step "maturin wheel')
    assert guard_at < build_at, "the surface check must run before the expensive wheel build"


def test_guard_is_load_bearing_via_self_test() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert "def self_test()" in source
    assert "def check(" in source
    assert "raise SystemExit(main())" in source


def test_regression_and_wiring_suites_are_registered() -> None:
    """Both suites must be collected by a real gate, not just committed.

    The wheel venv in verify-bio-core.sh has pytest, so both suites run there.
    A suite no gate collects is the exact regression class this file pins;
    smoke.sh is deliberately NOT touched (three in-flight PRs already insert
    into the same array slot).
    """
    text = _verify()
    assert "-m pytest scripts/test_bio_core_capability_surface.py" in text
    assert "scripts/test_bio_core_capability_surface_wiring.py" in text
    assert REGRESSION.is_file() and WIRING.is_file()


def test_removing_wiring_is_detected() -> None:
    """Negative control: stripping the guard invocations must break the pin."""
    text = (
        _verify()
        .replace('"${PY}" scripts/check_bio_core_capability_surface.py --self-test\n', "")
        .replace('"${PY}" scripts/check_bio_core_capability_surface.py\n', "")
    )
    assert "scripts/check_bio_core_capability_surface.py" not in text, (
        "a gate without the surface-guard invocations must not satisfy the wiring pin"
    )

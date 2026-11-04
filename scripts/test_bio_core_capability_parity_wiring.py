"""Pin the capability-parity guard's registration in the bio-core gate.

Kept as a standalone suite because ``scripts/test_ci_job_contracts.py`` is a
shared hotspot with several open PRs editing it. This file only reads bytes, so
it needs no wheel, no Rust toolchain and no Python 3.15 API venv.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/verify-bio-core.sh"
GUARD = ROOT / "scripts/check_bio_core_capability_parity.py"
REGRESSION = ROOT / "scripts/test_bio_core_capability_parity.py"


def _verify() -> str:
    return VERIFY.read_text(encoding="utf-8")


def test_guard_exists_and_is_invoked_before_the_build() -> None:
    text = _verify()
    assert GUARD.is_file(), "the parity guard must be committed"
    assert "scripts/check_bio_core_capability_parity.py --self-test" in text
    assert "scripts/check_bio_core_capability_parity.py" in text
    parity_at = text.index("capability parity")
    build_at = text.index('step "maturin wheel')
    assert parity_at < build_at, "parity must be checked before the expensive wheel build"


def test_guard_is_load_bearing_via_self_test() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert "def self_test()" in source
    assert "def check(" in source
    assert "raise SystemExit(main())" in source


def test_regression_suite_is_run_in_the_gate() -> None:
    text = _verify()
    assert "-m pytest scripts/test_bio_core_capability_parity.py" in text, (
        "the guard's regression suite must actually run in the bio-core gate"
    )
    regression_at = text.index("-m pytest scripts/test_bio_core_capability_parity.py")
    venv_at = text.index('"${PY}" -m venv')
    assert venv_at < regression_at, "the regression suite needs the venv that installs pytest"


def test_regression_suite_exists_and_covers_both_sides() -> None:
    source = REGRESSION.read_text(encoding="utf-8")
    for anchor in ("SEQUENCE_RS", "INTERVALS_RS", "BINDINGS_RS", "SCHEMA_PY", "test_weakened_guard_is_detected"):
        assert anchor in source, f"regression suite must pin {anchor}"


def test_removing_wiring_is_detected() -> None:
    """Negative control: stripping the two invocations must break the pin."""
    text = _verify().replace(
        '"${PY}" scripts/check_bio_core_capability_parity.py --self-test\n', ""
    ).replace(
        '"${PY}" scripts/check_bio_core_capability_parity.py\n', ""
    )
    assert "scripts/check_bio_core_capability_parity.py" not in text, (
        "a gate without the parity invocations must not satisfy the wiring pin"
    )

"""Pin the FFI error-message guard's registration in the bio-core gate.

Standalone suite (like the capability-parity wiring pin) because
``scripts/test_ci_job_contracts.py`` is a shared hotspot. It only reads bytes,
so it needs no wheel, no Rust toolchain and no Python 3.15 API venv.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/verify-bio-core.sh"
SMOKE = ROOT / "scripts/smoke.sh"
GUARD = ROOT / "scripts/check_kernel_error_messages.py"
REGRESSION = ROOT / "scripts/test_kernel_error_messages.py"
WIRING = ROOT / "scripts/test_kernel_error_messages_wiring.py"


def test_guard_exists_and_runs_before_the_build() -> None:
    text = VERIFY.read_text(encoding="utf-8")
    assert GUARD.is_file(), "the guard must be committed"
    assert "scripts/check_kernel_error_messages.py --self-test" in text
    assert "scripts/check_kernel_error_messages.py" in text
    guard_at = text.index("Kernel error-message contract")
    build_at = text.index('step "maturin wheel')
    assert guard_at < build_at, (
        "the contract check must run before the expensive wheel build"
    )


def test_guard_is_load_bearing_via_self_test() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert "def self_test()" in source
    assert "def check(" in source
    assert "raise SystemExit(main())" in source


def test_regression_and_wiring_suites_are_registered() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    assert "scripts/test_kernel_error_messages.py" in text
    assert "scripts/test_kernel_error_messages_wiring.py" in text
    assert REGRESSION.is_file() and WIRING.is_file()


def test_removing_wiring_is_detected() -> None:
    """Negative control: stripping the invocations must break the pin."""
    text = (
        VERIFY.read_text(encoding="utf-8")
        .replace('"${PY}" scripts/check_kernel_error_messages.py --self-test\n', "")
        .replace('"${PY}" scripts/check_kernel_error_messages.py\n', "")
    )
    assert "scripts/check_kernel_error_messages.py" not in text, (
        "a gate without the guard invocations must not satisfy the wiring pin"
    )

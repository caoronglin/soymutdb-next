"""Pin the OpenAPI field ledger's registration in the bio-core gate.

Kept as its own standalone suite (like the numeric-parity and surface wiring
pins) because ``scripts/test_ci_job_contracts.py`` is a shared hotspot with
several open PRs editing it. This file reads bytes only, so it needs no wheel,
no Rust toolchain and no Python 3.15 API venv.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts/verify-bio-core.sh"
GUARD = ROOT / "scripts/check_bio_core_openapi_fields.py"
REGRESSION = ROOT / "scripts/test_bio_core_openapi_fields.py"
WIRING = ROOT / "scripts/test_bio_core_openapi_fields_wiring.py"
SMOKE = ROOT / "scripts/smoke.sh"


def _verify() -> str:
    return VERIFY.read_text(encoding="utf-8")


def test_guard_is_committed_and_runs_before_the_build() -> None:
    text = _verify()
    assert GUARD.is_file(), "the field ledger must be committed"
    assert "scripts/check_bio_core_openapi_fields.py --self-test" in text
    assert "scripts/check_bio_core_openapi_fields.py\n" in text
    guard_at = text.index("OpenAPI response fields")
    build_at = text.index('step "maturin wheel')
    assert guard_at < build_at, "the ledger must run before the expensive wheel build"


def test_guard_is_load_bearing_via_self_test() -> None:
    source = GUARD.read_text(encoding="utf-8")
    assert "def self_test()" in source
    assert "def check(" in source
    assert "raise SystemExit(main())" in source, (
        "a discarded return value would print drift and still exit 0"
    )


def test_both_suites_are_collected_by_the_wheel_venv() -> None:
    text = _verify()
    assert "-m pytest scripts/test_bio_core_openapi_fields.py" in text
    assert "scripts/test_bio_core_openapi_fields_wiring.py" in text
    assert REGRESSION.is_file() and WIRING.is_file()


def test_smoke_contracts_layer_does_not_claim_the_ledger() -> None:
    """The ledger lives in the bio-core gate, not the shared smoke array.

    ``scripts/smoke.sh`` holds a ``tests=(...)`` array that three in-flight PRs
    already append to. Inserting here would be a guaranteed content conflict for
    no added coverage: the wheel venv in verify-bio-core.sh already collects
    both suites.
    """
    smoke = SMOKE.read_text(encoding="utf-8")
    assert "check_bio_core_openapi_fields.py" not in smoke
    assert "test_bio_core_openapi_fields.py" not in smoke

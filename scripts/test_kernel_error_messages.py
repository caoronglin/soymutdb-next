"""Regression suite for the FFI error-message guard.

The guard reads committed Rust bytes, so it needs no wheel, no cargo and no
Python 3.15. These cases prove it is load-bearing: reintroducing the second
literal sentence, weakening ``raise()``, or dropping the guard's own checks
must turn the suite red instead of leaving an unexercised file on disk.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts/check_kernel_error_messages.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "kernel_error_messages_guard", GUARD_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    return _load_guard()


def _sources() -> dict[str, str]:
    return {
        "errors": (ROOT / "packages/bio-core/src/errors.rs").read_text(
            encoding="utf-8"
        ),
        "bindings": (ROOT / "packages/bio-core/src/bindings.rs").read_text(
            encoding="utf-8"
        ),
    }


def _check(guard: ModuleType, errors: str, bindings: str) -> list[str]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "packages/bio-core/src").mkdir(parents=True)
        (root / "packages/bio-core/src/errors.rs").write_text(errors, encoding="utf-8")
        (root / "packages/bio-core/src/bindings.rs").write_text(
            bindings, encoding="utf-8"
        )
        return guard.check(root)


def test_clean_tree_passes(guard: ModuleType) -> None:
    assert guard.check(ROOT) == []


def test_guard_self_test_passes(guard: ModuleType) -> None:
    assert guard.self_test() == 0


def test_second_literal_sentence_is_caught(guard: ModuleType) -> None:
    src = _sources()
    bad = src["bindings"].replace(
        "String::from_utf8(bytes).or_else(|_| raise(BioCoreError::InvalidCharacter))",
        "String::from_utf8(bytes).map_err(|_| BioCoreException::new_err(("
        '"INVALID_CHARACTER", "invalid utf-8")))',
    )
    assert bad != src["bindings"], "mutation anchor is stale"
    problems = _check(guard, src["errors"], bad)
    assert any("hardcodes" in p for p in problems), problems
    assert any("exactly one new_err" in p for p in problems), problems


def test_raise_no_longer_derives_both_fields_is_caught(guard: ModuleType) -> None:
    src = _sources()
    for old, new in (
        ("err.code().to_string(),", '"validation_error".to_string(),'),
        ("err.to_string(),", '"oops".to_string(),'),
    ):
        bad = src["bindings"].replace(old, new, 1)
        assert bad != src["bindings"]
        assert _check(guard, src["errors"], bad), f"weakened raise() not caught: {old}"


def test_dropped_sentence_is_caught(guard: ModuleType) -> None:
    src = _sources()
    bad = src["errors"].replace(
        '    #[error("empty sequence")]\n    EmptySequence,\n', "    EmptySequence,\n"
    )
    assert bad != src["errors"]
    assert any("one sentence" in p for p in _check(guard, bad, src["bindings"])), (
        "a code with no sentence must fail, not be silently green"
    )


def test_weakened_guard_is_detected(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check() that always returns [] must not satisfy the suite."""
    src = _sources()
    monkeypatch.setattr(guard, "check", lambda _root: [])
    assert guard.check(ROOT) == []  # the weakened guard itself
    real = _load_guard()
    assert real.check(ROOT) == []
    assert _check(
        real,
        src["errors"],
        src["bindings"].replace(
            "String::from_utf8(bytes).or_else(|_| raise(BioCoreError::InvalidCharacter))",
            "String::from_utf8(bytes).map_err(|_| BioCoreException::new_err(("
            '"INVALID_CHARACTER", "invalid utf-8")))',
        ),
    ), "restoring the real guard must re-expose the drift"

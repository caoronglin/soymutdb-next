"""Regression suite for the Rust↔API capability-parity guard.

The guard reads committed sources, not a built wheel, so it can run before the
expensive Rust build. These cases prove the guard is load-bearing: weakening
its comparison (returning a green result without reading both sides) must turn
the suite red, not just leave a file on disk that nobody exercises.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts/check_bio_core_capability_parity.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capability_parity_guard", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    return _load_guard()


@pytest.fixture
def sources(guard: ModuleType) -> dict[str, str]:
    return guard.load_sources()


def test_clean_tree_has_no_capability_drift(guard: ModuleType, sources: dict[str, str]) -> None:
    assert guard.check(sources) == []


def test_guard_self_test_passes(guard: ModuleType) -> None:
    assert guard.self_test() == 0


@pytest.mark.parametrize(
    "path_key, old, new",
    [
        ("SEQUENCE_RS", "MAX_INLINE_SEQUENCE: usize = 1_048_576", "MAX_INLINE_SEQUENCE: usize = 1_048_577"),
        ("SEQUENCE_RS", "MAX_PATTERN: usize = 256", "MAX_PATTERN: usize = 257"),
        ("INTERVALS_RS", "MAX_HITS: usize = 1000", "MAX_HITS: usize = 1001"),
        ("INTERVALS_RS", "MAX_REGIONS: usize = 1000", "MAX_REGIONS: usize = 1001"),
        ("BINDINGS_RS", '"k_range", (1, 32)', '"k_range", (1, 33)'),
        ("TRANSLATION_RS", "STANDARD_GENETIC_CODE: u32 = 1", "STANDARD_GENETIC_CODE: u32 = 2"),
        ("BINDINGS_RS", '"coordinate_system_public", "1-based-inclusive"', '"coordinate_system_public", "1-based-closed"'),
        ("SCHEMA_PY", "MAX_INLINE_SEQUENCE = 1_048_576", "MAX_INLINE_SEQUENCE = 1_048_577"),
        ("SCHEMA_PY", "MAX_PATTERN = 256", "MAX_PATTERN = 257"),
        ("SCHEMA_PY", "MAX_HITS = 1000", "MAX_HITS = 1001"),
        ("SCHEMA_PY", "MAX_REGIONS = 1000", "MAX_REGIONS = 1001"),
        ("SEQUENCE_RS", "MAX_ALIGNMENT_CELLS: u64 = 10_000_000", "MAX_ALIGNMENT_CELLS: u64 = 10_000_001"),
        ("SCHEMA_PY", "MAX_ALIGNMENT_CELLS = 10_000_000", "MAX_ALIGNMENT_CELLS = 20_000_000"),
        ("SCHEMA_PY", "k_range: tuple[int, int] = (1, 32)", "k_range: tuple[int, int] = (1, 33)"),
        ("SCHEMA_PY", "lambda: [1]", "lambda: [2]"),
        ("SCHEMA_PY", 'coordinate_system_internal: str = "0-based-half-open"', 'coordinate_system_internal: str = "0-based-closed"'),
    ],
)
def test_one_sided_drift_is_reported(
    guard: ModuleType, sources: dict[str, str], path_key: str, old: str, new: str
) -> None:
    path = str(getattr(guard, path_key))
    assert old in sources[path], f"mutation anchor missing: {old!r}"
    mutated = dict(sources)
    mutated[path] = sources[path].replace(old, new, 1)
    assert mutated[path] != sources[path]
    assert guard.check(mutated), f"{path_key}: one-sided drift was not caught"


def test_missing_source_is_reported_not_silently_green(guard: ModuleType, sources: dict[str, str]) -> None:
    mutated = dict(sources)
    mutated[str(guard.SCHEMA_PY)] = "class SequenceCapabilitiesResponse: pass\n"
    errors = guard.check(mutated)
    assert errors, "a missing field must fail, not be treated as a match"


def test_weakened_guard_is_detected(guard: ModuleType, monkeypatch: pytest.MonkeyPatch, sources: dict[str, str]) -> None:
    """A guard that always returns [] must not satisfy the drift scenarios."""
    monkeypatch.setattr(guard, "check", lambda _sources: [])
    rust = dict(sources)
    rust[str(guard.SEQUENCE_RS)] = sources[str(guard.SEQUENCE_RS)].replace(
        "MAX_INLINE_SEQUENCE: usize = 1_048_576", "MAX_INLINE_SEQUENCE: usize = 2"
    )
    assert guard.check(rust) == []  # the weakened guard itself
    # Restore the real function to prove the un-weakened one still catches it.
    real = _load_guard()
    assert real.check(rust), "restoring the real guard must re-expose the drift"

def test_limit_advertised_by_kernel_but_absent_from_api_is_reported(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    """Dropping a field from the response must not read as "no difference".

    The numeric comparison only visits keys both sides already have, so a field
    removed from the API is invisible to it: the kernel keeps advertising the
    bound, clients keep sending input sized to an ad they can no longer read,
    and every check stays green.  This is the shape that let ``max_regions``
    and ``max_alignment_cells`` sit in the kernel without reaching the API.
    """
    path = str(guard.SCHEMA_PY)
    for field in ("    max_regions: int = MAX_REGIONS\n", "    max_alignment_cells: int = MAX_ALIGNMENT_CELLS\n"):
        assert field in sources[path], f"anchor missing: {field!r}"
        mutated = dict(sources)
        mutated[path] = sources[path].replace(field, "", 1)
        errors = guard.check(mutated)
        assert errors, f"dropping {field.strip()!r} from the API must be reported"
        assert "omits it entirely" in errors[0], errors


def test_advertised_key_sets_are_not_derived_from_the_api(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    """The Rust side owns the key set; the API cannot define its own workload.

    If both sets were read from the same file the comparison would be a
    tautology, so assert the kernel set is larger and that every advertised
    numeric limit is also a response field.
    """
    rust_keys = guard._rust_advertised_keys(sources)
    py_keys = guard._python_advertised_keys(sources[str(guard.SCHEMA_PY)])
    assert rust_keys, "kernel advertises no keys at all"
    assert rust_keys <= py_keys, f"kernel advertises {rust_keys - py_keys} which the API omits"
    for name, _, _ in guard.NUMERIC_LIMITS:
        assert name in py_keys, f"{name} is compared but never exposed by the API"

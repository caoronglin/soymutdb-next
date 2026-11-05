"""Regression suite for the advertised capability-surface guard.

The guard reads committed sources, not a built wheel, so it can run before the
expensive Rust build. These cases prove it is load-bearing: weakening the
comparison to a constant green, or dropping a single entry from one side, must
turn the suite red rather than leave an unexercised file in the repo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts/check_bio_core_capability_surface.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capability_surface_guard", GUARD_PATH)
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


def test_clean_tree_has_no_surface_drift(guard: ModuleType, sources: dict[str, str]) -> None:
    assert guard.check(sources) == []


def test_guard_self_test_passes(guard: ModuleType) -> None:
    assert guard.self_test() == 0


def test_guard_does_not_hardcode_the_program_surface(guard: ModuleType) -> None:
    """The advertised set must be derived from routes, not a fixed whitelist."""
    assert not hasattr(guard, "PROGRAM_BINDING"), (
        "a fixed program map would reject a legitimate new route"
    )
    assert hasattr(guard, "route_programs")


@pytest.mark.parametrize(
    "key, old, new",
    [
        ("SCHEMA_PY", '            "kmers",\n', ""),
        ("SCHEMA_PY", '"fasta", "fastq", "bed"', '"fasta", "fastq"'),
        ("SCHEMA_PY", '            "kmers",\n', '            "kmers",\n            "phantom",\n'),
        ("ROUTES_PY", '@router.post("/kmers", response_model=s.KmerResponse)\nasync def sequence_kmers(payload: s.KmerRequest) -> s.KmerResponse:\n    return await service.kmers(payload)\n', ""),
        ("BINDINGS_RS", "    m.add_function(wrap_pyfunction!(kmer_counts, m)?)?;\n", ""),
        ("BINDINGS_RS", "    m.add_function(wrap_pyfunction!(validate_bed, m)?)?;\n", ""),
        ("INSPECT_PY", '        "bed": "validate_bed",\n', ""),
        ("INSPECT_PY", '"bed": "validate_bed"', '"bed": "validate_gone"'),
    ],
)
def test_one_sided_drift_is_reported(
    guard: ModuleType, sources: dict[str, str], key: str, old: str, new: str
) -> None:
    path = str(getattr(guard, key))
    assert old in sources[path], f"anchor missing: {old!r}"
    mutated = dict(sources)
    mutated[path] = sources[path].replace(old, new, 1)
    assert guard.check(mutated), f"{key}: one-sided drift was not caught"


def test_weakened_guard_is_detected(guard: ModuleType, monkeypatch: pytest.MonkeyPatch, sources: dict[str, str]) -> None:
    """A guard that always returns [] must not satisfy the drift scenarios."""
    monkeypatch.setattr(guard, "check", lambda _sources: [])
    drifted = dict(sources)
    path = str(guard.SCHEMA_PY)
    drifted[path] = sources[path].replace('            "kmers",\n', "")
    assert guard.check(drifted) == []  # the weakened guard itself
    real = _load_guard()
    assert real.check(drifted), "restoring the real guard must re-expose the drift"


def test_missing_field_fails_closed(guard: ModuleType, sources: dict[str, str]) -> None:
    mutated = dict(sources)
    mutated[str(guard.SCHEMA_PY)] = "class SequenceCapabilitiesResponse: pass\n"
    errors = guard.check(mutated)
    assert errors, "a missing field must fail, not be treated as a match"

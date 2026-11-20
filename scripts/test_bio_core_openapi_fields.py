"""Regression suite for the per-endpoint OpenAPI field ledger.

The ledger reads committed bytes (``openapi.json``, the Pydantic models, the
service bodies, the PyO3 bindings), so it runs before the Rust build. These
cases prove it is load-bearing: weakening the comparison to a constant green,
or dropping a field on one side, must turn the suite red rather than leave an
unexercised file in the repository.

The two drifts the live tree carries today (``inspect`` and
``tools/intervals/overlap`` are served and schematised but absent from
``programs``) are pinned in :data:`check_bio_core_openapi_fields.KNOWN_DRIFT`.
Both directions are asserted: a *new* drift must be caught, and a *fixed* one
must not leave its baseline entry behind.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts/check_bio_core_openapi_fields.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("openapi_fields_guard", GUARD_PATH)
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


def test_recorded_drift_reproduces_exactly(guard: ModuleType, sources: dict[str, str]) -> None:
    """The baseline must reproduce and nothing else may drift."""
    errors = guard.check(sources)
    assert guard.new_drift(errors) == [], f"unrecorded drift: {guard.new_drift(errors)}"
    for label, detail in guard.KNOWN_DRIFT:
        assert f"{label}: {detail}" in errors, f"baseline entry {label!r} no longer reproduces"


def test_guard_self_test_passes(guard: ModuleType) -> None:
    assert guard.self_test() == 0


def test_programs_are_compared_with_the_served_document(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    """A path the document serves but the roster omits must be named."""
    mutated = dict(sources)
    schema = mutated[str(guard.SCHEMA_PY)]
    mutated[str(guard.SCHEMA_PY)] = schema.replace('            "kmers",\n', "", 1)
    errors = guard.check(mutated)
    assert any("program 'kmers'" in e and "absent from programs" in e for e in errors)


def test_a_field_added_with_no_kernel_key_is_named(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    mutated = dict(sources)
    schema = mutated[str(guard.SCHEMA_PY)]
    mutated[str(guard.SCHEMA_PY)] = schema.replace(
        "    distinct_kmers: int\n", "    distinct_kmers: int\n    phantom_metric: int\n", 1
    )
    errors = guard.check(mutated)
    assert any("phantom_metric" in e for e in errors)


def test_a_kernel_key_rename_is_named(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    mutated = dict(sources)
    bindings = mutated[str(guard.BINDINGS_RS)]
    mutated[str(guard.BINDINGS_RS)] = bindings.replace(
        'd.set_item("distinct_kmers", r.distinct_kmers)?;',
        'd.set_item("distinct_kmer", r.distinct_kmers)?;',
        1,
    )
    errors = guard.check(mutated)
    assert any("distinct_kmers" in e and "no kernel key" in e for e in errors)


def test_an_explicit_reader_of_a_dropped_key_is_named(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    """``raw["valid_windows"]`` with no matching key is a KeyError per request."""
    mutated = dict(sources)
    bindings = mutated[str(guard.BINDINGS_RS)]
    mutated[str(guard.BINDINGS_RS)] = bindings.replace(
        'd.set_item("valid_windows", r.valid_windows)?;\n', "", 1
    )
    errors = guard.check(mutated)
    assert any("valid_windows" in e for e in errors)


def test_python_owned_fields_are_declared_not_guessed(
    guard: ModuleType, sources: dict[str, str]
) -> None:
    """Every declared owner names a real field: a typo must not exempt anything."""
    doc_models = set(guard.load_sources()[str(guard.OPENAPI)])  # smoke: bytes readable
    assert doc_models
    schema = sources[str(guard.SCHEMA_PY)]
    for model, owners in guard.PYTHON_OWNED.items():
        fields = guard.pydantic_fields(schema, model)
        unknown = set(owners) - fields
        assert not unknown, f"{model}: PYTHON_OWNED names fields the model lacks: {unknown}"
        for reason in owners.values():
            assert reason.strip(), f"{model}: an owner needs a stated reason"


def test_the_ledger_covers_every_advertised_compute_route(guard: ModuleType, sources: dict[str, str]):
    """A new /tools path that joins the roster must also join the ledger."""
    doc = __import__("json").loads(sources[str(guard.OPENAPI)])
    served = guard.served_paths(doc)
    covered = {path.lstrip("/") for _, path, *_ in guard.ENDPOINTS}
    assert served <= covered, f"served without a ledger row: {sorted(served - covered)}"

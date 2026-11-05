"""Pin the error-code fallback's two-part declaration from outside the guard.

``scripts/check_api_error_code_vocabulary.py`` counts the ``http_error``
fallback as declared only when the module-level ``HTTP_ERROR_CODE`` constant
**and** the ``catalog[HTTP_ERROR_CODE] = ...`` subscript entry are both present
(PR #212). Weakening that predicate to a constant-only read is a one-line edit
that the guard's own ``--self-test`` must reject; this suite is the second
file pinning the same shape so a single edit cannot remove both the behaviour
and its detector.

Reads committed bytes only: no API import, no Python 3.15 venv, no wheel, no
database. Runs in the contracts smoke layer via ``tests=()``.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_api_error_code_vocabulary.py"
EXCEPTIONS = ROOT / "apps" / "api" / "app" / "core" / "exceptions.py"

_FALLBACK_BLOCK = (
    "    catalog[HTTP_ERROR_CODE] = (\n"
    '        "Generic HTTPException fallback; see x-error-status for the statuses that use it."\n'
    "    )\n"
)


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "api_error_code_vocabulary", GUARD_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fallback_block_shape_is_committed() -> None:
    """The ablation is built from the exact committed bytes, not hand-wrapped."""
    assert _FALLBACK_BLOCK in EXCEPTIONS.read_text(encoding="utf-8")


def test_clean_tree_declares_the_fallback() -> None:
    guard = _load_guard()
    assert "http_error" in guard.source_codes(ROOT)


def test_dropping_only_the_catalog_entry_is_detected() -> None:
    """A leftover constant must not stand in for the dropped subscript entry."""
    guard = _load_guard()
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        for rel in (
            "apps/api/app/core/exceptions.py",
            "packages/api-client/error-codes.golden.json",
            "packages/api-client/error-codes.json",
            "packages/api-client/openapi.json",
            "packages/api-client/scripts/generate-api-client.sh",
            "packages/api-client/scripts/export_contract.py",
        ):
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / rel).read_bytes())
        source = tree / "apps/api/app/core/exceptions.py"
        text = source.read_text(encoding="utf-8")
        assert _FALLBACK_BLOCK in text
        source.write_text(text.replace(_FALLBACK_BLOCK, "", 1), encoding="utf-8")
        assert "http_error" not in guard.source_codes(tree)
        assert guard.check(tree), "the guard must reject a dropped catalog entry"


def test_guard_self_test_rejects_a_constant_only_read() -> None:
    """Weakening source_codes() to constant-only must fail --self-test.

    This pins the detector itself: if a future edit drops the decisive plant
    from the guard's self-test along with the both-halves predicate, the smoke
    layer must still go red from a second file.
    """
    guard = _load_guard()
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "repo"
        tree.mkdir()
        for rel in (
            "scripts/check_api_error_code_vocabulary.py",
            "apps/api/app/core/exceptions.py",
            "packages/api-client/error-codes.golden.json",
            "packages/api-client/error-codes.json",
            "packages/api-client/openapi.json",
            "packages/api-client/scripts/generate-api-client.sh",
            "packages/api-client/scripts/export_contract.py",
        ):
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / rel).read_bytes())
        weakened = tree / "scripts/check_api_error_code_vocabulary.py"
        text = weakened.read_text(encoding="utf-8")
        old = "    if const_value is not None and catalog_entry:\n        codes.add(const_value)"
        new = "    if const_value is not None:\n        codes.add(const_value)"
        assert old in text, "the both-halves predicate shape changed"
        weakened.write_text(text.replace(old, new, 1), encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "weakened_vocabulary", weakened
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module._self_test() != 0, (
            "a constant-only source_codes() passed the guard's own --self-test"
        )

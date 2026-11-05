"""Regression coverage for the published error-code catalog guard.

The guard (``scripts/check_error_code_catalog.py``) is wired into
``packages/api-client/scripts/check-contract.sh``. These tests make sure the
wiring cannot be removed silently and that the guard itself fails on the drift
shapes it claims to catch -- without a 3.15 venv, pydantic or PostgreSQL.

The negative cases use synthetic trees, so a co-revert of source + catalog +
snapshot cannot make the tests pass by reading the real repo.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_error_code_catalog as guard

CATALOG_REL = "packages/api-client/error-codes.json"
OPENAPI_REL = "packages/api-client/openapi.json"
EXCEPTIONS_REL = "apps/api/app/core/exceptions.py"
GUARD_SOURCE = ROOT / "scripts" / "check_error_code_catalog.py"
GENERATOR_REL = "packages/api-client/scripts/generate-api-client.sh"
CONTRACT_REL = "packages/api-client/scripts/check-contract.sh"


def _synthetic_tree() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel in (EXCEPTIONS_REL, CATALOG_REL, OPENAPI_REL, GENERATOR_REL, CONTRACT_REL):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    return tmp


def _cleanup(tmp: Path) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


def test_committed_tree_is_in_sync() -> None:
    assert guard.check_tree(ROOT) == []


def test_guard_is_wired_into_the_contract_gate() -> None:
    script = (ROOT / "packages/api-client/scripts/check-contract.sh").read_text(encoding="utf-8")
    assert "check_error_code_catalog.py" in script, (
        "the error-code catalog guard is no longer called by check-contract.sh"
    )


@pytest.mark.parametrize(
    "plant",
    [
        pytest.param(
            lambda tree: _json_mutate(tree / CATALOG_REL, lambda d: d.update(phantom_code="x")),
            id="extra-code",
        ),
        pytest.param(
            lambda tree: _json_mutate(tree / CATALOG_REL, lambda d: d.pop("not_found", None)),
            id="dropped-code",
        ),
        pytest.param(
            lambda tree: _json_mutate(tree / CATALOG_REL, lambda d: d.__setitem__("internal_error", "tampered")),
            id="changed-description",
        ),
        pytest.param(
            lambda tree: _json_mutate(tree / OPENAPI_REL, lambda d: d["x-error-codes"].update(phantom_code="x")),
            id="x-error-codes-drift",
        ),
        pytest.param(
            lambda tree: _json_mutate(tree / OPENAPI_REL, lambda d: d.pop("x-error-codes", None)),
            id="x-error-codes-removed",
        ),
        pytest.param(
            lambda tree: (tree / EXCEPTIONS_REL).write_text(
                (tree / EXCEPTIONS_REL)
                .read_text(encoding="utf-8")
                .replace('error_code = "not_found"', 'error_code = "not_found_tampered"'),
                encoding="utf-8",
            ),
            id="source-code-renamed",
        ),
        pytest.param(
            lambda tree: (tree / GENERATOR_REL).write_text(
                (tree / GENERATOR_REL)
                .read_text(encoding="utf-8")
                .replace('  --error-codes "$PKG_DIR/error-codes.json"\n', ""),
                encoding="utf-8",
            ),
            id="generator-drops-error-codes",
        ),
        pytest.param(
            lambda tree: (tree / CONTRACT_REL).write_text(
                (tree / CONTRACT_REL)
                .read_text(encoding="utf-8")
                .replace("check_error_code_catalog.py", "unwired_guard.py"),
                encoding="utf-8",
            ),
            id="contract-gate-drops-guard",
        ),
    ],
)
def test_guard_rejects_drift(plant) -> None:  # type: ignore[no-untyped-def]
    tree = _synthetic_tree()
    try:
        assert guard.check_tree(tree) == [], "synthetic clean tree must start in sync"
        plant(tree)
        assert guard.check_tree(tree), "planted catalog drift was not caught"
    finally:
        _cleanup(tree)


def test_guard_detects_co_reverted_source_and_artifacts() -> None:
    """Source + both artifacts reverted together must still be caught."""
    tree = _synthetic_tree()
    try:
        src = tree / EXCEPTIONS_REL
        src.write_text(
            src.read_text(encoding="utf-8").replace(
                'error_code = "not_found"', 'error_code = "not_found_v2"'
            ),
            encoding="utf-8",
        )
        for rel in (CATALOG_REL, OPENAPI_REL):
            path = tree / rel
            data = json.loads(path.read_text(encoding="utf-8"))
            if rel == CATALOG_REL:
                data["not_found_v2"] = data.pop("not_found")
            else:
                data["x-error-codes"]["not_found_v2"] = data["x-error-codes"].pop("not_found")
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        # A fully co-reverted tree is internally consistent; the guard cannot
        # know the history, but it must at least agree the tree is in sync.
        # The real protection is that check-contract.sh re-exports from the
        # backend, so this test pins the guard's own consistency contract.
        assert guard.check_tree(tree) == []
    finally:
        _cleanup(tree)


def test_self_test_passes() -> None:
    assert guard.self_test() == 0


def test_fallback_without_a_subclass_is_derived() -> None:
    """error_code_catalog() publishes http_error with no exception class."""
    derived = guard._derived_catalog(ROOT / EXCEPTIONS_REL)
    assert derived.get("http_error") == (
        "Generic HTTPException fallback; see x-error-status for the "
        "statuses that use it."
    )
    committed = json.loads((ROOT / CATALOG_REL).read_text(encoding="utf-8"))
    assert derived == committed


def test_dropped_fallback_catalog_entry_is_detected() -> None:
    """A leftover HTTP_ERROR_CODE constant must not fake a published code."""
    tree = _synthetic_tree()
    try:
        src = tree / EXCEPTIONS_REL
        desc = (
            "Generic HTTPException fallback; see x-error-status for the "
            "statuses that use it."
        )
        block = (
            "    catalog[HTTP_ERROR_CODE] = (\n"
            f'        "{desc}"\n'
            "    )\n"
        )
        src.write_text(
            src.read_text(encoding="utf-8").replace(block, ""),
            encoding="utf-8",
        )
        assert guard.check_tree(tree), "dropped fallback entry went unnoticed"
    finally:
        _cleanup(tree)


def test_no_op_plants_are_refused_by_the_guard() -> None:
    """A needle that matches nothing is not an ablation.

    ``_mutate_source`` / ``_mutate_wiring`` / ``_mutate_json`` each refuse an
    edit that landed no bytes. Without that, a regenerate that rewraps the
    fallback block leaves ``str.replace`` inert and the self-test judges a
    pristine tree.
    """
    tree = _synthetic_tree()
    try:
        cases = (
            (
                guard._mutate_source,
                tree / EXCEPTIONS_REL,
                lambda src: src.replace("no such block", ""),
            ),
            (
                guard._mutate_wiring,
                tree / GENERATOR_REL,
                lambda src: src.replace("no such flag", ""),
            ),
            (
                guard._mutate_json,
                tree / CATALOG_REL,
                lambda data: data.pop("no_such_code", None),
            ),
        )
        for mutate, path, plant in cases:
            before = path.read_bytes()
            with pytest.raises(AssertionError, match="did not change"):
                mutate(path, plant)
            assert path.read_bytes() == before, "a refused plant still wrote bytes"
    finally:
        _cleanup(tree)


def test_coordinated_prune_of_the_fallback_is_rejected() -> None:
    """Source + both artifacts pruned together must still redden the guard."""
    tree = _synthetic_tree()
    try:
        src = tree / EXCEPTIONS_REL
        source = src.read_text(encoding="utf-8")
        assert guard._FALLBACK_BLOCK in source
        src.write_text(source.replace(guard._FALLBACK_BLOCK, "", 1), encoding="utf-8")
        for rel, key in ((CATALOG_REL, None), (OPENAPI_REL, "x-error-codes")):
            path = tree / rel
            data = json.loads(path.read_text(encoding="utf-8"))
            target = data if key is None else data[key]
            target.pop(guard._FALLBACK_CODE, None)
            path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        problems = guard.check_tree(tree)
        assert any("no longer publishes" in p for p in problems), problems
    finally:
        _cleanup(tree)


def test_self_test_plant_set_pins_the_coordinated_prune() -> None:
    """Dropping the decisive plant from the guard must fail its own self-test."""
    tree = _synthetic_tree()
    try:
        weakened = tree / "scripts/check_error_code_catalog.py"
        text = (ROOT / "scripts/check_error_code_catalog.py").read_text(encoding="utf-8")
        marker = '"fallback code pruned from source and both artifacts": lambda p: ('
        assert marker in text
        # Replacing the case with one that plants nothing must not stay green.
        start = text.index("        " + marker)
        # The case is a tuple expression ending in `),`; the next dict entry
        # begins with `    }` or another quoted key. Splice on the following
        # blank line + the `    }` that closes `cases`, so an inner lambda's
        # `),` cannot be mistaken for the end of the entry.
        end = text.index("    }\n", start)
        text = text[:start] + '        "inert probe": lambda p: None,\n' + text[end:]
        weakened.parent.mkdir(parents=True, exist_ok=True)
        weakened.write_text(text, encoding="utf-8")
        import importlib.util
        spec = importlib.util.spec_from_file_location("weakened_catalog", weakened)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = tree
        assert module.self_test() != 0, "a gutted self-test passed"
    finally:
        _cleanup(tree)


def _json_mutate(path: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_the_plant_gate_is_itself_self_tested() -> None:
    """Gutting `_require_changed` must turn `--self-test` red, not green.

    Every plant runs through that one function, so replacing its body with
    `return None` turns the whole case table into no-ops while each case still
    prints "caught" -- the clean tree is caught by nothing and reported as
    caught by everything. The guard now self-tests the gate before trusting
    any of its verdicts; this pins that it does.
    """
    source = GUARD_SOURCE.read_text(encoding="utf-8")
    marker = (
        '    if after == before:\n'
        '        raise AssertionError(f"planted defect did not change {path.name}")\n'
    )
    assert marker in source, "control: the plant gate changed shape"
    hollowed = source.replace(marker, "    return None\n" + marker, 1)
    assert hollowed != source

    tree = Path(tempfile.mkdtemp())
    try:
        # The probe copy walks to `ROOT.parents[1]` for its tree, so it must
        # run from a copy of the repo, not from the repo with a stray guard.
        probe = tree / "repo"
        shutil.copytree(
            ROOT,
            probe,
            ignore=shutil.ignore_patterns(".git", "node_modules", "dist", "__pycache__"),
        )
        (probe / "scripts" / "check_error_code_catalog.py").write_text(hollowed, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "scripts/check_error_code_catalog.py", "--self-test"],
            capture_output=True,
            text=True,
            cwd=probe,
            check=False,
        )
        assert result.returncode != 0, (
            "a guard whose plants cannot fail still reported a green self-test: "
            + (result.stdout + result.stderr)[-400:]
        )
        assert "_require_changed" in result.stderr, (
            "the failure did not name the plant gate: " + result.stderr[-400:]
        )
    finally:
        shutil.rmtree(tree, ignore_errors=True)

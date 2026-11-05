"""Regression coverage for ``scripts/check_openapi_required_fields.py``.

The guard pins 1076 published ``required`` declarations to a hand-written
literal and checks the generated client's optional markers against them.
These cases prove each failure direction on real committed bytes, that the
digest is independent of the artifact it audits, that the generated half
cannot be edited alone, and that the wiring cannot quietly rot. Collected by
the contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_required_fields as guard

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
REGISTRY = (ROOT / "scripts" / "check_contracts_registry_collection.py").read_text(
    encoding="utf-8"
)
TEETH = (ROOT / "scripts" / "check_contracts_self_test_teeth.py").read_text(
    encoding="utf-8"
)

_TARGET = "AdminPluginResponse"
_SNAPSHOT = guard.SNAPSHOT.read_text(encoding="utf-8")
_GENERATED = guard.GENERATED.read_text(encoding="utf-8")


def _mutate(change) -> str:
    document = json.loads(_SNAPSHOT)
    change(document["components"]["schemas"])
    return json.dumps(document, indent=2)


def test_committed_tree_passes() -> None:
    found = guard.failures(snapshot=_SNAPSHOT, generated=_GENERATED)
    assert not found, found


def test_coordinated_required_drop_is_rejected() -> None:
    """The decisive drift: both halves move together, blob ids re-pinned."""

    def change(schemas: dict) -> None:
        assert schemas[_TARGET]["required"] == ["key", "status"]
        schemas[_TARGET]["required"] = ["status"]

    snapshot = _mutate(change)
    generated = _GENERATED.replace(
        "        AdminPluginResponse: {\n            /** Key */\n            key: string;",
        "        AdminPluginResponse: {\n            /** Key */\n            key?: string;",
        1,
    )
    assert generated != _GENERATED
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("drifted" in problem for problem in found), found


def test_one_sided_snapshot_drop_is_rejected() -> None:
    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"] = ["status"]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_one_sided_client_optional_flip_is_rejected() -> None:
    """The generated half is checked against the pinned rows, not the snapshot."""
    generated = _GENERATED.replace(
        "        AdminPluginResponse: {\n            /** Key */\n            key: string;",
        "        AdminPluginResponse: {\n            /** Key */\n            key?: string;",
        1,
    )
    assert generated != _GENERATED
    found = guard.failures(snapshot=_SNAPSHOT, generated=generated)
    assert any("renders required field" in problem for problem in found), found


def test_one_sided_required_add_is_rejected() -> None:
    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"].append("manifest")

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("count is" in problem for problem in found), found


def test_nested_defs_required_drop_is_rejected() -> None:
    """The seven nested $defs copies are part of the pinned surface."""

    def change(schemas: dict) -> None:
        detail = schemas["ErrorResponse"]["$defs"]["ErrorDetail"]
        assert detail["required"] == ["code", "message"]
        detail["required"] = ["code"]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_same_count_permutation_is_rejected() -> None:
    """Move one required field between two schemas: counts hold, digest moves."""

    def change(schemas: dict) -> None:
        a = schemas["AdminPluginResponse"]["required"]
        b = schemas["AdminPluginsResponse"]["required"]
        assert a == ["key", "status"] and b == ["plugins"]
        a[0], b[0] = b[0], a[0]

    found = guard.failures(snapshot=_mutate(change), generated=_GENERATED)
    assert any("drifted" in problem for problem in found), found


def test_the_digest_is_an_independent_literal() -> None:
    """Re-deriving the digest from the artifact would make the pin vacuous."""
    source = (ROOT / "scripts" / "check_openapi_required_fields.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_REQUIRED_FIELD_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    document = json.loads(_SNAPSHOT)
    assert value == guard._digest(guard.rows(document))


def test_the_count_doors_are_load_bearing() -> None:
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_rows=guard._EXPECTED_REQUIRED_ROWS + 1,
    )
    assert any("count is" in problem for problem in found), found
    found = guard.failures(
        snapshot=_SNAPSHOT,
        generated=_GENERATED,
        expected_schemas=guard._EXPECTED_SCHEMAS + 1,
    )
    assert any("span" in problem for problem in found), found


def test_a_repin_in_the_same_commit_stays_green() -> None:
    """A reviewed regenerate re-pins the literal with the artifact, once."""

    def change(schemas: dict) -> None:
        schemas[_TARGET]["required"] = ["status"]

    snapshot = _mutate(change)
    new_digest = guard._digest(guard.rows(json.loads(snapshot)))
    assert new_digest != guard._REQUIRED_FIELD_DIGEST
    found = guard.failures(
        snapshot=snapshot,
        generated=_GENERATED,
        digest=new_digest,
        expected_rows=guard._EXPECTED_REQUIRED_ROWS - 1,
    )
    assert not found, found


def test_the_wiring_is_pinned_in_all_three_places() -> None:
    assert f"scripts/{guard.SELF}" in SMOKE
    assert f"scripts/{guard.SELF}" in REGISTRY
    assert "scripts/test_openapi_required_fields.py" in SMOKE
    assert "scripts/test_openapi_required_fields.py" in REGISTRY
    assert f"scripts/{guard.SELF}" in TEETH

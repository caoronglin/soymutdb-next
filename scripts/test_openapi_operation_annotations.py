"""Regression coverage for ``scripts/check_openapi_operation_annotations.py``.

The guard pins the published per-operation annotation prose to a hand-written
literal. These cases prove each failure direction on real committed bytes,
and that the wiring and the literal cannot quietly rot. Collected by the
contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_operation_annotations as guard

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
REGISTRY = (ROOT / "scripts" / "check_contracts_registry_collection.py").read_text(
    encoding="utf-8"
)
TEETH = (ROOT / "scripts" / "check_contracts_self_test_teeth.py").read_text(
    encoding="utf-8"
)


def _bytes() -> tuple[str, str, str]:
    return (
        guard.SNAPSHOT.read_text(encoding="utf-8"),
        guard.GENERATED.read_text(encoding="utf-8"),
        SMOKE,
    )


def _run(document: dict, generated: str | None = None, smoke: str | None = None):
    snap, gen, smk = _bytes()
    return guard.failures(
        document,
        gen if generated is not None else gen,
        smk if smoke is not None else smk,
    )


def _co_revert_summary(value: str = "Liveness v2") -> tuple[dict, str]:
    """Rename one summary in both halves -- the decisive drift."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    document["paths"]["/api/v1/health/live"]["get"]["summary"] = value
    changed = generated.replace(
        "         * Liveness\n", f"         * {value}\n", 1
    )
    assert changed != generated
    return document, changed


def test_committed_tree_passes() -> None:
    snap, gen, smk = _bytes()
    found = guard.failures(json.loads(snap), gen, smk)
    assert not found, found


def test_coordinated_summary_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent literal can catch it."""
    document, generated = _co_revert_summary()
    found = guard.failures(document, generated, SMOKE)
    assert any("_ANNOTATION_DIGEST" in problem for problem in found), found


def test_one_sided_snapshot_summary_rename_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    document["paths"]["/api/v1/health/live"]["get"]["summary"] = "Liveness v2"
    found = _run(document)
    assert any(
        "_ANNOTATION_DIGEST" in problem or "summary disagrees" in problem
        for problem in found
    ), found


def test_one_sided_generated_summary_rename_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8").replace(
        "         * Liveness\n", "         * Liveness v2\n", 1
    )
    snap, _gen, smk = _bytes()
    found = guard.failures(json.loads(snap), generated, smk)
    assert any("summary disagrees" in problem for problem in found), found


def test_coordinated_description_co_revert_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    description = document["paths"]["/api/v1/health/ready"]["get"]["description"]
    first = description.splitlines()[0]
    document["paths"]["/api/v1/health/ready"]["get"]["description"] = (
        first + " (changed)"
    )
    changed = generated.replace(
        f"@description {first}", f"@description {first} (changed)", 1
    )
    assert changed != generated
    found = guard.failures(document, changed, SMOKE)
    assert any("_ANNOTATION_DIGEST" in problem for problem in found), found


def test_description_only_change_moves_the_digest() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    original = guard._digest(guard._snapshot_rows(document))
    document["paths"]["/api/v1/health/live"]["get"]["description"] = "changed"
    assert guard._digest(guard._snapshot_rows(document)) != original


def test_deprecated_only_change_moves_the_digest() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    original = guard._digest(guard._snapshot_rows(document))
    document["paths"]["/api/v1/health/live"]["get"]["deprecated"] = True
    assert guard._digest(guard._snapshot_rows(document)) != original


def test_dropped_summary_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    del document["paths"]["/api/v1/health/live"]["get"]["summary"]
    found = _run(document)
    assert found, "a dropped summary must be caught"


def test_the_digest_is_an_independent_literal() -> None:
    """Re-deriving the digest from the artifact would make the pin vacuous."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_ANNOTATION_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert value == guard._digest(guard._snapshot_rows(document))


def test_the_count_doors_are_load_bearing() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    rows = guard._snapshot_rows(document)
    original = guard._EXPECTED_DESCRIPTION_COUNT
    guard._EXPECTED_DESCRIPTION_COUNT = original + 1
    try:
        found = guard.failures(
            document,
            guard.GENERATED.read_text(encoding="utf-8"),
            SMOKE,
        )
    finally:
        guard._EXPECTED_DESCRIPTION_COUNT = original
    assert any("description count drifted" in problem for problem in found), found
    assert len(rows) == guard._EXPECTED_OPERATION_COUNT


def test_the_wiring_is_pinned_in_all_three_places() -> None:
    assert f"{guard.SELF} --self-test" in SMOKE
    assert f"scripts/{guard.SELF}" in REGISTRY
    assert "scripts/test_openapi_operation_annotations.py" in SMOKE
    assert "scripts/test_openapi_operation_annotations.py" in REGISTRY
    assert f"scripts/{guard.SELF}" in TEETH


def test_a_dropped_self_test_wire_is_rejected() -> None:
    rewired = SMOKE.replace(
        f"{guard.SELF} --self-test", f"# {guard.SELF} --self-test", 1
    )
    assert rewired != SMOKE
    found = guard.failures(
        json.loads(guard.SNAPSHOT.read_text(encoding="utf-8")),
        guard.GENERATED.read_text(encoding="utf-8"),
        rewired,
    )
    assert any("not wired" in problem for problem in found), found


def test_a_gutted_self_test_would_be_named() -> None:
    """The teeth guard pins the shape of the evidence this guard emits."""
    assert f"scripts/{guard.SELF}" in TEETH
    assert guard.SELF in TEETH

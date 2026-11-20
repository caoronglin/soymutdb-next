"""Regression coverage for ``scripts/check_openapi_operation_annotations.py``.

The guard pins the published per-operation annotation prose to a hand-written
literal. These cases prove each failure direction on real committed bytes,
and that the wiring and the literal cannot quietly rot. Collected by the
contracts layer's ``tests=()`` array; stdlib-only, no Python 3.15 needed.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_openapi_operation_annotations as guard  # noqa: E402

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


def _co_revert_description(value: str = "Liveness probe (DRIFTED)") -> tuple[dict, str]:
    """Rewrite one operation description in both halves -- the decisive drift.

    #269 pins summaries; a coordinated DESCRIPTION co-revert is the residual
    hole this guard closes. Both halves agree and the provenance blobs would
    be re-pinned in the same reviewed regenerate.
    """
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    operation = document["paths"]["/api/v1/health/live"]["get"]
    first = operation["description"].splitlines()[0]
    operation["description"] = value
    changed = generated.replace(f"@description {first}", f"@description {value}", 1)
    assert changed != generated
    return document, changed


def test_committed_tree_passes() -> None:
    snap, gen, smk = _bytes()
    found = guard.failures(json.loads(snap), gen, smk)
    assert not found, found


def test_coordinated_description_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent literal can catch it."""
    document, generated = _co_revert_description()
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


def test_second_operation_description_co_revert_is_rejected() -> None:
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


def test_the_digest_does_not_duplicate_the_summary_pin() -> None:
    """#269 owns summaries; this literal covers the residual dimensions only."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    original = guard._digest(guard._snapshot_rows(document))
    document["paths"]["/api/v1/health/live"]["get"]["summary"] = "Liveness v2"
    assert guard._digest(guard._snapshot_rows(document)) == original


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


_CONTINUATION_LINE = (
    "Baseline gates PostgreSQL only; extended also gates the Redis broker."
)
_OTHER_CONTINUATION_LINE = (
    "Password strength is validated both client-side and server-side."
)


def _continuation_drift() -> str:
    """One-sided generated rewrite: the decisive co-revert shape for this door."""
    generated = guard.GENERATED.read_text(encoding="utf-8")
    changed = generated.replace(
        f"*     {_CONTINUATION_LINE}",
        f"*     {_CONTINUATION_LINE} (REWRITTEN)",
        1,
    )
    assert changed != generated
    return changed


def test_one_sided_generated_continuation_rewrite_is_rejected() -> None:
    """The snapshot half is pinned; only the generated projection is blind."""
    snap, _gen, smk = _bytes()
    found = guard.failures(json.loads(snap), _continuation_drift(), smk)
    assert any("_CONTINUATION_DIGEST" in problem for problem in found), found


def test_dropped_generated_continuation_is_named_by_the_count_door() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    dropped = generated.replace(f"*     {_CONTINUATION_LINE}\n", "", 1)
    assert dropped != generated
    snap, _gen, smk = _bytes()
    found = guard.failures(json.loads(snap), dropped, smk)
    assert any("continuation line count" in problem for problem in found), found
    assert any("_CONTINUATION_DIGEST" in problem for problem in found), found


def test_same_count_continuation_relocation_is_named_only_by_the_digest() -> None:
    """A swap keeps every count door silent; the digest must be load-bearing."""
    generated = guard.GENERATED.read_text(encoding="utf-8")
    swapped = (
        generated.replace(f"*     {_CONTINUATION_LINE}", "@@A@@", 1)
        .replace(f"*     {_OTHER_CONTINUATION_LINE}", "@@B@@", 1)
        .replace("@@A@@", f"*     {_OTHER_CONTINUATION_LINE}", 1)
        .replace("@@B@@", f"*     {_CONTINUATION_LINE}", 1)
    )
    assert swapped != generated
    snap, _gen, smk = _bytes()
    found = guard.failures(json.loads(snap), swapped, smk)
    assert any("_CONTINUATION_DIGEST" in problem for problem in found), found
    assert not any("continuation line count" in problem for problem in found), found
    assert not any("continuation lines span" in problem for problem in found), found


def test_continuation_digest_is_an_independent_literal() -> None:
    """The pin is a hand-written string, not computed from the bytes it guards."""
    source = (ROOT / "scripts" / guard.SELF).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_CONTINUATION_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    generated = guard.GENERATED.read_text(encoding="utf-8")
    assert value == guard._continuation_digest(guard.continuation_rows(generated))


def test_continuation_count_doors_are_load_bearing() -> None:
    snap, gen, smk = _bytes()
    document = json.loads(snap)
    original = guard._EXPECTED_CONTINUATION_LINES
    guard._EXPECTED_CONTINUATION_LINES = original + 1
    try:
        found = guard.failures(document, gen, smk)
    finally:
        guard._EXPECTED_CONTINUATION_LINES = original
    assert any("continuation line count" in problem for problem in found), found
    original_paths = guard._EXPECTED_CONTINUATION_PATHS
    guard._EXPECTED_CONTINUATION_PATHS = original_paths + 1
    try:
        found = guard.failures(document, gen, smk)
    finally:
        guard._EXPECTED_CONTINUATION_PATHS = original_paths
    assert any("continuation lines span" in problem for problem in found), found


def test_co_reverted_continuation_pin_lets_a_drift_walk_through() -> None:
    """Positive control: re-pinning THIS literal beside the drift must pass.

    That is the reviewed regenerate action, not a hole. It proves the door
    reads the pinned literal rather than deriving an expectation from the
    artifact under guard (which would make the comparison self-referential).
    """
    snap, gen, smk = _bytes()
    drift = _continuation_drift()
    actual = guard._continuation_digest(guard.continuation_rows(drift))
    found = guard.failures(
        json.loads(snap), drift, smk, continuation_digest=actual
    )
    assert not found, found

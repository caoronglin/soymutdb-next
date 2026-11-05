"""Regression coverage for ``scripts/check_openapi_response_surface.py``.

The guard pins the published per-operation response surface to a hand-written
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

import check_openapi_response_surface as guard

SMOKE = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
REGISTRY = (ROOT / "scripts" / "check_contracts_registry_collection.py").read_text(
    encoding="utf-8"
)
TEETH = (ROOT / "scripts" / "check_contracts_self_test_teeth.py").read_text(
    encoding="utf-8"
)


def _co_revert_status() -> tuple[str, str]:
    """Rename one 204 -> 205 in both halves -- the decisive drift."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    responses = document["paths"]["/api/v1/auth/logout"]["post"]["responses"]
    responses["205"] = responses.pop("204")
    key = "    logout_api_v1_auth_logout_post: {"
    start = generated.find(key)
    assert start >= 0
    block = generated[start : start + 1600]
    changed = block.replace("            204: {", "            205: {", 1)
    assert changed != block
    return json.dumps(document, indent=2), generated[:start] + changed + generated[
        start + 1600 :
    ]


def test_committed_tree_passes() -> None:
    found = guard.failures()
    assert not found, found


def test_coordinated_status_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent literal can catch it."""
    snapshot, generated = _co_revert_status()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("drifted" in problem for problem in found), found


def test_one_sided_snapshot_status_rename_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    responses = document["paths"]["/api/v1/auth/logout"]["post"]["responses"]
    responses["205"] = responses.pop("204")
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("response codes disagree" in problem for problem in found), found


def test_one_sided_generated_status_rename_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    key = "    logout_api_v1_auth_logout_post: {"
    start = generated.find(key)
    block = generated[start : start + 1600]
    changed = block.replace("            204: {", "            205: {", 1)
    assert changed != block
    found = guard.failures(
        generated=generated[:start] + changed + generated[start + 1600 :]
    )
    assert any("response codes disagree" in problem for problem in found), found


def test_coordinated_description_co_revert_is_rejected() -> None:
    """#260 shipped a digest with no description column; this closes it."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    document["paths"]["/api/v1/health/live"]["get"]["responses"]["200"][
        "description"
    ] = "OK"
    key = "    liveness_api_v1_health_live_get: {"
    start = generated.find(key)
    assert start >= 0
    block = generated[start : start + 1600]
    changed = block.replace(
        "/** @description Successful Response */", "/** @description OK */", 1
    )
    assert changed != block
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        generated=generated[:start] + changed + generated[start + 1600 :],
    )
    assert any("drifted" in problem for problem in found), found


def test_the_digest_covers_the_description_column() -> None:
    """A description-only change must move the independent fixed point."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    original = guard._digest(guard._snapshot_rows(document))
    document["paths"]["/api/v1/health/live"]["get"]["responses"]["200"][
        "description"
    ] = "OK"
    assert guard._digest(guard._snapshot_rows(document)) != original


def test_coordinated_content_drop_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    document["paths"]["/api/v1/health/live"]["get"]["responses"]["200"].pop(
        "content", None
    )
    key = "    liveness_api_v1_health_live_get: {"
    start = generated.find(key)
    block = generated[start : start + 1600]
    changed = block.replace(
        "                content: {", "                content?: never;", 1
    )
    assert changed != block
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        generated=generated[:start] + changed + generated[start + 1600 :],
    )
    assert found, "a dropped content body in both halves must be caught"


def test_the_digest_is_an_independent_literal() -> None:
    """Re-deriving the digest from the artifact would make the pin vacuous."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_RESPONSE_SURFACE_DIGEST"
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
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        expected_entries=guard._EXPECTED_RESPONSE_ENTRIES + 1,
    )
    assert any("count is" in problem for problem in found), found


def test_the_wiring_is_pinned_in_all_three_places() -> None:
    assert f"scripts/{guard.SELF}" in SMOKE
    assert f"scripts/{guard.SELF}" in REGISTRY
    assert "scripts/test_openapi_response_surface.py" in SMOKE
    assert "scripts/test_openapi_response_surface.py" in REGISTRY
    assert f"scripts/{guard.SELF}" in TEETH


def test_a_gutted_self_test_would_be_named() -> None:
    """The teeth guard pins the shape of the evidence this guard emits."""
    assert "scripts/check_openapi_response_surface.py" in TEETH

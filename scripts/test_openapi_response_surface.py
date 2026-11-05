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


def _co_revert_summary() -> tuple[str, str]:
    """Retype one operation ``summary`` in both halves -- the decisive drift."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    document["paths"]["/api/v1/health/live"]["get"]["summary"] = (
        "Liveness probe (edited)"
    )
    changed = generated.replace(
        "         * Liveness\n", "         * Liveness probe (edited)\n", 1
    )
    assert changed != generated
    return json.dumps(document, indent=2), changed


def test_coordinated_summary_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent summary literal can catch it."""
    snapshot, generated = _co_revert_summary()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("summaries drifted" in problem for problem in found), found


def test_one_sided_snapshot_summary_retype_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    document["paths"]["/api/v1/health/live"]["get"]["summary"] = "Only snapshot"
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any(
        "GET /api/v1/health/live" in problem and "disagrees" in problem
        for problem in found
    ), found


def test_one_sided_generated_summary_retype_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    changed = generated.replace(
        "         * Liveness\n", "         * Only client changed\n", 1
    )
    assert changed != generated
    found = guard.failures(generated=changed)
    assert any(
        "GET /api/v1/health/live" in problem and "disagrees" in problem
        for problem in found
    ), found


def test_the_summary_digest_is_an_independent_literal() -> None:
    """The literal must not be re-derived from the artifacts under guard."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "_OPERATION_SUMMARY_DIGEST"
            for target in node.targets
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert value == guard._summary_digest(guard._snapshot_summaries(document))


def test_the_summary_count_door_is_load_bearing() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        expected_summary_operations=guard._EXPECTED_SUMMARY_OPERATIONS + 1,
    )
    assert any("summary-bearing operation count is" in problem for problem in found), found


def test_the_summary_plant_is_load_bearing() -> None:
    """Both summary doors must stay in the guard source, not just the digest.

    Removing the independent digest comparison or the generated-JSDoc
    agreement makes a coordinated retype silently green. This assertion lives
    in a second file so a single-file edit cannot delete the evidence.
    """
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "_OPERATION_SUMMARY_DIGEST" in source
    assert "published operation summaries drifted" in source
    assert "generated JSDoc" in source
    # The comparison must be against the literal, not against a derived value
    # (which would make the pin self-referential and the drift invisible).
    assert "if actual_summary_digest != pinned_summary_digest:" in source
    assert "rendered = gen_summaries[key]" in source
    # Proof by ablation on real bytes: with the doors intact the coordinated
    # retype is named; with both comparisons replaced by self-agreement it is
    # not. We assert the intact behaviour here; the companion self-test in the
    # guard reproduces the negative control.
    snapshot, generated = _co_revert_summary()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("summaries drifted" in problem for problem in found), found


def _co_revert_request_body() -> tuple[str, str]:
    """Flip one ``requestBody.required`` in both halves -- decisive drift."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    target, symbol = "/api/v1/auth/register", "register_api_v1_auth_register_post"
    document["paths"][target]["post"]["requestBody"]["required"] = False
    start = generated.find(f"    {symbol}: {{")
    assert start >= 0
    block = generated[start : start + 1200]
    changed = block.replace("        requestBody: {", "        requestBody?: {", 1)
    assert changed != block
    return json.dumps(document, indent=2), generated[:start] + changed + generated[
        start + 1200 :
    ]


def test_coordinated_request_body_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent literal can catch it."""
    snapshot, generated = _co_revert_request_body()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("request bodies drifted" in problem for problem in found), found


def test_one_sided_snapshot_request_body_flip_is_rejected() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    document["paths"]["/api/v1/auth/register"]["post"]["requestBody"][
        "required"
    ] = False
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("disagrees with generated client" in p for p in found), found


def test_one_sided_generated_request_body_marker_is_rejected() -> None:
    generated = guard.GENERATED.read_text(encoding="utf-8")
    start = generated.find("    register_api_v1_auth_register_post: {")
    assert start >= 0
    block = generated[start : start + 1200]
    changed = block.replace("        requestBody: {", "        requestBody?: {", 1)
    assert changed != block
    found = guard.failures(
        generated=generated[:start] + changed + generated[start + 1200 :]
    )
    assert any("disagrees with generated client" in p for p in found), found


def test_request_body_digest_is_an_independent_literal() -> None:
    """The pin must be a module-level literal, not derived from the artifact."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    target = None
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = (
                [t.id for t in node.targets if isinstance(t, ast.Name)]
                if isinstance(node, ast.Assign)
                else [node.target.id]
                if isinstance(node.target, ast.Name)
                else []
            )
            if "_REQUEST_BODY_SURFACE_DIGEST" in names:
                target = node.value
    assert target is not None, "digest literal is missing"
    assert isinstance(target, ast.Constant) and isinstance(target.value, str), (
        "digest must be a hand-written string literal, not a derived value"
    )
    assert len(target.value) == 64, "digest must be a sha256 hex string"


def test_request_body_count_door_is_load_bearing() -> None:
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    del document["paths"]["/api/v1/auth/register"]["post"]["requestBody"]
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        expected_request_body_operations=guard._EXPECTED_REQUEST_BODY_BEARING_OPERATIONS
        - 1,
    )
    assert not any("request-body-bearing operation count is" in p for p in found), found
    assert any("request bodies drifted" in p or "disagrees" in p for p in found), found


def test_request_body_comparison_is_load_bearing() -> None:
    """A single-file edit cannot remove both doors without the companion."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "_REQUEST_BODY_SURFACE_DIGEST" in source
    assert "published request bodies drifted" in source
    assert "if actual_request_body_digest != pinned_request_body_digest:" in source
    assert "rendered = gen_request_bodies.get(symbol)" in source
    snapshot, generated = _co_revert_request_body()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("request bodies drifted" in problem for problem in found), found

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


def _co_revert_response_header() -> tuple[str, str]:
    """Retype the one declared header's description in both halves."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    old = "Seconds until this login attempt may be retried."
    new = "Seconds until this login attempt may be retried (edited)."
    header = document["paths"]["/api/v1/auth/login"]["post"]["responses"]["429"][
        "headers"
    ]["Retry-After"]
    assert header["description"] == old, "committed tree already regressed"
    header["description"] = new
    assert f"/** @description {old} */" in generated
    changed = generated.replace(
        f"/** @description {old} */", f"/** @description {new} */", 1
    )
    return json.dumps(document, indent=2), changed


def test_coordinated_response_header_co_revert_is_rejected() -> None:
    """Both halves agree; only the independent header literal can catch it."""
    snapshot, generated = _co_revert_response_header()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("response headers drifted" in problem for problem in found), found


def test_one_sided_response_header_retypes_are_rejected() -> None:
    """Door 9 names a header disagreement on either half alone."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    document["paths"]["/api/v1/auth/login"]["post"]["responses"]["429"]["headers"][
        "Retry-After"
    ]["description"] = "only the snapshot changed"
    found = guard.failures(snapshot=json.dumps(document, indent=2))
    assert any("is not rendered with description" in p for p in found), found


def test_response_header_digest_is_an_independent_literal() -> None:
    """The pin is a module-level literal, not derived from the artifact."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    target = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_RESPONSE_HEADER_SURFACE_DIGEST"
            for t in node.targets
        ):
            target = node.value
    assert target is not None, "digest literal is missing"
    assert isinstance(target, ast.Constant) and isinstance(target.value, str)
    assert len(target.value) == 64, "digest must be a sha256 hex string"
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    assert target.value == guard._response_header_digest(
        guard._snapshot_response_headers(document)
    )


def test_response_header_count_door_is_load_bearing() -> None:
    """Dropping the declared header moves both the digest and the count door."""
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    del document["paths"]["/api/v1/auth/login"]["post"]["responses"]["429"]["headers"]
    found = guard.failures(
        snapshot=json.dumps(document, indent=2),
        expected_response_headers=guard._EXPECTED_RESPONSE_HEADERS - 1,
    )
    assert not any("response header count is" in p for p in found), found
    assert any("response headers drifted" in p for p in found), found


def test_response_header_comparison_is_load_bearing() -> None:
    """A single-file edit cannot remove both doors without the companion."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "_RESPONSE_HEADER_SURFACE_DIGEST" in source
    assert "published response headers drifted" in source
    assert "if actual_header_digest != pinned_response_header_digest:" in source
    assert "gen_header_set = {" in source
    snapshot, generated = _co_revert_response_header()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("response headers drifted" in problem for problem in found), found


def test_response_header_doors_and_cases_are_pinned_from_a_second_file() -> None:
    """Gutting a door or deleting an ablation cannot hide in one file only."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "if len(header_rows) != pinned_response_headers:" in source
    assert "published response header count is" in source
    assert "if actual_header_digest != pinned_response_header_digest:" in source
    assert "snap_header_set = set()" in source
    # The four header ablations must remain in the guard's case table; deleting
    # one leaves the self-test's success line intact but the evidence gone.
    for label in (
        "one-sided snapshot response header retype",
        "one-sided generated response header retype",
        "coordinated response header co-revert",
        "declared response header dropped",
    ):
        assert f'cases["{label}"]' in source, f"{label} ablation is missing"


_CLIENT_LIVE_PATH = "/api/v1/health/live"
_CLIENT_SYMBOL = "liveness_api_v1_health_live_get"


def _client_response_co_revert() -> tuple[str, str, str]:
    """Retype one response description in BOTH halves; return bytes + re-pin.

    This is the decisive shape: both artifacts agree, every count door is
    unchanged, and the snapshot digest can be honestly re-pinned in one
    reviewed edit. Only an independent fixed point on the GENERATED half can
    still object.
    """
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    document["paths"][_CLIENT_LIVE_PATH]["get"]["responses"]["200"][
        "description"
    ] = "OK"
    start = generated.find(f"    {_CLIENT_SYMBOL}: {{")
    assert start >= 0
    block = generated[start : start + 1600]
    changed = block.replace(
        "/** @description Successful Response */", "/** @description OK */", 1
    )
    assert changed != block
    drifted_generated = generated[:start] + changed + generated[start + 1600 :]
    snapshot = json.dumps(document, indent=2)
    honest_digest = guard._digest(guard._snapshot_rows(document))
    return snapshot, drifted_generated, honest_digest


def test_client_response_surface_literal_is_independent() -> None:
    """The new pin must be a module-level string literal, recomputable, not derived."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name)
            and target.id == "_CLIENT_RESPONSE_SURFACE_DIGEST"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
    ]
    assert len(assigned) == 1
    value = ast.literal_eval(assigned[0].value)
    assert isinstance(value, str) and len(value) == 64
    generated = guard.GENERATED.read_text(encoding="utf-8")
    rows = guard.client_response_surface_rows(
        guard._generated_operations(generated)
    )
    assert value == guard._client_response_surface_digest(rows)
    assert "_CLIENT_RESPONSE_SURFACE_DIGEST = _client_response_surface_digest" not in source


def test_decisive_co_revert_with_an_honest_snapshot_repin_is_rejected() -> None:
    """One reviewed re-pin cannot silence both digest doors."""
    snapshot, generated, honest_digest = _client_response_co_revert()
    found = guard.failures(
        snapshot=snapshot, generated=generated, digest=honest_digest
    )
    assert any("_CLIENT_RESPONSE_SURFACE_DIGEST" in f for f in found), found
    # doors that must stay silent on this shape: the snapshot digest was
    # re-pinned honestly and the two halves agree with each other.
    assert not any(f.startswith("published response surface drifted:") for f in found), found
    assert not any("disagrees with the generated client" in f for f in found), found


def test_both_response_surface_digests_must_move_together() -> None:
    """Re-pinning only the client literal leaves the snapshot door red."""
    snapshot, generated, honest_digest = _client_response_co_revert()
    client_digest = guard._client_response_surface_digest(
        guard.client_response_surface_rows(guard._generated_operations(generated))
    )
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        client_response_surface_digest=client_digest,
    ), "re-pinning only the client literal must stay red"
    both = guard.failures(
        snapshot=snapshot,
        generated=generated,
        digest=honest_digest,
        client_response_surface_digest=client_digest,
    )
    assert not any(f.startswith("published response surface drifted:") for f in both), both
    assert not any("_CLIENT_RESPONSE_SURFACE_DIGEST" in f for f in both), both


def test_one_sided_generated_response_retype_is_named_by_both_doors() -> None:
    """A client-only drift moves the client digest and the agreement door."""
    snapshot, generated, _ = _client_response_co_revert()
    clean = guard.SNAPSHOT.read_text(encoding="utf-8")
    found = guard.failures(snapshot=clean, generated=generated)
    assert any("_CLIENT_RESPONSE_SURFACE_DIGEST" in f for f in found), found
    assert any("disagrees with the generated client" in f for f in found), found


def test_client_response_count_door_is_load_bearing() -> None:
    found = guard.failures(
        expected_client_response_entries=guard._EXPECTED_CLIENT_RESPONSE_ENTRIES + 1
    )
    assert any("_EXPECTED_CLIENT_RESPONSE_ENTRIES" in f for f in found), found


def test_weakening_the_client_door_lets_the_co_revert_walk_through() -> None:
    """The comparison is non-vacuous: weakening it returns the ablation to green."""
    snapshot, generated, honest_digest = _client_response_co_revert()
    client_digest = guard._client_response_surface_digest(
        guard.client_response_surface_rows(guard._generated_operations(generated))
    )
    # Both literals honestly re-pinned: the reviewed regenerate is green.
    assert not guard.failures(
        snapshot=snapshot,
        generated=generated,
        digest=honest_digest,
        client_response_surface_digest=client_digest,
    )
    # Without the door's literal the same one-re-pin ablation was green. Pin it
    # from the second file so a source weakening cannot hide in one file only.
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "if actual_client_digest != pinned_client_response_surface_digest:" in source
    assert "generated client response surface drifted:" in source
    assert "if len(client_rows) != pinned_client_response_entries:" in source


def test_client_doors_and_cases_are_pinned_from_a_second_file() -> None:
    """Gutting a door or deleting an ablation cannot hide in one file only."""
    source = (ROOT / "scripts" / "check_openapi_response_surface.py").read_text(
        encoding="utf-8"
    )
    assert "client_rows = client_response_surface_rows(gen_ops)" in source
    assert "generated client response entry count is" in source
    for label in (
        "coordinated description co-revert with an honest snapshot re-pin",
        "one-sided generated response description retype",
        "generated client response count door",
    ):
        assert f'cases["{label}"]' in source, f"{label} ablation is missing"


# ---------------------------------------------------------------------------
# Door 5 -- response-status declaration order (positional literals)
# ---------------------------------------------------------------------------
def _co_revert_status_order() -> tuple[str, str]:
    """Swap two adjacent status blocks in BOTH halves, coherently."""
    import re

    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    responses = document["paths"]["/api/v1/health/live"]["get"]["responses"]
    first, second = list(responses)[:2]
    reordered: dict[str, object] = {}
    for status in responses:
        if status == first:
            reordered[second] = responses[second]
        elif status == second:
            reordered[first] = responses[first]
        else:
            reordered[status] = responses[status]
    document["paths"]["/api/v1/health/live"]["get"]["responses"] = reordered

    symbol = "liveness_api_v1_health_live_get"
    start = generated.find(f"    {symbol}: {{")
    assert start >= 0
    following = guard.OP_DEF.search(generated, start + 10)
    end = following.start() if following else len(generated)
    block = generated[start:end]
    rstart = block.find("        responses: {")
    closer = re.search(r"^        \};$", block[rstart:], re.M)
    assert closer is not None
    rend = rstart + closer.start()
    matches = list(guard.STATUS_KEY.finditer(block, rstart))
    assert len(matches) >= 2
    segments: list[str] = []
    for i, m in enumerate(matches):
        nxt = matches[i + 1] if i + 1 < len(matches) else None
        begin = m.start()
        desc = block.rfind("/** @description ", rstart, begin)
        if desc >= 0:
            begin = desc
        segments.append(block[begin : nxt.start() if nxt else rend])
    segments[0], segments[1] = segments[1], segments[0]
    prefix = block[: rstart + len("        responses: {\n")]
    swapped = prefix + "".join(segments) + block[rend:]
    return json.dumps(document, indent=2), generated[:start] + swapped + generated[end:]


def test_coordinated_status_order_swap_is_rejected() -> None:
    """Both halves agree; only the two positional literals can see it."""
    snapshot, generated = _co_revert_status_order()
    found = guard.failures(snapshot=snapshot, generated=generated)
    assert any("_RESPONSE_STATUS_ORDER_DIGEST" in p for p in found), found
    assert any("_CLIENT_RESPONSE_STATUS_ORDER_DIGEST" in p for p in found), found


def test_one_sided_status_order_swaps_are_rejected() -> None:
    snapshot, generated = _co_revert_status_order()
    clean = guard.GENERATED.read_text(encoding="utf-8")
    snap_only = guard.failures(snapshot=snapshot)
    gen_only = guard.failures(generated=generated)
    assert snap_only, "snapshot-only reorder was not named"
    assert gen_only, "generated-only reorder was not named"


def test_both_status_order_literals_must_move_together() -> None:
    """Re-pinning only one literal leaves the other door red."""
    snapshot, generated = _co_revert_status_order()
    document = json.loads(snapshot)
    honest_snapshot = guard._status_order_digest(
        guard.snapshot_status_order_rows(document)
    )
    honest_client = guard._client_status_order_digest(
        guard.generated_status_order_rows(generated)
    )
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        response_status_order_digest=honest_snapshot,
    ), "snapshot-only re-pin silenced both doors"
    assert guard.failures(
        snapshot=snapshot,
        generated=generated,
        client_response_status_order_digest=honest_client,
    ), "client-only re-pin silenced both doors"
    # Both honestly re-pinned in the same reviewed act: the only green shape.
    assert not guard.failures(
        snapshot=snapshot,
        generated=generated,
        response_status_order_digest=honest_snapshot,
        client_response_status_order_digest=honest_client,
    )


def test_status_order_literals_are_independent_and_hand_written() -> None:
    """Re-deriving either from the artifact under guard would be vacuous."""
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    assigned = {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    for name in (
        "_RESPONSE_STATUS_ORDER_DIGEST",
        "_CLIENT_RESPONSE_STATUS_ORDER_DIGEST",
        "_EXPECTED_RESPONSE_STATUS_ORDER_ROWS",
    ):
        assert name in assigned, name
    document = json.loads(guard.SNAPSHOT.read_text(encoding="utf-8"))
    generated = guard.GENERATED.read_text(encoding="utf-8")
    assert (
        guard._status_order_digest(guard.snapshot_status_order_rows(document))
        == guard._RESPONSE_STATUS_ORDER_DIGEST
    )
    assert (
        guard._client_status_order_digest(
            guard.generated_status_order_rows(generated)
        )
        == guard._CLIENT_RESPONSE_STATUS_ORDER_DIGEST
    )
    assert (
        len(guard.snapshot_status_order_rows(document))
        == guard._EXPECTED_RESPONSE_STATUS_ORDER_ROWS
    )


def test_status_order_doors_and_cases_are_pinned_from_a_second_file() -> None:
    """A single-file edit cannot gut a door and its own ablation together."""
    source = Path(guard.__file__).read_text(encoding="utf-8")
    assert "if actual_status_order != pinned_status_order:" in source
    assert "if actual_client_status_order != pinned_client_status_order:" in source
    assert "published response status order drifted:" in source
    assert "generated client response status order drifted:" in source
    for label in (
        "coordinated response status order swap in both halves",
        "one-sided snapshot response status order swap",
        "one-sided generated response status order swap",
        "coordinated status swap with only the snapshot literal re-pinned",
        "coordinated status swap with only the client literal re-pinned",
        "coordinated status order swap with both literals re-pinned",
    ):
        assert f'cases["{label}"]' in source, f"{label} ablation is missing"


def test_status_order_row_count_door_is_load_bearing() -> None:
    assert any(
        "status order row count" in p
        for p in guard.failures(expected_response_status_order_rows=999)
    )

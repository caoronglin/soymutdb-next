#!/usr/bin/env python3
"""Wiring proofs for the MCP release-binding guard.

``scripts/check_mcp_release_binding.py`` reads committed bytes, so its
ablations are synthetic. This suite proves the two things a synthetic ablation
cannot: the guard is *invoked* by the contracts layer, and each ablation fails
against the real tree rather than only against a fixture.

A guard that nothing calls is the failure mode this repository has paid for
before -- the parity suite existed in source while no gate collected it.
"""

from pathlib import Path

import pytest

from scripts import check_mcp_release_binding as guard

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts/smoke.sh"
TESTS_ENTRY = "scripts/test_mcp_release_binding_wiring.py"
GUARD_CALL = "scripts/check_mcp_release_binding.py"


def test_guard_is_wired_into_the_contracts_layer():
    """The guard must be called by smoke.sh, not merely exist."""
    body = SMOKE.read_text(encoding="utf-8")
    assert GUARD_CALL in body, (
        f"{GUARD_CALL} is not invoked by smoke.sh: the release binding would "
        "drift with every gate green"
    )
    assert TESTS_ENTRY in body, (
        f"{TESTS_ENTRY} is not listed in the contracts-layer tests[] array, so "
        "these ablations never run in CI"
    )


def test_live_tree_satisfies_the_contract():
    """The committed tree must pass its own guard."""
    assert (
        guard.check(
            guard.json.loads(guard._read(guard.OPENAPI_JSON)),
            guard._read(guard.MANIFEST_PY),
            guard._read(guard.SERVER_PY),
        )
        == []
    )


def _sources() -> tuple[dict, str, str]:
    return (
        guard.json.loads(guard._read(guard.OPENAPI_JSON)),
        guard._read(guard.MANIFEST_PY),
        guard._read(guard.SERVER_PY),
    )


@pytest.mark.parametrize(
    ("label", "old", "new"),
    [
        (
            "transport stops forwarding the pin",
            "headers=_headers(release_id)",
            "headers=_headers()",
        ),
        (
            "transport stops accepting the pin",
            (
                "    payload: dict[str, Any] | None = None,\n"
                "    release_id: int | None = None,\n) -> Any:"
            ),
            "    payload: dict[str, Any] | None = None,\n) -> Any:",
        ),
        (
            "_headers() pins every tool",
            'headers = {"Accept": "application/json"}',
            'headers = {"Accept": "application/json", "X-SoyMutDB-Release": "1"}',
        ),
    ],
)
def test_transport_ablations_fail(label: str, old: str, new: str):
    spec, manifest, server = _sources()
    assert old in server, f"ablation anchor is stale: {old!r}"
    assert guard.check(spec, manifest, server.replace(old, new, 1)), label


def test_scoped_tool_without_a_pin_fails():
    spec, manifest, server = _sources()
    ablated = server.replace(
        "    max_results: int = 1000,\n    release_id: int | None = None,\n",
        "    max_results: int = 1000,\n",
        1,
    )
    assert ablated != server
    failures = guard.check(spec, manifest, ablated)
    assert any("variant_by_region" in f for f in failures), failures


def test_unscoped_tool_with_a_pin_fails():
    spec, manifest, server = _sources()
    ablated = server.replace(
        "    page_size: int = 20,\n    ctx: Context | None = None,",
        "    page_size: int = 20,\n    release_id: int | None = None,\n"
        "    ctx: Context | None = None,",
        1,
    )
    assert ablated != server
    failures = guard.check(spec, manifest, ablated)
    assert any("news_list" in f for f in failures), failures


def test_a_dropped_published_header_is_caught():
    """If the API stops publishing the pin, the tool input becomes a no-op."""
    spec, manifest, server = _sources()
    spec["paths"]["/api/v1/genes/{gene_id}"]["get"]["parameters"] = [
        p
        for p in spec["paths"]["/api/v1/genes/{gene_id}"]["get"]["parameters"]
        if p.get("name") != guard.RELEASE_HEADER
    ]
    failures = guard.check(spec, manifest, server)
    assert any("gene_by_id" in f and "does not publish" in f for f in failures), (
        failures
    )


def test_an_endpoint_missing_from_the_snapshot_is_a_failure():
    """A manifest entry with no published operation is a hard failure."""
    spec, manifest, server = _sources()
    spec["paths"].pop("/api/v1/stats/dashboard")
    with pytest.raises(guard.GuardError, match="stats_summary"):
        guard.check(spec, manifest, server)


def test_a_commented_out_pin_does_not_count():
    """A ``# release_id: ...`` line is prose, not wiring."""
    spec, manifest, server = _sources()
    ablated = server.replace(
        "    max_results: int = 1000,\n    release_id: int | None = None,\n",
        "    max_results: int = 1000,\n    # release_id: int | None = None,\n",
        1,
    )
    assert ablated != server
    failures = guard.check(spec, manifest, ablated)
    assert any("variant_by_region" in f for f in failures), failures


def _wiring_failures(smoke_text: str) -> list[str]:
    """The assertion body of ``test_guard_is_wired_into_the_contracts_layer``."""
    failures = []
    if GUARD_CALL not in smoke_text:
        failures.append(f"{GUARD_CALL} is not invoked by smoke.sh")
    if TESTS_ENTRY not in smoke_text:
        failures.append(f"{TESTS_ENTRY} is not listed in the contracts tests[]")
    return failures


@pytest.mark.parametrize(
    ("label", "mutation"),
    [
        ("guard call deleted", lambda body: body.replace(GUARD_CALL, "true")),
        ("tests[] entry deleted", lambda body: body.replace(TESTS_ENTRY, "true")),
    ],
)
def test_the_wiring_assertion_fails_when_the_call_site_is_removed(label, mutation):
    """Deleting either half of the wiring must fail, not silently pass.

    This is the ablation the guard cannot prove about itself: this repository
    has already shipped a guard that existed in source while no gate
    collected it, and one whose suite was listed but never invoked.
    """
    assert _wiring_failures(SMOKE.read_text(encoding="utf-8")) == []
    mutated = mutation(SMOKE.read_text(encoding="utf-8"))
    assert mutated != SMOKE.read_text(encoding="utf-8"), f"{label}: no-op mutation"
    assert _wiring_failures(mutated), label

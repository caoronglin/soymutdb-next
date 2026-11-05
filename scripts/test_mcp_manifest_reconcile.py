"""Regression cases for the MCP manifest reconciliation guard.

Each case mutates one of the three declarations held in memory and asserts the
guard names that specific drift. The committed tree is the positive control, so
a guard that has quietly stopped reading one of the sources fails here rather
than passing everything.
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_mcp_manifest_reconcile import (
    DEPLOY,
    MANIFEST,
    RATELIMIT,
    SERVER,
    check,
    parse_limiters,
    parse_manifest,
    parse_tools,
)

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"


def _sources() -> tuple[str, str, str, str | None]:
    return (
        MANIFEST.read_text(encoding="utf-8"),
        SERVER.read_text(encoding="utf-8"),
        RATELIMIT.read_text(encoding="utf-8"),
        DEPLOY.read_text(encoding="utf-8") if DEPLOY.is_file() else None,
    )


def _failures(**overrides: str) -> list[str]:
    manifest, server, ratelimit, deploy = _sources()
    return check(
        overrides.get("manifest", manifest),
        overrides.get("server", server),
        overrides.get("ratelimit", ratelimit),
        overrides.get("deploy", deploy) if deploy is not None else None,
    )


def test_the_committed_tree_reconciles_all_three_declarations() -> None:
    assert _failures() == []
    tools = parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    assert len(tools) == len(parse_tools(SERVER.read_text(encoding="utf-8")))
    limiters = parse_limiters(RATELIMIT.read_text(encoding="utf-8"))
    assert set(limiters) == {"GLOBAL_LIMITER", "SUBMIT_LIMITER"}


def test_a_parameter_the_manifest_never_publishes_is_rejected() -> None:
    manifest, server, _, _ = _sources()
    # gene_by_id gains a keyword in server.py only: clients cannot discover it.
    mutated = server.replace(
        "    gene_id: str, assembly_id: int | None = None, ctx: Context | None = None",
        "    gene_id: str,\n    assembly_id: int | None = None,\n"
        "    include_neighbours: bool = False,\n    ctx: Context | None = None",
        1,
    )
    assert mutated != server
    failures = _failures(server=mutated)
    assert any(
        "gene_by_id" in f and "include_neighbours" in f and "never publishes it" in f
        for f in failures
    ), failures


def test_a_published_input_the_server_dropped_is_rejected() -> None:
    manifest, server, _, _ = _sources()
    mutated = server.replace(
        "    gene_id: str, assembly_id: int | None = None, ctx: Context | None = None",
        "    gene_id: str, ctx: Context | None = None",
        1,
    )
    assert mutated != server
    failures = _failures(server=mutated)
    assert any(
        "gene_by_id" in f and "assembly_id" in f and "no such parameter" in f
        for f in failures
    ), failures


def test_a_tool_that_dropped_the_global_budget_is_rejected() -> None:
    _, server, _, _ = _sources()
    keep = "\n".join(
        line
        for line in server.splitlines()
        if not line.lstrip().startswith("rate_err = _rate_limit_error(ctx)")
    )
    # news_list (and every other plain tool) loses its guard.
    failures = _failures(server=keep)
    assert any("bypasses the global 60/min budget" in f for f in failures), failures
    assert sum("bypasses the global" in f for f in failures) == 7, failures


def test_a_commented_out_guard_does_not_count() -> None:
    _, server, _, _ = _sources()
    mutated = server.replace(
        "    rate_err = _rate_limit_error(ctx, submit_quota=True)",
        "    # rate_err = _rate_limit_error(ctx, submit_quota=True)",
        1,
    )
    assert mutated != server
    failures = _failures(server=mutated)
    assert any("blast_submit" in f and "submission quota" in f for f in failures), failures


def test_a_second_tool_spending_the_submission_quota_is_rejected() -> None:
    _, server, _, _ = _sources()
    mutated = server.replace(
        '    """GET {API_BASE}/api/v1/news → paginated list."""\n'
        "    rate_err = _rate_limit_error(ctx)",
        '    """GET {API_BASE}/api/v1/news → paginated list."""\n'
        "    rate_err = _rate_limit_error(ctx, submit_quota=True)",
        1,
    )
    assert mutated != server
    failures = _failures(server=mutated)
    assert any(
        "news_list" in f and "only blast_submit may" in f for f in failures
    ), failures


def test_a_relaxed_global_budget_is_rejected() -> None:
    _, _, ratelimit, _ = _sources()
    mutated = ratelimit.replace(
        'GLOBAL_LIMITER = get_limiter(60, 60.0, name="global")',
        'GLOBAL_LIMITER = get_limiter(600, 60.0, name="global")',
    )
    assert mutated != ratelimit
    failures = _failures(ratelimit=mutated)
    assert any("GLOBAL_LIMITER is 600" in f for f in failures), failures


def test_a_limiter_that_hardcodes_the_process_local_backend_is_rejected() -> None:
    _, _, ratelimit, _ = _sources()
    mutated = ratelimit.replace(
        'GLOBAL_LIMITER = get_limiter(60, 60.0, name="global")',
        'GLOBAL_LIMITER = FixedWindowLimiter(60, 60.0, name="global")',
    )
    assert mutated != ratelimit
    failures = _failures(ratelimit=mutated)
    assert any("hardcodes the in-memory backend" in f for f in failures), failures


def test_a_deployment_that_never_sets_the_redis_url_is_rejected() -> None:
    """The committed compose file sets it; stripping that is a named failure."""
    manifest, server, ratelimit, deploy = _sources()
    assert deploy is not None, "docker-compose.yml is required for this pin"
    assert "SOYMUTDB_MCP_REDIS_URL" in deploy
    stripped = "\n".join(
        line for line in deploy.splitlines() if "SOYMUTDB_MCP_REDIS_URL" not in line
    )
    assert "SOYMUTDB_MCP_REDIS_URL" not in stripped
    failures = check(manifest, server, ratelimit, stripped)
    assert any("SOYMUTDB_MCP_REDIS_URL" in f for f in failures), failures
    assert check(manifest, server, ratelimit, deploy) == []


def test_a_new_tool_needs_no_allowlist_edit() -> None:
    """Positive control: three agreeing declarations are sufficient."""
    manifest, server, ratelimit, deploy = _sources()
    tree = parse_manifest(manifest)
    assert all(tool["name"] != "news_list_two" for tool in tree)
    grown = "\n".join(
        (
            "    {",
            '        "name": "news_list_two",',
            '        "type": "read",',
            '        "description": "Second spelling of the news listing.",',
            '        "endpoint": "GET /api/v1/news",',
            '        "status": "implemented",',
            '        "auth": "public (API bearer forwarded when configured)",',
            '        "rate_limit": "global 60/min per client",',
            '        "inputs": {"page": "int, optional"},',
            '        "outputs": {"total": "int"},',
            "    },",
        )
    )
    header = "TOOLS: list[dict[str, object]] = [\n"
    new_manifest = manifest.replace(header, header + grown + "\n", 1)
    new_server = server + (
        '\n\n@mcp.tool(name="news_list_two", description="Second spelling.")\n'
        "async def news_list_two(page: int = 1, ctx: Context | None = None) -> dict[str, Any]:\n"
        "    rate_err = _rate_limit_error(ctx)\n"
        "    if rate_err is not None:\n"
        "        return rate_err\n"
        '    return await _safe_call(_api_request("GET", "/api/v1/news"))\n'
    )
    assert check(new_manifest, new_server, ratelimit, deploy) == []


def test_the_guard_is_wired_into_the_contracts_layer() -> None:
    """A dropped invocation must be a named failure, not silence."""
    assert "check_mcp_manifest_reconcile.py --self-test" in SMOKE.read_text(
        encoding="utf-8"
    )


def test_the_wiring_pin_actually_fails_on_an_unwired_layer() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    mutated = smoke.replace(
        '"${PYTHON_BIN}" scripts/check_mcp_manifest_reconcile.py --self-test || rc=$?\n',
        "",
        1,
    )
    assert mutated != smoke
    assert "check_mcp_manifest_reconcile.py" not in mutated


def self_test() -> int:
    checks = [
        test_the_committed_tree_reconciles_all_three_declarations,
        test_a_parameter_the_manifest_never_publishes_is_rejected,
        test_a_published_input_the_server_dropped_is_rejected,
        test_a_tool_that_dropped_the_global_budget_is_rejected,
        test_a_commented_out_guard_does_not_count,
        test_a_second_tool_spending_the_submission_quota_is_rejected,
        test_a_relaxed_global_budget_is_rejected,
        test_a_limiter_that_hardcodes_the_process_local_backend_is_rejected,
        test_a_deployment_that_never_sets_the_redis_url_is_rejected,
        test_a_new_tool_needs_no_allowlist_edit,
        test_the_guard_is_wired_into_the_contracts_layer,
        test_the_wiring_pin_actually_fails_on_an_unwired_layer,
    ]
    failures = 0
    for case in checks:
        try:
            case()
            print(f"PASS self-test: {case.__name__}")
        except AssertionError as exc:
            print(f"FAIL self-test: {case.__name__}: {exc}")
            failures += 1
    print(f"self-test: {len(checks)} cases, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(self_test())

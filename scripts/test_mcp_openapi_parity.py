#!/usr/bin/env python3
"""Reconcile the MCP tool manifest with the published OpenAPI operations.

The MCP server publishes its tool inventory in ``manifest.py``. Each entry
declares the REST operation it calls (``endpoint``), its audience (``type``:
read = public data, write = researcher-grade bearer token), and its inputs /
outputs. ``server.py`` independently hardcodes the same paths in its
``_api_request(...)`` calls, and ``app.main`` publishes the authoritative set
of operations in ``packages/api-client/openapi.json``.

These are three declarations of the same fact, and no gate reconciled them:

* ``check-contract.sh`` re-exports the backend and diffs the *generated*
  client. It never reads ``apps/mcp-server/**``, so renaming or dropping a
  backend path regenerates a self-consistent snapshot/client while the MCP
  manifest still points at the old path -- the tool then 404s at runtime.
* ``apps/mcp-server/tests/test_smoke.py`` checks that the manifest's tool
  *names* are registered by ``mcp``. It needs the MCP package installed and
  asserts nothing about endpoints, methods, or auth.
* The contracts layer is where dependency-free, committed-byte guards live,
  but it had no MCP coverage at all.

This guard reads committed bytes only (``ast`` + ``json`` + stdlib): no MCP
import, no API import, no CPython 3.15, no wheel, no database, no workspace
install. It pins, per tool:

* ``endpoint`` (method + path, path variables normalised) resolves to a
  published OpenAPI operation;
* the corresponding ``@mcp.tool`` function in ``server.py`` calls exactly that
  method/path via ``_api_request`` (so the manifest is not a stale decoration);
* the manifest's ``type`` agrees with the operation's ``security``: the
  manifest docstring defines read as public data and write as bearer-token
  operations, so a write tool must target a protected operation and a read
  tool must not;
* the manifest and the ``@mcp.tool`` registry name the same tool set.

A new tool needs no edit to an allowlist here: it passes as soon as all three
declarations agree (positive control in ``--self-test``). A co-revert that
changes the backend, the snapshot and the generated client together still
cannot hide a stale MCP declaration -- but that same agreement is exactly what
lets a coordinated edit *delete* or *rename* one of the published tools from
all three declarations at once, with zero failures. ``PINNED_MCP_TOOLS`` is a
hand-written, reviewed lower bound on the inventory (name -> endpoint, type),
read from nowhere else: a pinned tool that disappears, moves to another REST
operation, or changes audience is named. It deliberately permits extra tools,
so the "a new consistent tool needs no allowlist edit" property survives.

Run directly (stdlib only) or collect with pytest::

    python3 scripts/test_mcp_openapi_parity.py
    python3 scripts/test_mcp_openapi_parity.py --self-test
    pytest scripts/test_mcp_openapi_parity.py -q
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "apps" / "mcp-server" / "src" / "mcp_server" / "manifest.py"
SERVER = ROOT / "apps" / "mcp-server" / "src" / "mcp_server" / "server.py"
SNAPSHOT = ROOT / "packages" / "api-client" / "openapi.json"
SMOKE = ROOT / "scripts" / "smoke.sh"
SELF = Path(__file__).name

METHODS = {"get", "put", "post", "patch", "delete", "options", "head", "trace"}
_TYPE_SECURITY = {"read": False, "write": True}
_REQUIRED_KEYS = ("name", "type", "endpoint", "auth")

# Reviewed lower bound on the published MCP tool inventory. Hand-written, NOT
# derived from manifest.py / server.py / openapi.json: those three are exactly
# the declarations a coordinated co-revert moves together. Deleting one of the
# eight tools from all three, renaming its endpoint across all three, or
# flipping its audience alongside the operation's `security` used to return
# zero failures (only emptying the WHOLE manifest was caught). This floor is a
# minimum, not an allowlist: a genuinely new consistent tool still passes
# without an edit here (positive control), but a published tool cannot silently
# leave or move. A deliberate retirement/rename is an explicit, reviewable edit
# to this literal in the same commit as the three declarations.
PINNED_MCP_TOOLS: dict[str, tuple[str, str]] = {
    "gene_by_id": ("GET /api/v1/genes/{gene_id}", "read"),
    "variant_by_region": ("GET /api/v1/variants/region", "read"),
    "news_list": ("GET /api/v1/news", "read"),
    "stats_summary": ("GET /api/v1/stats/dashboard", "read"),
    "seqfetch": ("POST /api/v1/tools/seqfetch", "read"),
    "blast_submit": ("POST /api/v1/blast/jobs", "write"),
    "blast_job_status": ("GET /api/v1/blast/jobs/{job_id}", "write"),
    "analyses_query": ("GET /api/v1/analyses/{job_id}", "write"),
}


def norm(path: str) -> str:
    """Collapse concrete path-variable names so declarations can be compared."""
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/") or "/"


def parse_endpoint(endpoint: str) -> tuple[str, str] | None:
    """Split ``"METHOD /path/{id}"`` into a comparable (method, path) pair."""
    parts = endpoint.split(" ", 1)
    if len(parts) != 2:
        return None
    method, path = parts[0].strip().lower(), parts[1].strip()
    if method not in METHODS or not path.startswith("/"):
        return None
    return method.upper(), norm(path)


def parse_manifest(source: str) -> list[dict[str, Any]]:
    """Read the TOOLS literal without importing the MCP package."""
    tree = ast.parse(source, filename="manifest.py")
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "TOOLS":
                return list(ast.literal_eval(node.value))
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TOOLS"
            for target in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise ValueError("manifest.py no longer declares a TOOLS literal")


def _string_arg(node: ast.expr) -> str | None:
    """A plain string literal or an f-string with ``{}`` for each field."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                out.append("{}")
        return "".join(out)
    return None


def parse_server(source: str) -> dict[str, tuple[str, str] | None]:
    """Map each ``@mcp.tool(name=...)`` to the ``_api_request`` call it makes."""
    tree = ast.parse(source, filename="server.py")
    calls: dict[str, tuple[str, str] | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name: str | None = None
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if "mcp.tool" not in ast.unparse(dec.func):
                continue
            for kw in dec.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    name = str(kw.value.value)
        if name is None:
            continue
        found: tuple[str, str] | None = None
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call) or len(sub.args) < 2:
                continue
            func = ast.unparse(sub.func)
            if not func.endswith("_api_request"):
                continue
            method = _string_arg(sub.args[0])
            path = _string_arg(sub.args[1])
            if method and path and method.lower() in METHODS:
                found = (method.upper(), norm(path))
                break
        calls[name] = found
    return calls


def published_operations(document: dict[str, Any]) -> dict[tuple[str, str], bool]:
    """(method, path) -> whether the operation declares a security requirement."""
    out: dict[tuple[str, str], bool] = {}
    for path, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method.lower() not in METHODS or not isinstance(operation, dict):
                continue
            out[(method.upper(), norm(path))] = bool(operation.get("security"))
    return out


def check(
    tools: list[dict[str, Any]],
    server_calls: dict[str, tuple[str, str] | None],
    document: dict[str, Any],
) -> list[str]:
    """Return human-readable failures; empty means the three surfaces agree."""
    found: list[str] = []
    if not tools:
        return ["manifest.py declares no MCP tools"]
    operations = published_operations(document)
    if not operations:
        return ["openapi.json publishes no operations"]

    # An independent fixed point: none of the three declarations may silently
    # shed or move a published tool. Extras are allowed on purpose.
    by_name = {str(tool.get("name")): tool for tool in tools}
    for name, (endpoint, kind) in sorted(PINNED_MCP_TOOLS.items()):
        tool = by_name.get(name)
        if tool is None:
            found.append(
                f"reviewed MCP tool inventory is missing {name!r}: a coordinated "
                "edit dropped it from the manifest, server and snapshot together"
            )
            continue
        if str(tool.get("endpoint")) != endpoint:
            found.append(
                f"{name}: endpoint moved to {tool.get('endpoint')!r}, reviewed "
                f"floor pins {endpoint!r}"
            )
        if str(tool.get("type")) != kind:
            found.append(
                f"{name}: audience changed to {tool.get('type')!r}, reviewed "
                f"floor pins {kind!r}"
            )

    manifest_names: set[str] = set()
    for tool in tools:
        label = str(tool.get("name", "<unnamed tool>"))
        for key in _REQUIRED_KEYS:
            if key not in tool:
                found.append(f"{label}: manifest entry is missing {key!r}")
        if any(key not in tool for key in _REQUIRED_KEYS):
            continue
        if label in manifest_names:
            found.append(f"duplicate manifest tool {label!r}")
        manifest_names.add(label)

        endpoint = str(tool["endpoint"])
        parsed = parse_endpoint(endpoint)
        if parsed is None:
            found.append(f"{label}: endpoint {endpoint!r} is not 'METHOD /path'")
            continue
        method, path = parsed
        if parsed not in operations:
            found.append(
                f"{label}: endpoint {endpoint!r} is not a published OpenAPI operation"
            )
        else:
            kind = str(tool["type"])
            if kind not in _TYPE_SECURITY:
                found.append(f"{label}: type {kind!r} is neither 'read' nor 'write'")
            elif operations[parsed] != _TYPE_SECURITY[kind]:
                want = "a protected" if _TYPE_SECURITY[kind] else "a public"
                got = "protected" if operations[parsed] else "public"
                found.append(
                    f"{label}: manifest declares type={kind!r} but "
                    f"{method} {path} is {got}, expected {want} operation"
                )

        if label not in server_calls:
            found.append(f"{label}: manifest declares a tool server.py does not register")
        elif server_calls[label] is None:
            found.append(f"{label}: server.py registers no _api_request call for this tool")
        elif server_calls[label] != parsed:
            call_method, call_path = server_calls[label]  # type: ignore[misc]
            found.append(
                f"{label}: server.py calls {call_method} {call_path} but the "
                f"manifest declares {method} {path}"
            )

    for name in sorted(set(server_calls) - manifest_names):
        found.append(f"server.py registers {name!r} with no manifest entry")

    return found


def check_wiring(smoke: str) -> list[str]:
    """The guard is only as good as the layer that collects it.

    A merge that drops the ``tests[]`` entry leaves the file on disk and
    ``--self-test`` green while the contracts layer stops running it. Pin the
    registration itself so the disappearance is a named failure, not silence.
    """
    if f"scripts/{SELF}" not in smoke:
        return [f"smoke.sh contracts layer no longer collects scripts/{SELF}"]
    return []


def load() -> tuple[list[dict[str, Any]], dict[str, tuple[str, str] | None], dict[str, Any]]:
    return (
        parse_manifest(MANIFEST.read_text(encoding="utf-8")),
        parse_server(SERVER.read_text(encoding="utf-8")),
        json.loads(SNAPSHOT.read_text(encoding="utf-8")),
    )


def _clean() -> tuple[list[dict[str, Any]], dict[str, tuple[str, str] | None], dict[str, Any]]:
    tools, calls, document = load()
    assert check(tools, calls, document) == [], "the committed tree is already out of sync"
    return tools, calls, document


# ---------------------------------------------------------------------------
# pytest-collectible regression cases (the contracts layer collects this file)
# ---------------------------------------------------------------------------


def test_committed_tree_reconciles_manifest_server_and_openapi() -> None:
    assert check(*load()) == []


def test_a_dropped_backend_path_is_rejected() -> None:
    tools, calls, document = _clean()
    del document["paths"]["/api/v1/genes/{gene_id}"]
    assert any("not a published OpenAPI operation" in f for f in check(tools, calls, document))


def test_a_wrong_endpoint_method_is_rejected() -> None:
    tools, calls, document = _clean()
    for tool in tools:
        if tool["name"] == "news_list":
            tool["endpoint"] = "POST /api/v1/news"
    assert any("not a published OpenAPI operation" in f for f in check(tools, calls, document))


def test_a_server_call_that_drifted_from_the_manifest_is_rejected() -> None:
    tools, calls, document = _clean()
    calls["stats_summary"] = ("GET", "/api/v1/stats/summary/impact")
    errors = check(tools, calls, document)
    assert sum("server.py calls" in f for f in errors) == 1, errors


def test_an_unregistered_tool_is_rejected() -> None:
    tools, calls, document = _clean()
    del calls["seqfetch"]
    assert any("does not register" in f for f in check(tools, calls, document))


def test_a_manifest_only_tool_is_rejected() -> None:
    tools, calls, document = _clean()
    calls["ghost_tool"] = ("GET", "/api/v1/news")
    assert any("no manifest entry" in f for f in check(tools, calls, document))


def test_a_write_tool_pointed_at_a_public_operation_is_rejected() -> None:
    tools, calls, document = _clean()
    document["paths"]["/api/v1/blast/jobs"]["post"].pop("security", None)
    assert any("expected a protected operation" in f for f in check(tools, calls, document))


def test_a_read_tool_pointed_at_a_protected_operation_is_rejected() -> None:
    tools, calls, document = _clean()
    document["paths"]["/api/v1/news"]["get"]["security"] = [{"HTTPBearer": []}]
    assert any("expected a public operation" in f for f in check(tools, calls, document))


def test_a_manifest_entry_missing_a_required_key_is_rejected() -> None:
    tools, calls, document = _clean()
    for tool in tools:
        if tool["name"] == "news_list":
            del tool["auth"]
    assert any("missing 'auth'" in f for f in check(tools, calls, document))


def test_dropping_the_smoke_wiring_is_rejected() -> None:
    smoke = SMOKE.read_text(encoding="utf-8")
    assert check_wiring(smoke) == []
    assert check_wiring(smoke.replace(f"scripts/{SELF}", "", 1))


def test_a_dropped_pinned_tool_is_rejected() -> None:
    """Whole-set co-revert: delete one tool from all three declarations."""
    tools, calls, document = _clean()
    victim = "news_list"
    tools = [t for t in tools if t["name"] != victim]
    calls = {k: v for k, v in calls.items() if k != victim}
    document = copy.deepcopy(document)
    document["paths"].pop("/api/v1/news", None)
    assert any("reviewed MCP tool inventory is missing" in f for f in check(tools, calls, document))


def test_a_renamed_pinned_endpoint_is_rejected() -> None:
    """Coordinated rename of one tool's REST operation across all three."""
    tools, calls, document = _clean()
    document = copy.deepcopy(document)
    for tool in tools:
        if tool["name"] == "news_list":
            tool["endpoint"] = "GET /api/v1/news/archive"
    calls = dict(calls)
    calls["news_list"] = ("GET", "/api/v1/news/archive")
    document["paths"]["/api/v1/news/archive"] = document["paths"].pop("/api/v1/news")
    assert any("reviewed floor pins" in f for f in check(tools, calls, document))


def test_a_flipped_pinned_audience_is_rejected() -> None:
    """Coordinated audience flip (manifest type + operation security)."""
    tools, calls, document = _clean()
    document = copy.deepcopy(document)
    for tool in tools:
        if tool["name"] == "news_list":
            tool["type"] = "write"
    document["paths"]["/api/v1/news"]["get"]["security"] = [{"HTTPBearer": []}]
    assert any("audience changed" in f for f in check(tools, calls, document))


def test_the_floor_is_a_literal_not_an_export() -> None:
    """The floor must be a source literal, not derived from an artifact.

    Parse this file's own AST: the value bound to PINNED_MCP_TOOLS has to be an
    ``ast.Dict`` with constant keys. A ``json.load`` / ``parse_manifest`` /
    ``ast.literal_eval`` of the three declarations would be an ``ast.Call`` and
    fail here, which is the property that keeps the floor independent.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bound = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "PINNED_MCP_TOOLS":
                bound = node.value
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PINNED_MCP_TOOLS" for t in node.targets
        ):
            bound = node.value
    assert isinstance(bound, ast.Dict), "PINNED_MCP_TOOLS is not a literal dict"
    assert bound.keys and all(isinstance(k, ast.Constant) for k in bound.keys)


def test_a_new_consistent_tool_needs_no_allowlist_edit() -> None:
    """Positive control: agreement of the three declarations is sufficient."""
    tools, calls, document = _clean()
    tools.append(
        {
            "name": "news_list_again",
            "type": "read",
            "endpoint": "GET /api/v1/news",
            "auth": "public (API bearer forwarded when configured)",
        }
    )
    calls["news_list_again"] = ("GET", "/api/v1/news")
    assert check(tools, calls, document) == []


# ---------------------------------------------------------------------------
# Direct stdlib runner (also used by --self-test)
# ---------------------------------------------------------------------------


def self_test() -> int:
    # Each pytest case above is also a mutation check; run them directly so the
    # guard is executable without pytest (the contracts layer has both paths).
    checks = [
        test_committed_tree_reconciles_manifest_server_and_openapi,
        test_a_dropped_backend_path_is_rejected,
        test_a_wrong_endpoint_method_is_rejected,
        test_a_server_call_that_drifted_from_the_manifest_is_rejected,
        test_an_unregistered_tool_is_rejected,
        test_a_manifest_only_tool_is_rejected,
        test_a_write_tool_pointed_at_a_public_operation_is_rejected,
        test_a_read_tool_pointed_at_a_protected_operation_is_rejected,
        test_a_manifest_entry_missing_a_required_key_is_rejected,
        test_dropping_the_smoke_wiring_is_rejected,
        test_a_dropped_pinned_tool_is_rejected,
        test_a_renamed_pinned_endpoint_is_rejected,
        test_a_flipped_pinned_audience_is_rejected,
        test_the_floor_is_a_literal_not_an_export,
        test_a_new_consistent_tool_needs_no_allowlist_edit,
    ]
    failures = 0
    for fn in checks:
        try:
            fn()
            print(f"PASS self-test: {fn.__name__}")
        except AssertionError as exc:
            print(f"FAIL self-test: {fn.__name__}: {exc}")
            failures += 1
    print(f"self-test: {len(checks)} cases, {failures} failure(s)")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    tools, calls, document = load()
    errors = check(tools, calls, document) + check_wiring(SMOKE.read_text(encoding="utf-8"))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"MCP/OpenAPI parity: {len(errors)} failure(s)")
        return 1
    print(
        f"MCP/OpenAPI parity: OK "
        f"({len(tools)} tools, {len(published_operations(document))} published operations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

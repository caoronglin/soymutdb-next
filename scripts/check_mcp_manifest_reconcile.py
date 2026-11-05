#!/usr/bin/env python3
"""Reconcile the MCP tool manifest with the server and the rate limiters.

The SoyMutDB MCP server declares the same eight tools three times:

* ``manifest.py`` -- ``TOOLS``: the published inventory (``endpoint``,
  ``type``, ``inputs``, ``auth``, ``rate_limit``);
* ``server.py`` -- the ``@mcp.tool(name=...)`` function bodies: the keyword
  arguments a client may pass, and the guards each tool runs before the
  upstream call;
* ``ratelimit.py`` -- the module-level limiters (``GLOBAL_LIMITER`` 60/min,
  ``SUBMIT_LIMITER`` 10/hour) and their backing store.

``check_mcp_openapi_endpoints.py`` reconciles only the *routes* of that
inventory against ``openapi.json``. Nothing read the rest, so three classes of
drift were invisible:

1. **A parameter the server accepts that the manifest never publishes.**
   MCP clients build their tool schema from ``manifest.py``; a keyword added to
   ``server.py`` alone is callable but undiscoverable, and one removed from
   ``server.py`` while the manifest still lists it is a hard error at call time.
2. **A tool that drops a guard.** Every tool must enforce the global budget,
   and ``blast_submit`` additionally draws from the submission quota. Deleting
   ``_rate_limit_error(...)`` from one tool body leaves every existing test
   green (they exercise the limiter, not each tool's use of it).
3. **A limiter swapped for a per-process one.** ``ratelimit.py`` fails over
   from Redis to an in-memory counter when Redis is unreachable. With several
   MCP replicas behind nginx that fallback multiplies the budget by the replica
   count, so it must be a logged, reported condition -- not the default the
   deployment silently lands on.

This guard reads committed bytes with ``ast`` only: no MCP import, no
``redis``, no API, no CPython 3.15, no wheel, no database, no workspace
install. It cannot be silenced by editing the documents it compares, and a new
tool needs no allowlist edit -- it passes as soon as the three declarations
agree.

Run directly (stdlib only) or collect with pytest::

    python3 scripts/check_mcp_manifest_reconcile.py
    python3 scripts/check_mcp_manifest_reconcile.py --self-test
    pytest scripts/test_mcp_manifest_reconcile.py -q
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "apps" / "mcp-server" / "src" / "mcp_server"
MANIFEST = PACKAGE / "manifest.py"
SERVER = PACKAGE / "server.py"
RATELIMIT = PACKAGE / "ratelimit.py"
DEPLOY = ROOT / "docker-compose.yml"

#: The limiter that guards every tool, and the one that only ``blast_submit``
#: draws from. Pinned by name because ``server.py`` imports them directly.
GLOBAL_LIMITER = "GLOBAL_LIMITER"
SUBMIT_LIMITER = "SUBMIT_LIMITER"
#: The single tool allowed to spend the submission quota. Pinned because the
#: quota exists to bound worker-spawning calls; a second entry here is a design
#: decision, not a refactor.
SUBMIT_TOOL = "blast_submit"

#: ``ctx`` is the FastMCP injection slot, never a client-supplied keyword.
_NOT_A_PARAMETER = {"ctx", "self"}


def _strip_comments(source: str) -> str:
    """Drop full-line comments so a commented-out call is not read as present."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def parse_manifest(source: str) -> list[dict[str, Any]]:
    """Read the ``TOOLS`` literal without importing the package."""
    tree = ast.parse(source, filename="manifest.py")
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        elif isinstance(node, ast.Assign):
            target = node.targets[0]
            value = node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "TOOLS" and value is not None:
            return list(ast.literal_eval(value))
    raise ValueError("manifest.py no longer declares a TOOLS literal")


def parse_tools(source: str) -> dict[str, dict[str, Any]]:
    """Per ``@mcp.tool(name=...)``: keyword params and the guards in its body."""
    tree = ast.parse(source, filename="server.py")
    tools: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name: str | None = None
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if "mcp.tool" not in ast.unparse(decorator.func):
                continue
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    name = str(keyword.value.value)
        if name is None:
            continue
        positional = [arg.arg for arg in node.args.args]
        keywords = [arg.arg for arg in node.args.kwonlyargs]
        body = ast.get_source_segment(source, node) or ""
        calls = sorted(
            {
                ast.unparse(call.func)
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }
        )
        tools[name] = {
            "params": {p for p in (*positional, *keywords) if p not in _NOT_A_PARAMETER},
            "guards": [call for call in calls if call.endswith("_rate_limit_error")],
            "submit_quota": "submit_quota=True" in _strip_comments(body),
        }
    return tools


def parse_limiters(source: str) -> dict[str, dict[str, Any]]:
    """``GLOBAL_LIMITER``/``SUBMIT_LIMITER`` construction arguments."""
    tree = ast.parse(source, filename="ratelimit.py")
    found: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id not in {GLOBAL_LIMITER, SUBMIT_LIMITER}:
                continue
            args = [ast.literal_eval(arg) for arg in value.args if isinstance(arg, ast.Constant)]
            named = {
                kw.arg: ast.literal_eval(kw.value)
                for kw in value.keywords
                if kw.arg and isinstance(kw.value, ast.Constant)
            }
            found[target.id] = {
                "limit": args[0] if args else named.get("limit"),
                "window": args[1] if len(args) > 1 else named.get("window_seconds"),
                "name": named.get("name"),
                "factory": ast.unparse(value.func),
            }
    return found


def check(
    manifest_source: str,
    server_source: str,
    ratelimit_source: str,
    deploy_source: str | None = None,
) -> list[str]:
    """Return named failures; empty means the declarations agree."""
    failures: list[str] = []

    try:
        tools = parse_manifest(manifest_source)
    except (ValueError, SyntaxError) as exc:
        return [f"manifest.py is unreadable: {exc}"]
    if not tools:
        return ["manifest.py declares no MCP tools"]
    implementations = parse_tools(server_source)
    limiters = parse_limiters(ratelimit_source)

    if GLOBAL_LIMITER not in limiters:
        failures.append(f"ratelimit.py no longer builds {GLOBAL_LIMITER}")
    if SUBMIT_LIMITER not in limiters:
        failures.append(f"ratelimit.py no longer builds {SUBMIT_LIMITER}")

    for tool in tools:
        label = str(tool.get("name", "<unnamed tool>"))
        implementation = implementations.get(label)
        if implementation is None:
            failures.append(f"{label}: manifest declares a tool server.py does not register")
            continue

        # 1. published inputs vs callable keyword parameters
        published = set(tool.get("inputs", {}))
        callable_params = implementation["params"]
        for missing in sorted(callable_params - published):
            failures.append(
                f"{label}: server.py accepts {missing!r} but the manifest never "
                "publishes it, so no MCP client can supply it"
            )
        for stale in sorted(published - callable_params):
            failures.append(
                f"{label}: manifest publishes input {stale!r} but server.py has "
                "no such parameter"
            )

        # 2. every tool enforces the global budget; only the submitter may
        #    spend the submission quota.
        if not implementation["guards"]:
            failures.append(
                f"{label}: server.py body never calls *_rate_limit_error, so this "
                "tool bypasses the global 60/min budget"
            )
        elif len(implementation["guards"]) > 1:
            failures.append(
                f"{label}: server.py calls {implementation['guards']}; one guard per "
                "tool, or the budgets are drawn twice per request"
            )
        if implementation["submit_quota"] and label != SUBMIT_TOOL:
            failures.append(
                f"{label}: draws the submission quota, but only {SUBMIT_TOOL} may "
                "spawn worker-bound jobs"
            )
        if label == SUBMIT_TOOL and not implementation["submit_quota"]:
            failures.append(
                f"{label}: no longer draws the submission quota "
                f"({SUBMIT_LIMITER}); BLAST submissions would be bounded only by "
                "the global budget"
            )

    for extra in sorted(set(implementations) - {str(t.get("name")) for t in tools}):
        failures.append(f"server.py registers {extra!r} with no manifest entry")

    # 3. the budgets the manifest advertises are the ones ratelimit.py builds.
    global_limiter = limiters.get(GLOBAL_LIMITER, {})
    global_pair = (global_limiter.get("limit"), global_limiter.get("window"))
    if global_limiter and global_pair != (60, 60.0):
        failures.append(
            f"{GLOBAL_LIMITER} is {global_limiter.get('limit')} requests per "
            f"{global_limiter.get('window')}s; every tool's manifest entry "
            "advertises 60/min"
        )
    submit_limiter = limiters.get(SUBMIT_LIMITER, {})
    submit_pair = (submit_limiter.get("limit"), submit_limiter.get("window"))
    if submit_limiter and submit_pair != (10, 3600.0):
        failures.append(
            f"{SUBMIT_LIMITER} is {submit_limiter.get('limit')} requests per "
            f"{submit_limiter.get('window')}s; the manifest advertises 10/hour"
        )
    for name in (GLOBAL_LIMITER, SUBMIT_LIMITER):
        factory = limiters.get(name, {}).get("factory", "")
        if factory and "get_limiter" not in factory:
            failures.append(
                f"{name} is built by {factory}(...), which hardcodes the in-memory "
                "backend; with several MCP replicas the budget multiplies by the "
                "replica count (get_limiter is the Redis-backed path)"
            )

    # 4. a Redis URL that the deployment never sets silently lands on the
    #    per-process fallback described above.
    if deploy_source is not None and "SOYMUTDB_MCP_REDIS_URL" in ratelimit_source:
        if "SOYMUTDB_MCP_REDIS_URL" not in deploy_source:
            failures.append(
                "docker-compose.yml never sets SOYMUTDB_MCP_REDIS_URL, so every MCP "
                "replica uses the per-process limiter and the advertised 60/min "
                "becomes 60/min per replica"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        sys.path.insert(0, str(ROOT))
        from scripts.test_mcp_manifest_reconcile import self_test  # noqa: PLC0415

        return self_test()
    deploy = DEPLOY.read_text(encoding="utf-8") if DEPLOY.is_file() else None
    failures = check(
        MANIFEST.read_text(encoding="utf-8"),
        SERVER.read_text(encoding="utf-8"),
        RATELIMIT.read_text(encoding="utf-8"),
        deploy,
    )
    if failures:
        print("MCP manifest reconciliation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "  the manifest, server.py and ratelimit.py declare the same tools; "
            "change them together (docs/dev/mcp-manifest-reconcile.md)",
            file=sys.stderr,
        )
        return 1
    tools = parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    print(f"MCP manifest reconciliation: OK ({len(tools)} tools, 3 declarations agree)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

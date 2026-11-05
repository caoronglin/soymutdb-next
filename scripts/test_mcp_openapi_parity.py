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
# Fields a tool documents in the manifest but deliberately does not put in the
# JSON body: they travel as a query parameter, as the release header, or are
# tool-local (ownership proofs the MCP server enforces itself). This is a
# reviewed allowlist, not a default: a new REST input that silently misses the
# payload must be an explicit edit here in the same commit.
_NOT_IN_BODY: frozenset[str] = frozenset({"release_id", "submitter_token", "ctx"})

# Manifest input names that are accepted under a different payload key. The
# manifest is the specification an MCP client reads, so the name it documents
# has to be the name the REST operation accepts -- an alias here is a real
# defect and must be fixed at the source, not excused. Kept empty on purpose:
# the check reports the ``params`` / ``parameters`` split rather than hiding it.
_OPTIONAL_PARAMETER_INPUTS: frozenset[str] = frozenset()

# Payload keys carried as a query parameter rather than the JSON body (the
# OpenAPI operation publishes them under ``parameters``, not ``properties``).
_REQUIRED_PARAMETER_NOT_IN_BODY: frozenset[str] = frozenset({"release_id"})

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


def parse_server_calls(source: str) -> dict[str, tuple[tuple[str, str] | None, ast.Call]]:
    """``parse_server`` plus the ``_api_request`` call node for each tool.

    The endpoint pair drives the pre-existing checks; the node additionally
    lets :func:`check_request_bodies` read *how* the payload is assembled
    without executing ``server.py`` (which imports FastMCP, the manifest and an
    HTTP client -- none of which exist in a dependency-free contracts layer).
    """
    tree = ast.parse(source, filename="server.py")
    calls: dict[str, tuple[tuple[str, str] | None, ast.Call]] = {}
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
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call) or len(sub.args) < 2:
                continue
            if not ast.unparse(sub.func).endswith("_api_request"):
                continue
            method = _string_arg(sub.args[0])
            path = _string_arg(sub.args[1])
            if method and path and method.lower() in METHODS:
                # ast nodes have no parent pointers; stash the tool function on
                # the call so payload-shape helpers can resolve name bindings.
                sub._soymutdb_scope = node  # type: ignore[attr-defined]
                calls[name] = ((method.upper(), norm(path)), sub)
                break
        else:
            calls[name] = (None, ast.Call())
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


def resolve_schema(
    schema: dict[str, Any], document: dict[str, Any], depth: int = 0
) -> dict[str, Any]:
    """Dereference a local ``$ref`` so a body's properties become comparable."""
    if not isinstance(schema, dict) or depth > 8:
        return {}
    ref = schema.get("$ref")
    if not (isinstance(ref, str) and ref.startswith("#/")):
        return schema
    target: Any = document
    for part in ref[2:].split("/"):
        target = target.get(part) if isinstance(target, dict) else None
    return resolve_schema(target, document, depth + 1) if isinstance(target, dict) else {}


def published_body_schema(
    method: str, path: str, document: dict[str, Any]
) -> dict[str, Any] | None:
    """The JSON request-body schema published for ``METHOD /path``, or None."""
    for candidate, item in document.get("paths", {}).items():
        if norm(candidate) != path or not isinstance(item, dict):
            continue
        operation = item.get(method.lower())
        if not isinstance(operation, dict):
            return None
        body = operation.get("requestBody")
        if not isinstance(body, dict):
            return None
        content = body.get("content") or {}
        schema = (content.get("application/json") or {}).get("schema")
        return resolve_schema(schema, document) if isinstance(schema, dict) else None
    return None


def tool_parameters(call: ast.Call) -> list[str]:
    """Names of the tool function's own MCP arguments, ``ctx`` excluded.

    These are the values a caller can actually supply. A documented input that
    is neither a tool parameter nor reachable another way (a query parameter,
    the release header) cannot be caller-supplied at all, and the assignment of
    it into the payload would name an undefined variable.
    """
    scope = getattr(call, "_soymutdb_scope", None)
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    args = scope.args
    names = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    names += [a.arg for a in args.kwonlyargs]
    return [name for name in names if name not in _NOT_IN_BODY]


def payload_shape(call: ast.Call) -> tuple[dict[str, ast.If | None] | None, bool]:
    """The payload the tool sends: ``(key -> guarding if, is_literal)``.

    ``payload=`` is a dict literal or a name bound once in the tool function
    (``payload: dict[str, Any] = {...}``). Each key is paired with the
    enclosing ``if`` whose *body* assigned it, so a documented optional field
    (``if assembly: payload["assembly"] = assembly``) can be told apart from a
    field that never leaves the process. A payload that is not statically
    enumerable returns ``(None, False)``; the caller reports that instead of
    assuming the body is complete.
    """
    node: ast.expr | None = None
    for keyword in call.keywords:
        if keyword.arg == "payload":
            node = keyword.value
    if node is None:
        return {}, True
    if isinstance(node, ast.Name):
        # A name bound exactly once is a pre-built literal; a name re-bound
        # conditionally (`payload = {**payload, ...}`) is reassigned twice and
        # comes back as None, which the caller reports as unprovable.
        node = _unique_binding(call, node.id)
    if not isinstance(node, ast.Dict):
        return None, False
    guards: dict[str, ast.If | None] = {}
    for key in node.keys:
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            return None, False
        guards[str(key.value)] = None
    # A conditional field is assigned into the dict after it is built
    # (`if assembly: payload["assembly"] = assembly`), so those keys exist only
    # in the surrounding `if` bodies and not in the literal itself. Collect
    # them here; a key assigned only on an `else` branch is left out and the
    # caller reports it as a body that never carries the documented input.
    for if_node in _conditional_assignments(call, node):
        guards.setdefault(if_node, _guarding_if(call, if_node))
    return guards, True


def _conditional_assignments(call: ast.Call, payload: ast.Dict) -> list[str]:
    """Keys assigned into ``payload`` inside some ``if`` body in the function."""
    names = {
        keyword.value.id
        for keyword in call.keywords
        if keyword.arg == "payload" and isinstance(keyword.value, ast.Name)
    }
    keys: list[str] = []
    for node in _scope_nodes(call):
        if not isinstance(node, ast.If):
            continue
        for body in node.body:
            if not isinstance(body, ast.Assign):
                continue
            for target in body.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if not (isinstance(target.value, ast.Name) and target.value.id in names):
                    continue
                index = target.slice
                if isinstance(index, ast.Constant) and isinstance(index.value, str):
                    if index.value not in keys:
                        keys.append(index.value)
    return keys


def _scope_nodes(call: ast.Call) -> list[ast.AST]:
    """The tool function's statements, recovered from the call node itself.

    ``ast`` nodes carry no parent pointers, so :func:`parse_server_calls`
    attaches the enclosing function to the call it finds. Reading the scope
    from the call keeps this helper pure and testable.
    """
    scope = getattr(call, "_soymutdb_scope", None)
    return list(ast.walk(scope)) if scope is not None else []


def _unique_binding(call: ast.Call, name: str) -> ast.expr | None:
    """The single value bound to ``name`` inside the tool function."""
    values: list[ast.expr] = []
    for node in _scope_nodes(call):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name) and node.target.id == name:
                values.append(node.value)
    return values[0] if len(values) == 1 else None


def _guarding_if(call: ast.Call, key: str) -> ast.If | None:
    """The ``if`` whose body assigns ``payload[key]``, or ``None``.

    A documented optional field is written conditionally
    (``if assembly: payload["assembly"] = assembly``); the assignment sits in
    that ``if``'s body, so the key is sent only when the argument is present.
    A key assigned on the *false* branch, or outside every ``if`` in a dict
    literal, is not conditional and must be carried unconditionally.
    """
    for node in _scope_nodes(call):
        if not isinstance(node, ast.If):
            continue
        for body in node.body:
            if not isinstance(body, ast.Assign):
                continue
            for target in body.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                index = target.slice
                if isinstance(index, ast.Constant) and index.value == key:
                    return node
    return None


def _declared_conditions(call: ast.Call, key: str, payload: ast.Dict) -> bool:
    """Whether ``payload`` already carries ``key`` in its literal form."""
    return any(
        isinstance(k, ast.Constant) and k.value == key for k in payload.keys
    )


def check_request_bodies(
    tools: list[dict[str, Any]],
    server_calls: dict[str, tuple[tuple[str, str] | None, ast.Call]],
    document: dict[str, Any],
) -> list[str]:
    """A documented input that the tool never sends is a spec it cannot honour.

    The endpoint/audience checks prove the tool calls the right ``(method,
    path)``. They say nothing about the *body* that request carries: a tool can
    advertise a documented input and never place it in the payload, and every
    surface stays in agreement (the manifest is a declaration, ``server.py`` is
    another, and the operation's schema is a third -- the first two are never
    compared field by field). This check closes that hole for the operations
    that publish a JSON request body:

    * an input the manifest documents must appear in the payload the tool
      sends, unless it is carried another way (a query parameter, the
      ``X-SoyMutDB-Release`` header, or a tool-local argument the REST call does
      not take). A manifest that says ``params`` while the payload says
      ``parameters`` is reported, because the documented name is not the one
      the API accepts.
    * a payload key the request schema does not publish is accepted by nobody:
      the API's models forbid unknown fields, so the value is dropped and the
      documented behaviour silently never happens.

    A payload that is not statically enumerable is reported, never assumed
    correct.
    """
    found: list[str] = []
    for tool in tools:
        label = str(tool.get("name"))
        entry = server_calls.get(label)
        if entry is None or entry[0] is None:
            continue  # reported by check()
        (method, path), call = entry
        schema = published_body_schema(method, path, document)
        if schema is None:
            continue
        properties = {str(name) for name in (schema.get("properties") or {})}
        declared = {str(name) for name in (tool.get("inputs") or {})}
        shape, literal = payload_shape(call)
        if not literal or shape is None:
            found.append(
                f"{label}: payload for {method} {path} is not a static dict "
                "literal, so its body cannot be reconciled with the operation"
            )
            continue
        sent = set(shape)
        parameters = tool_parameters(call)
        for key in sorted(declared - set(parameters) - properties - _NOT_IN_BODY):
            found.append(
                f"{label}: manifest documents input {key!r} but the tool takes no "
                f"argument of that name and {method} {path} publishes no such "
                "request property, so no caller can ever supply it"
            )
        for key in sorted(set(tool.get("inputs") or {}) - sent):
            if key in _NOT_IN_BODY or key in _OPTIONAL_PARAMETER_INPUTS:
                continue
            if shape.get(key) is not None:
                continue  # assembled inside an `if`, i.e. an optional field
            found.append(
                f"{label}: manifest documents input {key!r} but the payload sent "
                f"to {method} {path} never carries it"
            )
        for key in sorted(sent - properties):
            if key in _REQUIRED_PARAMETER_NOT_IN_BODY:
                continue
            found.append(
                f"{label}: payload sends {key!r} but {method} {path} publishes no "
                "such request property (the API rejects or drops unknown fields)"
            )
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


def load_all(
    tools_source: str | None = None,
    server_source: str | None = None,
    document: dict[str, Any] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, tuple[tuple[str, str] | None, ast.Call]],
    dict[str, Any],
]:
    """Read all three declarations, optionally overriding any of them.

    The overrides let the body checks run against an edited copy built from
    committed bytes -- the alternative (round-tripping ``server.py`` through
    ``ast.unparse``) would test the synthesised file, not the shipped one.
    """
    return (
        parse_manifest(
            tools_source if tools_source is not None else MANIFEST.read_text(encoding="utf-8")
        ),
        parse_server_calls(
            server_source if server_source is not None else SERVER.read_text(encoding="utf-8")
        ),
        document
        if document is not None
        else json.loads(SNAPSHOT.read_text(encoding="utf-8")),
    )


def load() -> tuple[list[dict[str, Any]], dict[str, tuple[str, str] | None], dict[str, Any]]:
    tools, calls, document = load_all()
    return tools, {name: pair[0] for name, pair in calls.items()}, document


def check_bodies(
    tools_source: str | None = None,
    server_source: str | None = None,
    document: dict[str, Any] | None = None,
) -> list[str]:
    """``check_request_bodies`` over committed (or supplied) declarations."""
    return check_request_bodies(*load_all(tools_source, server_source, document))


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


def test_a_documented_input_missing_from_the_payload_is_rejected() -> None:
    """The manifest names an input the tool never sends: a spec it cannot honour."""
    tools_source = MANIFEST.read_text(encoding="utf-8")
    drifted = tools_source.replace(
        '"database_id": "int, optional — numeric database id",',
        '"database_id": "int, optional — numeric database id",\n'
        '            "database_version": "str, optional — pinned database build",',
        1,
    )
    assert drifted != tools_source
    failures = check_bodies(tools_source=drifted)
    assert any(
        "blast_submit" in f and "database_version" in f and "never carries it" in f
        for f in failures
    ), failures


def test_an_input_documented_under_a_name_the_api_does_not_accept_is_rejected() -> None:
    """The blast_submit defect: manifest said ``params``, the body sends ``parameters``.

    Committed bytes put the real (drifted) shape back, so this case fails if the
    check ever goes back to comparing endpoints only.
    """
    tools_source = MANIFEST.read_text(encoding="utf-8").replace(
        '"parameters": "dict, optional — search parameters (evalue, "',
        '"params": "dict, optional — search parameters (evalue, "',
        1,
    )
    failures = check_bodies(tools_source=tools_source)
    assert any("blast_submit" in f and "'params'" in f for f in failures), failures


def test_an_input_sent_only_on_the_else_branch_is_rejected() -> None:
    server_source = SERVER.read_text(encoding="utf-8")
    drifted = server_source.replace(
        """    if database:
        payload["database"] = database""",
        """    if database:
        pass
    else:
        payload["database"] = database""",
        1,
    )
    assert drifted != server_source
    failures = check_bodies(server_source=drifted)
    assert any("blast_submit" in f and "'database'" in f for f in failures), failures


def test_an_unguarded_optional_field_stays_accepted() -> None:
    """Positive control: ``if database: payload[...]`` is a sendable optional input."""
    assert check_bodies() == []


def test_an_opaque_payload_is_reported_not_assumed() -> None:
    server_source = SERVER.read_text(encoding="utf-8").replace(
        """    payload: dict[str, Any] = {
        "engine": engine,""",
        """    payload: dict[str, Any] = {
        **(extra or {}),
        "engine": engine,""",
        1,
    )
    failures = check_bodies(server_source=server_source)
    assert any("blast_submit" in f and "not a static dict literal" in f for f in failures), failures


def test_a_payload_property_the_operation_does_not_publish_is_rejected() -> None:
    server_source = SERVER.read_text(encoding="utf-8").replace(
        '        "query_sequence": query_sequence,',
        '        "query_sequence": query_sequence,\n        "query_type": "protein",',
        1,
    )
    failures = check_bodies(server_source=server_source)
    assert any("blast_submit" in f and "query_type" in f for f in failures), failures


def test_request_body_agreement_covers_every_tool_with_a_body() -> None:
    """No tool may quietly opt out of the body checks."""
    tools, calls, document = load_all()
    covered = {
        str(tool["name"])
        for tool in tools
        if published_body_schema(*calls[str(tool["name"])][0], document) is not None
    }
    assert covered == {"seqfetch", "blast_submit"}, covered


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
        test_a_documented_input_missing_from_the_payload_is_rejected,
        test_an_input_documented_under_a_name_the_api_does_not_accept_is_rejected,
        test_an_input_sent_only_on_the_else_branch_is_rejected,
        test_an_unguarded_optional_field_stays_accepted,
        test_an_opaque_payload_is_reported_not_assumed,
        test_a_payload_property_the_operation_does_not_publish_is_rejected,
        test_request_body_agreement_covers_every_tool_with_a_body,
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
    errors = (
        check(tools, calls, document)
        + check_bodies()
        + check_wiring(SMOKE.read_text(encoding="utf-8"))
    )
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

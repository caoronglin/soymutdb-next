#!/usr/bin/env python3
"""Pin every MCP tool's header set to the publication scope of its operation.

The MCP server is a third declaration of the REST surface: ``manifest.py``
names the endpoint, ``server.py`` calls it through ``_api_request``, and
``openapi.json`` describes what the API actually publishes. ``_api_request``
sends a fixed header dictionary (``Accept`` + bearer). Any release pin the
operation accepts via ``X-SoyMutDB-Release`` is therefore *not* sent, and the
API falls back to whatever release happens to be active when the call is
served.

For ``gene_by_id``, ``variant_by_region`` and ``stats_summary`` that fallback
is the whole read path: all three publish ``X-SoyMutDB-Release`` as an optional
header and resolve it through ``get_release_context``. During an internal
preview the MCP answer is then computed against the draft release while the web
portal is pinned to the published one -- two clients, one tool name, different
biology, and nothing in any artifact says which release the answer came from.

This guard reads committed bytes (no MCP package, no FastAPI, no network) and
holds two things:

1. **Scope** -- a tool whose operation publishes ``X-SoyMutDB-Release`` must
   forward a release pin, and a tool whose operation does not publish it must
   not forward one. The second half matters as much as the first: a tool that
   invents a parameter the API does not accept turns a caller's release choice
   into a silent no-op.
2. **Single layer** -- the pin must be added in ``_api_request`` (resolve once,
   one transport), not sprinkled into ``_headers()`` or per-tool call sites.
   The local wiring tests only assert the request the tools make, so a
   per-tool scatter that happens to pass would not be caught anywhere.

Signature pinning is deliberately absent: ``seqfetch`` takes no release pin and
is already scoped by an explicit ``assembly``, so requiring a pin there would be
a wrong constraint rather than a missing one.

Usage:
    python3 scripts/check_mcp_release_binding.py --self-test
    python3 scripts/check_mcp_release_binding.py
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PY = ROOT / "apps/mcp-server/src/mcp_server/manifest.py"
SERVER_PY = ROOT / "apps/mcp-server/src/mcp_server/server.py"
OPENAPI_JSON = ROOT / "packages/api-client/openapi.json"

RELEASE_HEADER = "X-SoyMutDB-Release"
PIN_PARAM = "release_id"

#: Regex anchor for the transport that every tool funnels through.
API_REQUEST_DEF = "async def _api_request("
HEADERS_DEF = "def _headers("


#: Endpoints scoped by an explicit assembly / parameter instead of a release
#: pin. Each entry is a decision, not a hole: ``seqfetch`` takes
#: ``{assembly, genes|region}`` and its response echoes that assembly, so a
#: release header would put two scopes on one request without telling them
#: apart. ``blast_submit`` creates a job whose release is resolved server-side
#: when the worker runs; a client-chosen release there would let a submission
#: outlive the release it was pinned to.
ASSEMBLY_SCOPED = frozenset({"seqfetch"})
JOB_CREATED = frozenset({"blast_submit"})
EXEMPT = ASSEMBLY_SCOPED | JOB_CREATED


class GuardError(Exception):
    """A contract violation, reported verbatim and counted as a failure."""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - checkout invariant
        raise GuardError(f"missing source file: {path}") from exc


def strip_python_line_comments(source: str, *, keep_comments: bool = False) -> str:
    """Drop docstrings (and, unless asked, ``#`` comments) so prose never counts.

    A release pin spelled inside a comment or a docstring is not wiring. Both
    the scope check and its negative control must read code, not prose, or the
    guard can be satisfied by a sentence.
    """
    without_strings = re.sub(r'"""(?:.|\n)*?"""', '""', source)
    without_strings = re.sub(r"'''(?:.|\n)*?'''", "''", without_strings)
    if keep_comments:
        return without_strings
    return "\n".join(line.split("#", 1)[0] for line in without_strings.splitlines())


def manifest_tools(source: str) -> dict[str, str]:
    """Return ``{tool name: endpoint "METHOD /path"}`` from TOOLS."""
    tools: dict[str, str] = {}
    for block in re.split(r"\n    \{\n", source)[1:]:
        name = re.search(r'"name": "([^"]+)"', block)
        endpoint = re.search(r'"endpoint": "([A-Z]+) (\S+)"', block)
        if name and endpoint:
            tools[name.group(1)] = f"{endpoint.group(1)} {endpoint.group(2)}"
    if not tools:
        raise GuardError("no tools parsed from manifest.py TOOLS")
    return tools


def operation_scope(spec: dict, tool: str, endpoint: str) -> bool:
    """True when the published operation accepts a release pin header."""
    try:
        method, path = endpoint.split(" ", 1)
    except ValueError as exc:
        raise GuardError(
            f"{tool}: endpoint is not 'METHOD /path': {endpoint!r}"
        ) from exc
    operations = spec.get("paths", {}).get(path)
    if operations is None:
        raise GuardError(
            f"{tool}: endpoint {path} is not a published operation "
            "(manifest.py and openapi.json disagree)"
        )
    operation = operations.get(method.lower())
    if operation is None:
        raise GuardError(f"{tool}: {endpoint} is not published (no {method} on {path})")
    names = {param.get("name") for param in operation.get("parameters", [])}
    return RELEASE_HEADER in names


def server_scope(variables: list[str]) -> bool:
    """True when the tool function accepts a release_id input."""
    return PIN_PARAM in variables


def parse_tool_functions(source: str) -> dict[str, list[str]]:
    """Map each ``@mcp.tool`` function name to the names it takes."""
    functions: dict[str, list[str]] = {}
    pattern = re.compile(
        r"@mcp\.tool\((?:(?!\)\n).)*?name=\"([a-z_0-9]+)\".*?\)\s*\n"
        r"async def ([a-z_0-9]+)\(\s*(.*?)\n?\) ->",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        declared, func, params = match.groups()
        if declared != func:
            raise GuardError(
                f"@mcp.tool name {declared!r} is registered on function {func!r}; "
                "the manifest key and the callable would drift apart"
            )
        variables = [
            line.strip().split(":", 1)[0].split("=", 1)[0].strip()
            for line in params.splitlines()
            if line.strip()
        ]
        functions[func] = [v for v in variables if v]
    if not functions:
        raise GuardError("no @mcp.tool functions parsed from server.py")
    return functions


def function_body(name: str, source: str) -> str:
    """Return ``def <name>`` up to the next top-level def, docstrings stripped.

    ``_api_request`` and ``_headers`` are both scanned this way so a header
    spelling only in prose is not mistaken for wiring.
    """
    start = source.find(f"def {name}(")
    if start == -1:
        raise GuardError(f"{name} is gone from server.py: the transport moved")
    tail = source[start:]
    end = tail.find("\nasync def ", 1)
    alt = tail.find("\ndef ", 1)
    if alt != -1 and (end == -1 or alt < end):
        end = alt
    end = len(tail) if end == -1 else end
    # Comments stay: ``_headers(release_id)`` merely forwards the pin, so the
    # header name legitimately lives in the ``_headers`` definition. Only
    # docstring mentions are excluded.
    body = strip_python_line_comments(tail[:end], keep_comments=True)
    if name == "_api_request" and "httpx.AsyncClient" not in body:
        raise GuardError("_api_request no longer owns the httpx client")
    return body


def check(spec: dict, manifest_source: str, server_source: str) -> list[str]:
    """Return human-readable failures; empty means the contract holds."""
    failures: list[str] = []
    tools = manifest_tools(manifest_source)
    functions = parse_tool_functions(server_source)
    code = strip_python_line_comments(server_source)

    if set(tools) != set(functions):
        only_manifest = sorted(set(tools) - set(functions))
        only_server = sorted(set(functions) - set(tools))
        failures.append(
            "tool inventory disagrees: manifest-only "
            f"{only_manifest}, server-only {only_server}"
        )

    body = function_body("_api_request", code)
    # The pin may be spelled by name or forwarded through a helper
    # (``_headers(release_id)``); either is wiring, prose in a docstring is not.
    forwards_pin = (
        f"_headers({PIN_PARAM})" in body or f"{PIN_PARAM}={PIN_PARAM}" in body
    )
    if RELEASE_HEADER not in body and not forwards_pin:
        failures.append(
            f"_api_request neither sends {RELEASE_HEADER} nor forwards a "
            f"{PIN_PARAM} to _headers: every release-scoped tool silently "
            "reads whatever release is active"
        )
    signature = re.match(r"def [^(]*\((.*?)\) ->", body, re.DOTALL)
    declares_pin = bool(signature) and re.search(
        rf"\b{PIN_PARAM}\b", signature.group(1)
    )
    if not declares_pin:
        failures.append(
            f"_api_request does not declare a {PIN_PARAM} keyword, so a tool "
            "cannot hold a pin even if it takes one"
        )

    try:
        headers_block = strip_python_line_comments(
            function_body("_headers", code), keep_comments=True
        )
    except GuardError:
        headers_block = ""
    # ``_headers`` is *allowed* to apply the pin -- it is the single place the
    # header dictionary is built. What must not happen is a header with no
    # input behind it, which would pin every tool including the exempt ones.
    # A literal in the dict initializer is that unconditional case: the
    # conditional arm assigns the header from the ``release_id`` argument.
    literal = re.search(rf'headers\s*=\s*\{{[^}}]*"{RELEASE_HEADER}"', headers_block)
    if literal:
        failures.append(
            f"_headers() sends {RELEASE_HEADER} unconditionally: every tool "
            "would be release-pinned when only the scoped half is"
        )

    for tool in sorted(tools):
        endpoint = tools[tool]
        published = operation_scope(spec, tool, endpoint)
        forwarded = server_scope(functions[tool])
        if published and not forwarded and tool in EXEMPT:
            continue
        if published and not forwarded:
            failures.append(
                f"{tool}: {endpoint} publishes {RELEASE_HEADER} but the tool "
                f"takes no {PIN_PARAM} input, so callers cannot pin a release"
            )
        if not published and forwarded:
            failures.append(
                f"{tool}: {endpoint} does not publish {RELEASE_HEADER} but the "
                f"tool takes {PIN_PARAM}; the pin would be a silent no-op"
            )
    return failures


def run_self_test() -> int:
    """Inject one-sided drifts and assert each is caught."""
    spec = json.loads(_read(OPENAPI_JSON))
    manifest_source = _read(MANIFEST_PY)
    server_source = _read(SERVER_PY)

    if check(spec, manifest_source, server_source):
        print(
            "self-test needs a passing baseline; the live tree is already",
            file=sys.stderr,
        )
        print("failing -- fix the tree before trusting the ablations", file=sys.stderr)
        return 1

    scoped_tool = next(
        tool
        for tool, endpoint in manifest_tools(manifest_source).items()
        if operation_scope(spec, tool, endpoint)
    )

    def drop_param(src: str, tool: str) -> str:
        start = re.search(rf"async def {tool}\(", src)
        if start is None:
            return src
        end = src.find(") ->", start.start())
        block = src[start.start() : end]
        return src.replace(
            block, re.sub(r"\n    release_id: int \| None = None,", "", block), 1
        )

    cases: list[tuple[str, dict, str, str]] = []

    def replace_once(src: str, old: str, new: str) -> str:
        if old not in src:
            raise SystemExit(f"self-test drift anchor is stale: {old!r}")
        return src.replace(old, new, 1)

    cases.append(
        (
            "transport stops forwarding the pin",
            spec,
            manifest_source,
            replace_once(
                server_source, "headers=_headers(release_id)", "headers=_headers()"
            ),
        )
    )
    cases.append(
        (
            "_headers() takes over the pin",
            spec,
            manifest_source,
            replace_once(
                server_source,
                'headers = {"Accept": "application/json"}',
                f'headers = {{"Accept": "application/json", "{RELEASE_HEADER}": "1"}}',
            ),
        )
    )
    cases.append(
        (
            f"{scoped_tool} loses its release input",
            spec,
            manifest_source,
            drop_param(server_source, scoped_tool),
        )
    )
    cases.append(
        (
            "an unscoped tool invents a pin",
            spec,
            manifest_source,
            replace_once(
                server_source,
                "    page_size: int = 20,\n    ctx: Context | None = None,",
                f"    page_size: int = 20,\n    {PIN_PARAM}: int | None = None,\n"
                "    ctx: Context | None = None,",
            ),
        )
    )
    unpublished = copy.deepcopy(spec)
    unpublished["paths"]["/api/v1/news"]["get"]["parameters"] = [
        p
        for p in unpublished["paths"]["/api/v1/news"]["get"]["parameters"]
        if p.get("name") != RELEASE_HEADER
    ]
    cases.append(
        (
            "the operation stops publishing the header",
            unpublished,
            manifest_source,
            server_source.replace(
                "    page_size: int = 20,\n    ctx: Context | None = None,",
                f"    page_size: int = 20,\n    {PIN_PARAM}: int | None = None,\n"
                "    ctx: Context | None = None,",
            ),
        )
    )
    cases.append(
        (
            "a commented-out pin does not count",
            spec,
            manifest_source,
            drop_param(server_source, scoped_tool).replace(
                "    ctx: Context | None = None,",
                f"    # {PIN_PARAM}: int | None = None,\n    ctx: Context | None = None,",
                1,
            ),
        )
    )

    failures = 0
    for label, case_spec, case_manifest, case_server in cases:
        try:
            found = check(case_spec, case_manifest, case_server)
        except GuardError as exc:
            found = [str(exc)]
        if found:
            print(f"self-test OK   {label}")
        else:
            print(f"self-test FAIL {label}: ablation stayed green", file=sys.stderr)
            failures += 1
    if failures:
        return 1
    print(f"self-test: {len(cases)} ablations caught, 0 missed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    spec = json.loads(_read(OPENAPI_JSON))
    try:
        failures = check(spec, _read(MANIFEST_PY), _read(SERVER_PY))
    except GuardError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    tools = manifest_tools(_read(MANIFEST_PY))
    functions = parse_tool_functions(_read(SERVER_PY))
    scoped = sorted(
        t
        for t, e in tools.items()
        if operation_scope(spec, t, e) and server_scope(functions[t])
    )
    print(
        f"mcp release binding: OK ({len(tools)} tools, "
        f"{len(scoped)} pinned: {', '.join(scoped)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# MCP manifest ↔ OpenAPI operation parity

## The seam

`SoyMutDB` publishes the same REST endpoint set through three independent
declarations:

| Declaration | File | What it states |
| --- | --- | --- |
| Backend contract | `packages/api-client/openapi.json` (an export of `app.main:app`) | Which `(method, path)` operations exist and whether they require `security` |
| MCP tool inventory | `apps/mcp-server/src/mcp_server/manifest.py` (`TOOLS`) | Each tool's `endpoint`, audience (`type`: `read` / `write`), inputs, outputs, auth |
| MCP call sites | `apps/mcp-server/src/mcp_server/server.py` (`@mcp.tool` + `_api_request`) | The method/path actually requested at runtime |

None of the pre-existing gates reconciled them:

* `packages/api-client/scripts/check-contract.sh` exports the backend, diffs
  the committed snapshot and regenerates `src/generated/openapi.d.ts`. It never
  reads `apps/mcp-server/**`. Renaming a backend path therefore produces a
  fully self-consistent snapshot/client pair while the MCP manifest still
  points at the old path — the tool 404s at runtime with no red gate.
* `apps/mcp-server/tests/test_smoke.py` asserts the manifest's tool *names*
  are registered by `mcp`. It needs the MCP package installed and checks
  neither endpoints nor methods nor auth.
* The dependency-free contracts layer (`scripts/smoke.sh --profile contracts`)
  had no MCP coverage at all.

This is the same genus as the 422-envelope and behavior-contract blind spots:
**equality of generated products is not evidence that a second, hand-written
declaration still points at the truth.**

## The guard

`scripts/test_mcp_openapi_parity.py` is stdlib-only (`ast`, `json`, `re`). It
reads committed bytes, so it needs no MCP import, no API import, no CPython
3.15, no wheel, no database and no `pnpm install`. It runs as a contracts-layer
pytest case and directly (`python3 scripts/test_mcp_openapi_parity.py`).

Per tool it pins:

1. `endpoint` parses as `METHOD /path` and resolves to a published OpenAPI
   operation (path variables normalised to `{}`, so `{gene_id}` and `{id}`
   compare as the same slot);
2. `server.py`'s `@mcp.tool(name=...)` function calls that exact method/path
   via `_api_request` — a plain string literal or an f-string with `{}` for
   interpolated ids;
3. the manifest's `type` agrees with the operation's `security`: the manifest
   defines `read` as public data and `write` as bearer-token operations, so a
   write tool must target a protected operation and a read tool must not;
4. manifest tool names and the `@mcp.tool` registry are the same set (both
   directions), and every entry carries `name` / `type` / `endpoint` / `auth`;
5. its own `tests[]` registration in `scripts/smoke.sh` is still present —
   a dropped wiring line is a named failure, not a silently-green `--self-test`.

There is **no allowlist of tool names or endpoints**. A new tool passes as soon
as all three declarations agree (positive control in `--self-test`); a
co-revert that changes the backend, snapshot and generated client together
cannot hide a stale MCP declaration.

## The body, which agreement does not cover

Endpoint agreement says the tool calls the right `(method, path)`. It says
nothing about the JSON body that request carries, and the body is where a
documented input can quietly stop working: the manifest is what an MCP client
reads (`inputs`), `server.py`'s `payload={...}` is the only place a field can
leave the process, and the operation's request schema is what the API will
accept. Since #212 all three surfaces can agree while the second one drops a
field the first one documents.

Measured on live `main` before this check existed: `blast_submit` documented
its search-parameter dict as `params` and sent `parameters`. The API accepted
the request and applied the parameters, so nothing 404'd, nothing 422'd, and no
gate read either name — but the manifest told every MCP client the wrong
argument name, so a caller passing `params` had it dropped by the tool
signature and never reached the request body at all.

`check_request_bodies()` closes that hole for every tool whose operation
publishes a JSON request body (`seqfetch`, `blast_submit` today; the test
`test_request_body_agreement_covers_every_tool_with_a_body` pins the covered
set so a new body-declaring tool cannot silently opt out). It reads `ast` only:

- **name reachability** — every input the manifest documents must be a tool
  function parameter *or* a published request property, otherwise no caller can
  ever supply it;
- **payload completeness** — every documented input must appear in the payload
  literal, or be assigned inside an `if` *body* (`if database: payload[...]`,
  the shape of an optional field). A key assigned only on the `else` branch is
  not sent, and is reported;
- **payload legality** — a payload key the operation does not publish is named
  (the API's models forbid unknown fields, so it is dropped);
- **unprovable bodies fail closed** — a `**spread`, a computed value or a
  twice-rebound `payload` is reported as unreconcilable rather than assumed
  correct.

The allowlist is `_NOT_IN_BODY` (values that travel as a query parameter, the
release header, or are tool-local ownership proofs). It is reviewed, not
derived: a new REST input that silently misses the payload must be an explicit
edit to that literal in the same commit.

`--self-test` runs 22 one-sided mutations (dropped backend path, wrong method,
drifted server call, unregistered tool, manifest-only tool, auth downgrade /
upgrade, missing key, dropped wiring, the consistent-new-tool positive control,
plus seven body cases: a documented input missing from the payload, a
documented name the API does not accept, a key sent only on the `else` branch,
the unguarded-optional positive control, an opaque payload, an unpublished
payload key, and the covered-tool set). Each must be caught; the clean tree must
pass.

## Why not run the MCP tests here

`apps/mcp-server/tests/**` need the MCP package, FastAPI/httpx and, for the
transport suite, a live nginx reverse proxy. The contracts layer is explicitly
plain-pytest-under-`scripts/` with no workspace install. This guard is the
cheap, dependency-free complement: it reconciles the *declarations*, not the
runtime transport. The `mcp-e2e` stage remains the owner of the live path.

## Change workflow

Adding or moving an MCP-facing endpoint requires updating, in one change:

1. the backend route (and a real `generate:api-client` re-export under Python
   3.15, per `docs/dev/openapi-422-unified-envelope.md`);
2. `manifest.py` (`TOOLS[].endpoint`, and `type` if the audience changed);
3. `server.py` (`_api_request` method/path, the `@mcp.tool` signature, and the
   payload key for each new field). The MCP argument name and the request-body
   property should be the same string: `blast_submit` shipped `params` vs
   `parameters` and only this guard reads both.
4. `manifest.py`'s `inputs` — the names a client is told to pass.

If any one is missed, `scripts/test_mcp_openapi_parity.py` names the tool and
the specific disagreement. Do not relax the guard; fix the declaration.

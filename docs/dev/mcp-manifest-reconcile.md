# MCP tool inventory: three declarations, one guard

`apps/mcp-server` publishes the same eight tools three times, and until this
guard nothing compared them.

| Declaration | File | What it owns |
| --- | --- | --- |
| Published inventory | `src/mcp_server/manifest.py` (`TOOLS`) | `name`, `endpoint`, `type`, `inputs`, `outputs`, `auth`, `rate_limit` |
| Callable surface | `src/mcp_server/server.py` (`@mcp.tool` bodies) | the keyword arguments a client can pass, the guards each tool runs |
| Budgets | `src/mcp_server/ratelimit.py` (`GLOBAL_LIMITER`, `SUBMIT_LIMITER`) | 60 requests/min per client, 10 BLAST submissions/hour |

`scripts/test_mcp_openapi_parity.py` reconciles the `endpoint` field against
`packages/api-client/openapi.json` (landed as `f07334f1`). It covers routes and
`type`-vs-`security` only. This suite is its complement, not a replacement: it
reads the two surfaces that guard never touches — the `inputs` a client can
discover, each tool body's guards, and the limiters those guards draw from.
Keep them separate. Merging the two would put Redis-backed budget semantics
and `openapi.json` route parity in one file, and neither can then fail for its
own reason.

## 1. A parameter nobody can pass

An MCP client builds its tool schema from `manifest.py`. A keyword added to
`server.py` alone is callable but undiscoverable — the tool accepts an argument
no client knows exists. A keyword removed from `server.py` while the manifest
still lists it is a hard error on the client's first call.

The guard compares `TOOLS[].inputs` keys against each tool function's
positional and keyword-only parameters. `ctx` is FastMCP's injection slot, not
a client parameter, and is excluded.

## 2. A tool that dropped its guard

Every tool calls `_rate_limit_error(ctx)` before touching the upstream API, and
only `blast_submit` adds `submit_quota=True`.

Deleting one tool's guard is silent. Verified by ablation on the pre-fix tree:
removing `news_list`'s `_rate_limit_error(ctx)` block leaves
`apps/mcp-server/tests/test_tools.py` at **30 passed**. Those tests exercise the
limiter class and a handful of tool paths; none of them asserts that *every*
tool consults it. A tool that skips the budget only misbehaves under load, in
production, with several clients.

The guard reads each `@mcp.tool` body via `ast` and requires exactly one
`*_rate_limit_error` call. Full-line comments are stripped first, so
commenting a guard out is not the same as having it.

## 3. A budget that silently multiplied

`ratelimit.py` prefers Redis and falls back to an in-process `FixedWindowLimiter`
when Redis is unreachable. With one replica that fallback is a reasonable
degradation; with several replicas behind nginx it multiplies the advertised
budget by the replica count, which is the opposite of a limit.

The guard pins both limits (60/60.0 and 10/3600.0) and requires that each
module-level limiter is built by `get_limiter` — the factory that owns the
Redis path and its logged fallback — rather than by `FixedWindowLimiter` or
`RedisLimiter` directly. It also requires `docker-compose.yml` to set
`SOYMUTDB_MCP_REDIS_URL`; a deployment that omits it lands on the per-process
counter with no warning in the logs anyone reads.

## What is deliberately not here

* Route existence, HTTP method, and `type`-vs-`security`.
  `scripts/test_mcp_openapi_parity.py` owns those.
* Live transport and tool behaviour. `apps/mcp-server/tests/**` need the `mcp`
  package, `httpx`, and (for `test_smoke.py`) the repository root. The
  `mcp-e2e` stage owns the live path.
* Response-shape parity between `TOOLS[].outputs` (prose) and the OpenAPI
  response schema. The outputs field is human-readable text
  (`"str | None"`, `"list of {...}"`), not a machine-checkable schema;
  pinning it would mean inventing a notation the file does not use.

## Changing a tool

A new tool passes with no allowlist edit as soon as the three declarations
agree (positive control in `--self-test`). When touching one, change together:

1. `manifest.py` — the `TOOLS` entry, including every input the function takes.
2. `server.py` — the `@mcp.tool` body: parameters, the `_rate_limit_error`
   guard, and `submit_quota=True` only if it spawns worker-bound jobs.
3. `ratelimit.py` — only for a new budget class, and only through `get_limiter`.

The guard names the tool and the field that disagree, so a partial edit fails
with a sentence rather than a runtime 404 or a silent budget bypass.

## Wiring

One entry point, pinned:

`scripts/smoke.sh` `smoke_contracts()` runs
`scripts/check_mcp_manifest_reconcile.py --self-test`, next to the other
standalone guards. Dropping it is a named failure
(`test_the_guard_is_wired_into_the_contracts_layer`), because a guard that was
quietly unregistered is the failure mode this whole family of suites exists to
prevent.

This suite deliberately does **not** take a row in the shared `tests[]` array.
That array is the merge hotspot of this repository: at the time of writing all
154 open pull requests modify `scripts/smoke.sh`, most of them by appending to
or reverting that list, so a new row is a conflict waiting to happen even in a
slot that looks quiet today. A `--self-test` line in the function body costs
one line, keeps the guard load-bearing (the self-test covers every negative
case), and lands without a rebase.

The pytest file (`scripts/test_mcp_manifest_reconcile.py`) is still collectible
by path and runs in local verification; it is what the self-test invokes.

Run directly:

```bash
python3 scripts/check_mcp_manifest_reconcile.py
python3 scripts/check_mcp_manifest_reconcile.py --self-test
pytest scripts/test_mcp_manifest_reconcile.py -q
```

Stdlib only: no MCP package, no Redis, no API, no CPython 3.15, no wheel, no
workspace install.

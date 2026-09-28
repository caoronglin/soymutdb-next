# Dependency governance

The CI dependency-governance job audits the dependency graphs used by the API, Worker, MCP server, and Web workspace. The checks are blocking: a tool failure is not converted into a pass.

## Python audit inputs

The API, Worker, and MCP checks export their committed `uv.lock` files to temporary, hash-pinned requirements files with `uv export --locked --no-emit-project --no-emit-local`. `pip-audit` then audits those public distributions. Local workspace packages are intentionally omitted because they are not published on PyPI and are covered by the repository tests and lock validation.

## Security dependency decisions

- API JWT signing uses `PyJWT` and no longer pulls `python-jose`/`ecdsa`. This removes an unfixable ECDSA timing-attack dependency from the runtime graph; the API default and production contract use HMAC JWT algorithms.
- API uses `starlette>=1.3.1`, which is compatible with the pinned FastAPI release and includes the current Starlette security fixes.
- MCP uses `fastmcp>=3.2.0,<4`; the lock currently resolves FastMCP 3.4.x, which includes fixes for the reported command-injection and OAuth resource-validation issues.
- Uvicorn ranges are explicit in the API, MCP, and Conda deployment manifests so CI and no-Docker deployments resolve the same supported runtime family.

A vulnerability exception is not currently required by the Python audit commands. If a future transitive vulnerability has no upstream fix, it must be narrowly scoped to the affected package and documented here with the reachable code path and compensating control before adding `--ignore-vuln`.

## Job environment

`knip` resolves the workspace graph while loading `apps/web/config/config.ts`
(Umi), which validates deployment origins at import time. Left unset,
`VITE_API_BASE_URL` throws before Knip analyses a single file:

```
Error: API origin is required for production deployment
  at requireDeploymentOrigin (packages/shared/src/deployment.ts)
  at /workspace/apps/web/config/config.ts
```

The analyzer then exits non-zero and the summary reads `knip: failed
(analyzer_exit_nonzero)` — a missing environment variable that looks like an
unused-code finding. `scripts/ci-job-steps.sh` therefore exports the same demo
fixture origins the offline frontend build uses (`frontend_build_demo`,
`SOYMUTDB_CI_DEMO_*`) before either `pnpm deps:graphs` or `pnpm deps:audit`, so
the setting does not depend on the provider configuring it separately. The checked-in config is the Umi Max config; the removed Vite configs are not part of the application build.

## JS security floors

Transitive utility packages with an upstream fix are pinned through the
`overrides` block in `pnpm-workspace.yaml` rather than a per-package resolution,
so one review covers every consumer:

| Package | Floor | Advisory |
| --- | --- | --- |
| `lodash` | 4.18.1 | prototype pollution |
| `ansi-regex` | 5.0.1 | ReDoS |
| `js-yaml` | 4.3.2 | GHSA-2883-xcg3-v3hh (`maxTotalMergeKeys` CPU use on empty merge sources) |

Direct dependencies are raised in the owning manifest instead — `@tiptap/*` is a
direct Admin dependency, so its floor lives in `apps/admin/package.json`.

`pnpm dedupe --check` is a blocking gate. Because the overrides above change the
resolved graph, the lockfile must be regenerated (`pnpm dedupe`) in the same
commit, or the gate reports `[ERR_PNPM_DEDUPE_CHECK_ISSUES]`.

## Reproducing locally

```bash
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/api
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/worker
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/mcp-server
PNPM_HOME=/tmp/pnpm-home pnpm install --frozen-lockfile --ignore-scripts --lockfile-only
```

The full governance runner additionally requires network access to the package registries and vulnerability services.

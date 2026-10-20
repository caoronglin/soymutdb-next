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

### Dead-code categories (`files` / `exports`)
### Legacy ClickHouse lane module exemptions (`deptry DEP001`)

`deptry` reports imports that are not declared dependencies. The API and worker
still carry the retired ClickHouse lane behind lazy imports
(`app/services/clickhouse_service.py`, `app/core/database.py`,
`worker/tasks/clickhouse_engine.py`, `worker/tasks/ingest.py`); its drivers
(`clickhouse_connect`, `chdb`) are installed only in the separate Python 3.14
`legacy-migration` image, so they must not be declared in the Python 3.15
project metadata (the packages do not support 3.15).

The policy therefore exempts exactly those modules, per rule:

```
deptry-api:    --per-rule-ignores DEP001=clickhouse_connect
deptry-worker: --per-rule-ignores DEP001=soymutdb_worker|clickhouse_connect|chdb
```

(`|` separates multiple modules for one rule; `,` would be parsed as another
`RULE=modules` pair.) The exemption is narrow: a new undeclared import anywhere
else still fails the gate, and removing the legacy lane removes the exemption.

### Duplicate versions are a gate, not a suggestion

`pnpm dedupe --check` runs in the audit set: a stale duplicate in the lockfile
(e.g. two patch versions of `dompurify` reached through different peers) fails
the governance gate. Run `pnpm dedupe` and re-verify the workspace after it
changes a lockfile.


`knip.json` reports `files`, `exports` and `types` (the `exclude` list only
keeps `unlisted` and `binaries` excluded). All three used to be excluded, which
is why unused components, export-only dead code and dead exported types
survived manual audits.

Two deliberate configuration entries exist because static analysis cannot see
the reference:

- `packages/charts/src/g2-runtime.ts` is in `ignore`: `ChartCanvas` reaches
  `createChart` through the namespace of a dynamic `import("./g2-runtime")`,
  which Knip 5 does not follow. The runtime is still covered by the charts
  unit tests.
- `scripts/scan-ant-design.mjs` and `scripts/webpack/chart-*.{ts,cjs}` are
  root/app `entry` points: the first is a documented CLI scan tool, the webpack
  files are referenced by `apps/web/config/config.ts` (one by path string).

With these entries the analyzer exits 0 on the current tree; a new unused file
or export fails the governance gate.

## JS security floors

Transitive utility packages with an upstream fix are pinned through the
`overrides` block in `pnpm-workspace.yaml` rather than a per-package resolution,
so one review covers every consumer:

| Package | Floor | Advisory |
| --- | --- | --- |
| `lodash` | 4.18.1 | prototype pollution |
| `ansi-regex` | 5.0.1 | ReDoS |
| `js-yaml` | 4.3.2 | GHSA-2883-xcg3-v3hh (`maxTotalMergeKeys` CPU use on empty merge sources) |
| `postcss-selector-parser` (6.x paths) | 7.1.6 | GHSA-rj75-hqrm-r3gf (ReDoS via crafted CSS selectors) |
| `pbkdf2` | 3.1.7 | GHSA-477h-4r7f-fvrx (crypto-browserify KDF shim) |
| `sprintf-js` | 1.1.3 | GHSA-hp3w-g68c-fv3c (ReDoS; **no patched release yet**) |

Direct dependencies are raised in the owning manifest instead — `@tiptap/*` is a
direct Admin dependency, so its floor lives in `apps/admin/package.json`.

`pnpm dedupe --check` is a blocking gate. Because the overrides above change the
resolved graph, the lockfile must be regenerated (`pnpm dedupe`) in the same
commit, or the gate reports `[ERR_PNPM_DEDUPE_CHECK_ISSUES]`.

## Accepted residual advisories (`pnpm audit`, reviewed 2026-10-18)

After the overrides above, `pnpm audit --registry https://registry.npmjs.org/`
reports 5 advisories with **no available fix**; each is bounded to build-time
tooling and none ships in the portal/admin artifacts:

| Package | Severity | Path | Why accepted |
| --- | --- | --- | --- |
| `braces` 3.0.3 | high | Umi → chokidar (dev file watcher) | Advisory has no patched version (3.0.3 is latest); not in bundle output. Recheck when upstream 3.0.4 ships or Umi upgrades. |
| `react-router` 6.30.6 | moderate ×2 | Umi 4 renderer/server (dev + preview server) | Fixed only in `>=7.18.0`, a major Umi 4 does not support; the shipped SPA uses TanStack Router, not react-router. |
| `sprintf-js` 1.1.3 | moderate | mammoth → argparse (docx import) | Latest release; advisory covers `<=1.1.3`. The 1.0.3 chain is overridden away. |
| `elliptic` 6.6.1 | low | Umi → crypto-browserify bundler shim | No patched release; development bundling only. |

Review trigger: any upstream patched release, an Umi major upgrade, or a new
reachable runtime path through these packages.

## Reproducing locally

```bash
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/api
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/worker
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/mcp-server
PNPM_HOME=/tmp/pnpm-home pnpm install --frozen-lockfile --ignore-scripts --lockfile-only
```

The full governance runner additionally requires network access to the package registries and vulnerability services.

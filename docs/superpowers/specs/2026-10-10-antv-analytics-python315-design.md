# AntV charts, first-party visit analytics, and Python 3.15 isolation — design

- Date: 2026-10-10
- Status: approved direction, per-direction detail below carries open decisions
- Approval source: user approval of four directions (AntV replaces ECharts in batches;
  close the PV/UV/referrer loop; verify Python 3.15 in an isolated mamba env; use native
  React lazy loading). The four directions are approved. The **specific** contract
  decisions listed in §8 are *not* covered by that approval and are raised as decision
  requests rather than assumed.
- Status update 2026-10-11: the user's `analytics_privacy_policy` choice
  (`selected = 第一方隐私统计（推荐）`) is recorded in the **§8 addendum** below. D1, D4 and the
  D2 direction are answered; **D5 is not approved**; D3 stays open. The earlier draft's B1
  route-template regex is **deprecated** there. The §8 list is kept as written history.
- Scope of this document: design only. No dependency was installed, no service was
  started, no source file outside `docs/` was modified.

## 1. Baseline actually read

Everything below was read in this session, not inherited from history.

| Concern | File | What it says now |
| --- | --- | --- |
| Portal chart runtime | `apps/web/src/lib/use-echarts.ts` | `await import("echarts")` inside a `useEffect`; `ResizeObserver` + `chart.resize()` + `chart.dispose()`; CSS-variable palette resolution; `notMerge` guard for empty-series interpolation crash |
| Portal chart consumers | `apps/web/src/routes/analytics.tsx:15-18`, `apps/web/src/routes/genes/$geneId.tsx:54` | already `React.lazy(() => import(...))` + `<React.Suspense fallback={<ChartFallback />}>` where `ChartFallback` is `<Skeleton className="h-72 w-full" />` |
| Portal tool charts | `apps/web/src/routes/tools/enrichment.tsx`, `.../exppattern.tsx` | ECharts `EChartsOption` built in the route module; only the runtime is lazy |
| Admin charts | `apps/admin/src/components/charts/{import-throughput,query-latency,storage-growth}.tsx` | `import * as echarts from "echarts"` **statically at the top** of two of them; `storage-growth.tsx:83` uses `echarts.graphic.LinearGradient` |
| Admin chart call sites | `apps/admin/src/routes/index.tsx:12-14,156-160` | `lazy()` + `<Suspense fallback={<ChartLoading />}>`, fed by `/admin/dashboard-stats` + `/admin/dashboard-series` |
| Admin route lazy pattern | `apps/admin/src/App.tsx:25-52,69-75` | one `lazy(() => import(...))` per route + a local `withSuspense()` helper |
| Shared chart package | `packages/charts/src/{definitions.ts,ChartFigure.tsx,index.ts}`, `packages/charts/package.json` | `"private": true`, `echarts: "catalog:"`, exports `ChartFigure` + `categoryBarChart` + `trendAreaChart`; `ChartFigure` already carries the accessible exact-value table (`<details>` + `<table data-testid="chart-values">`) and a runtime-failure branch |
| Dependency ownership | `pnpm-workspace.yaml:15-29` | catalog pins `echarts: 5.5.1`, `antd: 6.6.5`, `react: 19.3.0`, `@ant-design/pro-components: 3.1.15-2`; `minimumReleaseAgeExclude` is per-package/per-version |
| Bundle cache group | `apps/web/config/config.ts:146-151` | `charts` group tests `/node_modules/(echarts\|zrender)/`, `enforce: true` |
| Bundle budget gate | `scripts/check-bundle-size.sh:17-26,149-164` | `CHARTS_MAX_KB=370` gzip for the **required** `charts.*.js` group; `CHUNK_MAX_KB=600` per emitted asset; `ENTRY_MAX_KB=750` for `index.html` script refs |
| Gate invocation | `scripts/verify-frontend-artifacts.sh:90-91` | runs the budget against `apps/web/dist/external/assets` only |
| Analytics write path | `apps/api/app/api/v1/analytics.py` | `GET`/`POST /track.gif`, `event` pattern already includes `pageview`; `sm_sid` cookie minted by `_resolve_session_id` (httponly, samesite lax, 365 days); `_is_dnt()` short-circuits persistence; `_client_ip()` only trusts `X-Forwarded-For` from configured proxies; `Access-Control-Allow-Origin: *` + `no-store` on the pixel |
| Analytics read path | `apps/api/app/services/analytics_service.py:169-259` | `get_summary(days)` returns `total_events`, `unique_sessions` (`uniqExact(session_id)`), `events_by_type`, `top_pages`, `top_referrers`, `top_searches`, `events_by_day`; on any exception it logs and **returns the same shape with zeros** |
| Analytics authz | `apps/api/app/api/v1/analytics.py:190-204` | `GET /admin/analytics/summary` requires `RoleName.ADMINISTRATOR` |
| Analytics typed client | `packages/api-client/src/admin-analytics.ts` | pins the seven response fields; **no React consumer anywhere** (`apps/admin/src/routes/index.tsx` uses `/admin/dashboard-stats` + `/admin/dashboard-series`, not this) |
| Analytics settings page | `apps/admin/src/routes/analytics-settings.tsx:20-18,151` | documentation-only; explicitly "does not call the backend"; line 151 calls the first-party ClickHouse path "Legacy self-hosted analytics … available as a fallback" and Cloudflare the "primary visitor-statistics channel" |
| Portal perf producer | `apps/web/src/lib/perf.ts`, `apps/web/src/react-app.tsx:105-114` | the only `/track.gif` caller; PROD-only dynamic import; `sampleRate: 0.25`; sends `event=performance` over `navigator.sendBeacon`. **No pageview producer exists** |
| Analytics schema | `infra/clickhouse/init.sql:377-411`, `upgrade_variant_facts_schema.sql:171` | `analytics_events` (page, path, widget_name, search_query, source, referrer, user_agent, ip_hash, duration_ms), `MergeTree`, `PARTITION BY toYYYYMM`, `ORDER BY (timestamp, event_type, session_id)`, TTL 2 years; `web_vitals` TTL 90 days |
| Schema guard | `infra/clickhouse/test_schema_contract.py:285-313` | asserts `analytics_events.timestamp` stays `DateTime64` and both TTLs wrap in `toDateTime()` |
| Identity contract | `docs/dev/database-core-contract.md` | `public_id`/`internal_id` separation; `internal_id` MUST NOT reach external contracts, URLs, downloads or static artifacts; unreleased records must not appear; negative leakage tests are mandatory at every public boundary |
| Python pins | `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`, `packages/jobs-py/pyproject.toml` (`requires-python >=3.14`, `ruff target-version = "py314"`), `apps/mcp-server/pyproject.toml` (`>=3.11`) | locks: `apps/api/uv.lock` and `apps/worker/uv.lock` `requires-python = ">=3.14"`; `packages/jobs-py` has no `uv.lock` |
| Python CI pins | `.cnb.yml` (9× `image: python:3.14`), `.cnb/env/Dockerfile.frontend:52`, `infra/docker/Dockerfile.{api,worker,migrate,migrate-clickhouse}` (`python:3.14.6-slim`), `apps/mcp-server/Dockerfile` (`python:3.12-slim`), `scripts/ci-job-steps.sh:54` (`PYTHON_VERSION="${SOYMUTDB_CI_PYTHON_VERSION:-3.14}"`), `scripts/test_ci_job_contracts.py` (hardcoded `PYTHON_VERSION = "3.14"`) | one pin change without the whole set breaks the CI contract tests |
| Local environment | `.ai-memory/LOCAL-RUN-ENV.md`, `docs/dev/mamba-validation-environment.md`, `mamba env list`, `mamba --version` | mamba 2.5.0; `webdb` (3.14, full PostgreSQL server); workspace-local `.mamba-root/envs/postgres16` is the established isolated-env precedent; **no 3.15 env exists**; no Docker, no Redis server, no port 80; `uv` under `~/.local/share/uv/tools` is read-only |
| Approved-design history | `docs/aegis/work/2026-09-28-portal-quality-improvements/10-intent.md:61`, `docs/aegis/plans/2026-09-28-admin-editable-footer-search-font.md:40,57`, `docs/aegis/adr/` (**empty**) | GoatCounter appears only as a plan-level statement and as an explicit "separate future slice"; no ADR, no deploy/infra/compose/script hit, no code |
| Root phase plan | `plan.md:527-536,606-608` | `@soymutdb/charts` is meant to be the **only** chart dependency entry; "one chart per previewable commit"; last commit removes ECharts runtime/CDN/helper |

## 2. Direction A — replace ECharts with AntV

### 2.1 Library choice

`@ant-design/plots`, exact-pinned through the `pnpm-workspace.yaml` catalog, replacing the
`echarts: 5.5.1` catalog entry.

Registry metadata recorded for the install step, all of it **metadata only**:
`@ant-design/plots@2.6.8` declares `peerDependencies { react: ">=16.8.4", react-dom: ">=16.8.4" }`,
declares **no** `antd` peer, and depends on `@antv/g2: ^5.2.7`. `@antv/g2plot@2.4.35` is
excluded: it targets G2 4.x and its own README states no G2 v5-based successor.

Two consequences that must not be papered over:

- **No automatic antd theme inheritance.** There is no antd↔G2 coupling in the registry
  metadata. G2 owns its own theme object. A theme bridge is required work, not a free
  side effect of choosing this library.
- **No "safe version ceiling" claim.** An AntV supply-chain incident is referenced by
  third-party write-ups, but no official advisory was read in this session. This design
  therefore states no safe/unsafe version boundary. The install step must check the npm
  advisory feed, GitHub Security Advisories and AntV's own announcement before installing,
  and record what it found.

### 2.2 Single chart owner

`packages/charts` (`@soymutdb/charts`, `private: true`, version 2.1.0) becomes the real
runtime facade. `plan.md:532` and `plan.md:606-608` already designate it as the only chart
entry point; today it is the only piece of this system that is *named* as the owner while
being consumed by nobody, and it is the only chart code carrying the accessible
exact-value alternative.

It is **not** deleted. Two facts settle that: `packages/charts/package.json` is
`"private": true`, so it is not a published API surface and nothing external can break;
and `plan.md` designates it as the migration destination, so deleting it would retire the
one place the codebase already agreed charts belong.

What the facade owns after Direction A:

- a runtime wrapper that lazy-imports the chart engine, initialises on a measured element,
  observes resize, and disposes on unmount and on theme change;
- the CSS-variable → chart-theme bridge (the existing `--chart-1..5`, `--impact-*`,
  `--background`, `--foreground`, `--muted-foreground`, `--border` set in
  `apps/web/src/lib/use-echarts.ts:40-56` becomes the bridge's input contract);
- the reduced-motion / animation-intensity input from
  `apps/web/src/lib/animation-context.tsx`;
- the accessible contract `ChartFigure` already implements: `role="img"` + `aria-label` +
  `aria-describedby`, an `<details>`-wrapped exact-value table, an empty state, and a
  runtime-failure state that keeps the description in the accessibility tree.
- a **serializable** definition type. `ChartDefinition` is currently `EChartsOption`
  (`packages/charts/src/definitions.ts:10`). After migration it is a plain structured
  value owned by the facade, so route modules never see engine syntax.

`apps/web` and `apps/admin` gain `@soymutdb/charts` as a workspace dependency and drop
their own `echarts` dependency. `apps/web/src/lib/use-echarts.ts` retires.

### 2.3 Migration order and the one hard unknown

One chart per previewable commit (`plan.md:533`), each independently buildable and
revertable, ECharts removed only at the end:

1. Install + measure + React-19 runtime smoke. **No production component changes.**
2. Facade runtime + `ChartFigure`/`definitions` migrated; `packages/charts` tests updated.
3. Admin 3 charts (`import-throughput`, `query-latency`, `storage-growth`).
4. Web 5 charts (`/analytics` ×4, `/genes/$geneId` ×1).
5. Web tool charts (`enrichment.tsx` heatmap/dot views, `exppattern.tsx` heatmap).
6. Remove ECharts: `use-echarts.ts`, catalog entry, 3 `package.json` deps, the orphan
   `ECharts CDN URL` field at `apps/admin/src/routes/settings.tsx:981-986` and its i18n keys.
7. Budget verification.

**Hard unknown that gates step 1.** `scripts/check-bundle-size.sh:154` requires a
`charts.*.js` cache group to exist and caps it at **370 KB gzip**, and the group is
`enforce: true` (`apps/web/config/config.ts:146-151`), so the whole engine lands in one
chunk regardless of per-component imports. The current engine occupies that group today
at roughly 345 KB gzip. G2 5.x is not known to fit. Step 1 therefore measures the real
chunk before any component is migrated, and the measurement decides:

- fits → proceed as written;
- does not fit → **stop and return to design**. The options are a reviewed budget change
  (a real first-load performance trade-off, so it needs a decision, not a silent
  `CHARTS_MAX_KB` bump) or a different engine. Silently raising the budget is explicitly
  rejected.

The cache-group test at `config.ts:147` must be repointed from `(?:echarts|zrender)` to the
new package names in the same step that installs them, otherwise the required group is not
emitted and the gate fails for the wrong reason.

No chart ever holds both engines at runtime. There is no `try echarts → catch plots`
render path; a broken new chart shows its accessible fallback, it does not silently
re-render through the old engine.

### 2.4 Per-chart correctness notes

- `packages/charts/src/definitions.ts:81-99` (`trendAreaChart`) is documented in
  `docs/dev/vue-parity/README.md:22` as having crashed a page by binding ISO date strings
  to a quantitative scale. The migration must keep the x axis a **category** axis, as the
  current ECharts option does (`definitions.ts:86`).
- `apps/admin/src/components/charts/storage-growth.tsx:83` uses
  `echarts.graphic.LinearGradient`, the only genuinely engine-specific API in the set. It
  becomes an explicit gradient in the theme bridge, not an import.
- `apps/web/src/lib/use-echarts.ts:164-182` documents a real ECharts crash when a series
  transitions between empty and populated (`interpolate1DArray`). That workaround disappears
  with the engine; the empty-data behaviour it protected must be reproduced as an explicit
  state, not left to chance.

## 3. Direction B — close the PV/UV/referrer loop

### 3.1 Owner decision, and the conflict it resolves

The loop is closed on the **existing first-party owner**: `/track.gif` →
`analytics_events` → `AnalyticsService.get_summary` → `GET /admin/analytics/summary` →
`getAdminAnalyticsSummary` → a new admin route.

**GoatCounter is not adopted**, and this is a reported conflict, not a silent choice:

- `docs/aegis/adr/` is empty — there is no accepted architecture record for it.
- `deploy/`, `infra/`, `scripts/`, the compose files and `.cnb.yml` contain no reference.
- It exists only as a statement in a work-intent file
  (`docs/aegis/work/2026-09-28-portal-quality-improvements/10-intent.md:61`: "GoatCounter
  replaces only public pageview analytics") and as an explicit exclusion in a plan
  (`docs/aegis/plans/2026-09-28-admin-editable-footer-search-font.md:40,57`: "GoatCounter
  work is a separate approved slice, not part of this plan").
- Adopting it now would add an analytics SaaS, a different visitor-identity model, a new
  deployment unit and a second authoritative read path — none of which the approval covers.

Repairing the existing owner is therefore both the approved reading and the
anti-entropy-correct one: adding a second owner beside a dormant first-party one is the
duplicate-owner failure this project already has a rule against. **This still needs an
explicit confirmation from the user** (§8, D1); if GoatCounter is in fact wanted, this
design is superseded before implementation.

### 3.2 Second conflict: the admin page says the opposite

`apps/admin/src/routes/analytics-settings.tsx:151` tells operators that first-party
ClickHouse is "Legacy self-hosted analytics … available as a fallback" and Cloudflare
Web Analytics is the "primary visitor-statistics channel". After this loop is closed that
copy is wrong. The page currently never calls the backend
(`analytics-settings.tsx:18`), so the new visitors route is a **new** route, not a
retrofit of this one; but the copy must be reconciled or the console will contradict
itself. Raised as §8, D2.

### 3.3 What is measured

| Metric | Definition | Source |
| --- | --- | --- |
| PV | count of accepted `pageview` rows in the window | new `pv` field = `countIf(event_type='pageview')` |
| UV | `uniqExact(session_id)` over the window | already `unique_sessions`; reused verbatim |
| Referrer source | referrer **category**, not the raw URL | new server-side classifier (§3.5) |
| Top pages | route **template** buckets | new client producer + server allowlist (§3.5) |

**UV caveat is mandatory in the UI copy.** `sm_sid` lives 365 days
(`analytics.py:32`), so `uniqExact(session_id)` is a *session* count over a long-lived
cookie, not a person count, and it is not comparable across windows. The admin UI must say
"distinct sessions (365-day first-party cookie)" — it must not say "unique visitors". The
cookie lifetime is not changed by this slice.

`search_query` / `top_searches` is **not** populated by this slice. Storing raw search text
means persisting user-typed free text — which may contain an unreleased identifier or an
internal identifier — into an analytical store. The server-side enum, column and query
stay for compatibility; the producer does not exist and the admin UI labels the panel as
not collected. See §8, D4.

### 3.4 Client producer

New `apps/web/src/lib/analytics.ts`, a sibling of the existing `perf.ts` and following the
same PROD-only dynamic-import wiring already in `apps/web/src/react-app.tsx:105-114`. It
fires on route change, honours `navigator.doNotTrack`, and sends one `pageview` through
the **existing** `GET /track.gif` with `event=pageview&page=<template>&site=<variant>`.
It sends no query string, no hash, no `document.title`, no referrer of its own (the server
already reads the `Referer` header), and no cookie of its own. It is dynamically imported,
never a top-level import, so it adds nothing to the entry bundle.

### 3.5 Server-side allowlist, and why the server is the real protection

Client-side normalisation is convenience. The API is the boundary that must not persist
anything it should not, because the collector is unauthenticated and
`Access-Control-Allow-Origin: *` (`analytics.py:94`).

**Route template grammar, not a route list.** Enumerating the portal's ~19 routes inside
the API would duplicate portal knowledge and drift. Instead `page` is accepted only when
it matches

```
^/[a-z0-9]*(?:/[a-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)?)*$
```

with a hard length cap. That grammar is chosen because it **cannot** match SoyMutDB
identifier shapes: no uppercase, no dot, no digits-leading segment, no `..`, no `?`, no
`#`. `Glyma.01G000100` (a public id), `42` (an internal id), a release slug with a dot, and
any query string all fail it. Non-matching input is recorded as `"/other"` and counted, so
the drop is observable rather than silent.

**Referrer categorisation.** The raw `Referer` header is reduced on the server to a bounded
category (`direct` / `search` / `social` / `referral` / `internal` / `other`) written to the
existing `source` column, plus a **scheme://host[:port] only** origin written to `referrer`.
This is what stops a gene detail URL from landing in ClickHouse while keeping "来源"
statistics meaningful. The full query string, path and query parameters never reach storage.

**The `path` column stops being populated.** `analytics.py:106-107` currently accepts a
free-form `path` up to 1024 chars and the client sends `location.pathname`
(`perf.ts:60`). That is a raw URL field with no normalisation and it is the largest
leakage surface in the existing schema. This slice stops writing it and the writer is
removed rather than left as an unused optional.

**Site variant is explicit, never inferred.** `AGENTS.md` forbids inferring the site
variant from host, IP, cookie or user agent. `site` is supplied by the portal from its
build-time `VITE_SITE_VARIANT` constant and validated server-side against
`{external, internal}`; anything else is rejected to `"/other"`-equivalent handling. This
requires no new deployment environment variable, and it keeps external and internal
traffic separable in one shared ClickHouse.

**Release and assembly get no column.** They are deliberately absent, and this is a
decision rather than an omission: pageview events carry no biological scope, and giving
the table a `release` column would create exactly the invitation to aggregate across
releases and across v4/v5 that `docs/dev/database-core-contract.md` forbids. Release- and
assembly-scoped counting stays in the PostgreSQL-authoritative `/api/v1/stats` path, which
is untouched by this slice.

### 3.6 Schema and contract changes

Additive only:

- `infra/clickhouse/init.sql` and `infra/clickhouse/upgrade_*.sql`:
  `ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS site LowCardinality(String) DEFAULT ''`.
  No `ORDER BY` change, no new table, no materialised view. The existing
  parts-per-INSERT pressure documented at `docs/dev/performance-optimization-plan.md:416-482`
  (batched inserts, `ORDER BY (event_type, toDate(timestamp), session_id)`) is a
  **pre-existing, separately-planned** item and stays out of this scope.
- `infra/clickhouse/test_schema_contract.py`: a guard that `site` is declared and
  `LowCardinality(String)` in both DDL files, next to the existing timestamp/TTL guards.
- `get_summary` gains an **additive** `available: bool` field. Today
  `analytics_service.py:248-258` swallows every exception and returns the same shape with
  zeros, which makes "ClickHouse is down" indistinguishable from "no traffic" — precisely
  the error-masking fallback this work must not introduce. `available` lets the UI show an
  antd `Alert` for the first case and an antd `Empty` for the second. Existing consumers
  ignore unknown keys, so this stays backward compatible; the endpoint is in the committed
  OpenAPI snapshot, so the client contract check still runs.

### 3.7 Admin surface

New lazy admin route rendering PV, UV, daily trend, route-template ranking and referrer
source mix, consuming the existing `getAdminAnalyticsSummary` typed client — which today
has **zero** React consumers, so this gives an already-tested client its first real caller
instead of adding a new one. Charts come from the Direction A facade. Loading is antd
`Skeleton`, no-data is antd `Empty`, collection failure is antd `Alert`.

Authorization is unchanged and stays administrator-only (`analytics.py:200-202`), with a
negative test that an authenticated non-administrator is refused and that the refusal
carries no analytics payload.

## 4. Direction C — Python 3.15 in an isolated environment

### 4.1 Position

Python 3.15.0 is a stable release (release date 2026-09/10 per the official release page,
verified by an earlier session; re-verified at install time). This slice produces
**evidence**, not a migration. 3.14 remains the production and CI interpreter and is not
being retired; 3.14 is still in bugfix with a long support horizon.

### 4.2 Environment shape

- Interpreter lives at `.mamba-root/envs/py315`, created with
  `MAMBA_ROOT_PREFIX=$PWD/.mamba-root CONDA_PKGS_DIRS=$PWD/.mamba-root/pkgs mamba create -p ... --override-channels -c conda-forge python=3.15.0`.
  This reuses the `.mamba-root` precedent already documented in
  `docs/dev/mamba-validation-environment.md`, leaves `mamba env list` untouched, and cannot
  overwrite `webdb` (3.14 + PostgreSQL server) or any other user environment.
- **Regular CPython build.** The `cp315` build is selected explicitly; the free-threaded
  `cp315t` build is not approved and must not be selected. Pin the interpreter by the
  package build string, not only by `python=3.15`, so a future free-threaded default cannot
  slip in.
- **mamba supplies the interpreter; uv/pip supplies the Python packages.** The existing
  projects are uv-managed with committed `uv.lock` files. Installing project dependencies
  through conda would create a second, invisible dependency resolution path — the mixed
  toolchain this slice is supposed to avoid. Use `uv pip install --python
  .mamba-root/envs/py315/bin/python …` against the pinned lock.

### 4.3 Order and stopping points

`packages/jobs-py` → `apps/api` → `apps/mcp-server` → `apps/worker`. The API/MCP/jobs
tier carries the PostgreSQL-authoritative core and is verified first. The worker is last
because its biology stack is where the unknown risk actually is.

Package-level facts gathered earlier, all **metadata only, none re-verified by an install**:

| Package | Locked version | Wheel situation for 3.15 |
| --- | --- | --- |
| `pyfaidx` | 0.9.0.4 | pure `py3-none-any` wheel — expected fine |
| `python-igraph` | 0.11.9 | abi3 wheel — expected fine |
| `leidenalg` | 0.10.2 | abi3 wheel — expected fine |
| `polars` (+ `polars-runtime-32`) | 1.43.2 | native runtime wheel availability on 3.15 unknown |
| `cyvcf2` | 0.34.0 | no 3.15 wheel seen; would need an sdist/Cython build |

The earlier "no cp315 wheels at all, everything is blocked" conclusion is **wrong** and is
not carried forward. Equally, none of the rows above is treated as proven: the whole table
is what the install step is for.

### 4.4 Promotion evidence, written before the work

The isolated environment changes **no** production pin. Specifically, phase 1 does not
touch `requires-python`, `ruff target-version`, any `uv.lock`, `.cnb.yml` images,
`.cnb/env/Dockerfile.frontend`, `infra/docker/Dockerfile.*`,
`apps/mcp-server/Dockerfile`, `scripts/ci-job-steps.sh` or
`scripts/test_ci_job_contracts.py`. `scripts/test_ci_job_contracts.py` hardcodes
`PYTHON_VERSION = "3.14"` and asserts it in several places; a partial edit breaks the
delivery contract for no benefit.

Promotion to a real migration requires, as one separately-approved slice: a 3.15
`uv.lock` re-resolve for every project, the biology stack either shipping 3.15 wheels or
moving to conda-forge, `.cnb.yml` image bumps validated against the recorded glibc
constraint (`.cnb.yml:150-151`: node 26.13.0 is bookworm/glibc 2.36, python 3.14 needs
2.38, so a 3.15 Debian base is a strictly newer baseline and the constraint must be
re-verified, not assumed), and all three `Dockerfile` families bumped together.

### 4.4a Addendum added after the C1/C2 slice ran (user-supplied checklist)

- The official source for 3.15 feature claims is
  <https://www.python.org/downloads/release/python-3150/> (verified HTTP 200, release
  date Oct. 9, 2026). The full "What's New in Python 3.15" page could not be retrieved
  inside the network budget (Jina reader timeout, curl exit 124) and is recorded as a
  failed fetch, not as a read.
- Compatibility checks added to this direction: `-X warn_default_encoding` regression
  plus an honest `DeprecationWarning` census; removed `sre_*` / `cgi` / legacy `sqlite3`
  interface probes. Third-party deprecations are **not** mechanically fixed, and a
  silenced run is **not** a pass — `apps/api/pyproject.toml` already ignores
  `DeprecationWarning` in pytest, so an api run must override that first.
- "Phase 1 changes no production pin" describes **this phase only**. The overall objective
  is still the core migration once the evidence is sufficient; zero pins is not the
  permanent end state.
- **Python native lazy imports (PEP 810) are a phase-2 candidate**, verified against
  official sources first, kept out of this compatibility track and **not enabled
  globally**. `sentinel` (PEP 661), `frozendict` (PEP 814), the experimental JIT and
  PEP 799 profiling join that phase-2 list. No LLVM is installed on this host. This does
  not alter the approved **frontend** native React lazy/Suspense scope in §5.
- C1/C2 evidence is recorded in `docs/dev/mamba-python315-validation.md`.

### 4.5 Local evidence ceiling

This host has no Docker, so the testcontainers-backed tests and the ClickHouse-backed
integration tests cannot run here. What *can* run and be recorded: interpreter version,
dependency resolution, `packages/jobs-py` tests, `apps/mcp-server` tests, and the
`apps/api` tests that are reachable against a scratch PostgreSQL fixture database using
the documented `postgres16` cluster pattern. Any layer that cannot run here is reported
as not-covered, never as passing.

## 5. Direction D — native lazy loading

The codebase already does this natively; the work is to make it complete and to stop the
remaining eager paths. **No custom lazy framework, no custom defer plugin, no new
abstraction layer.**

Existing native patterns to follow, not to reinvent:

- route-level: `React.lazy(() => import("./routes/x"))` + a local `withSuspense()` helper
  (`apps/admin/src/App.tsx:25-75`);
- component-level inside a route: `React.lazy` + `<React.Suspense fallback={<Skeleton/>}>`
  (`apps/web/src/routes/analytics.tsx:15-18,161-170`,
  `apps/web/src/routes/genes/$geneId.tsx:54,459-461`);
- feedback components: antd `Skeleton` while loading, `Empty` when there is nothing to
  show, `Alert` when collection failed.

What is actually wrong today:

| Site | Problem |
| --- | --- |
| `apps/admin/src/components/charts/import-throughput.tsx:2`, `.../storage-growth.tsx:2` | `import * as echarts from "echarts"` is a **static top-level** import of the whole engine, in a file whose only dynamic part is `echarts.init` inside an effect |
| `apps/web/src/lib/use-echarts.ts:129` | a library dynamic import inside an effect is not a component or route boundary; it is what produces a single 1 MB / ~345 KB gzip chunk |
| `apps/web/src/routes/tools/enrichment.tsx`, `.../exppattern.tsx` | chart definitions are built in the route module, so the route chunk carries chart code even before the engine loads |

Direction A removes the first and third by moving chart code into the lazy facade;
Direction D removes the second by deleting the hook. The verification is the build, not an
opinion: after the migration the bundle gate must show the `charts.*.js` group still
emitted, every emitted asset within `CHUNK_MAX_KB`, and the `index.html` entry total
within `ENTRY_MAX_KB`.

## 6. Change Necessity

Each direction needs source change; none is reachable by configuration or documentation.

- **A.** Removing a JavaScript engine requires new source and a new dependency. No
  `pnpm-workspace.yaml` edit removes a bundle.
- **B.** `/admin/analytics/summary` returns zeros because a table has no producer and the
  client has no consumer. No configuration creates a producer or a consumer.
- **C.** Layer-③ evidence (does a solver actually resolve this stack on 3.15?) requires an
  interpreter that does not exist here. No document produces it.
- **D.** Static top-level imports cannot be removed by configuration.

Minimum code boundary: one new shared chart runtime owner (`packages/charts`), one new
portal telemetry producer (`apps/web/src/lib/analytics.ts`), one new admin route, one
additive ClickHouse column, one additive API response field, one isolated environment
directory.

## 7. Compatibility boundary

- Existing `GET`/`POST /track.gif` stays. `event` keeps accepting `pageview|click|search|
  widget|performance`; `perf.ts` is untouched; `sm_sid` keeps its name, 365-day lifetime
  and `HttpOnly`/`SameSite=Lax` attributes. DNT handling and the trusted-proxy rule for
  `X-Forwarded-For` are unchanged.
- `web_vitals`, its 90-day TTL and its sampling rate are untouched.
- `analytics_events` gains one column. No column is dropped, retyped or reordered; no table
  is dropped; no historical row is rewritten. **No production data is deleted and no
  database identity changes.**
- `/api/v1/stats` and the public `/analytics` content-statistics page are untouched; this
  is a different system from website visit statistics.
- `/admin/dashboard-stats` and `/admin/dashboard-series` are untouched.
- `/admin/analytics/summary` keeps all seven existing fields and gains `available`.
- `categoryBarChart` / `trendAreaChart` / `ChartFigure` keep their names, props and their
  `data-testid` hooks (`chart-empty`, `chart-unavailable`, `chart-values`) so existing
  tests stay meaningful; `ChartDefinition` changes shape, which is a type-level break
  confined to the facade.
- Python: no production pin changes in this slice.

## 8. Decisions required before implementation

These are *not* covered by the four approved directions.

- **D1 — GoatCounter.** Confirm it is dropped in favour of repairing the existing
  first-party owner. Evidence in §3.1 says it was never an accepted architecture decision.
  If it is still wanted, stop: it is a different design with a second owner.
- **D2 — Cloudflare copy.** `apps/admin/src/routes/analytics-settings.tsx:151` currently
  makes Cloudflare primary and first-party legacy. Confirm the reconciled wording, and
  whether the first-party visitors route is the console's single owner of PV/UV/source.
- **D3 — `charts` bundle budget.** Authorise measuring the AntV chunk before migrating any
  component, and pre-agree what happens if it exceeds 370 KB gzip: a reviewed budget change
  (a first-load performance trade-off) or a different engine. Silent budget relaxation is
  not on the table.
- **D4 — search text.** Confirm this slice does not collect raw search terms, so
  `top_searches` stays empty and the panel says so.
- **D5 — `site` column.** Confirm adding `site LowCardinality(String)` to `analytics_events`
  (additive `ALTER`, new DDL guard) rather than inferring the variant at the API.

### §8 addendum — answered 2026-10-11 by the user's `analytics_privacy_policy` choice

**`selected = 第一方隐私统计（推荐）`.** Approved contract, recorded as given: use the
existing backend; record **only route templates**; under DNT send **no tracking cookie**;
**stop the public site's third-party analytics scripts**; **do not touch production data**.
Both options excluded internal identifiers, raw search text and full URLs, so that exclusion
holds without further choice.

| Decision | State |
| --- | --- |
| D1 | **answered** — GoatCounter dropped; the first-party owner is repaired, not replaced |
| D2 | **answered in direction** — third-party scripts stop; the admin settings wording and the CSP stay consistent with the code, reconciled **after** the code lands, serially |
| D3 | **still open** — needs a real gzip measurement, see §8 |
| D4 | **answered** — no raw search terms; `top_searches` stays empty and labelled not collected |
| D5 | **NOT approved** — no `site` column, no additive `ALTER`; B2 does not start |

Binding detail:

- **The internal build never enters the anonymous producer.** A client `site` marker is not
  a permission boundary; the API must not decide the variant from a guessable host, IP or
  user agent. A genuinely needed schema/site dimension requires re-checking current settings
  and read queries as its own step. **Nothing here implicitly approves D5.**
- Raw `q` / `ref` / `source` / `path` client text is **not persisted and not echoed**;
  normalise server-side or into a fixed enum. A parameter kept for **request** backward
  compatibility only must not store its raw value.
- **DNT is processed before any `Set-Cookie`.** Existing historical cookies are **not**
  deleted and no store is cleared; the figure is **session count, not people**.
- IP and other extra stable identifiers are evaluated against the minimal-collection goal;
  until then no claim that the measurement scope has changed.
- Summary is **private / `no-store`**; **availability ≠ zero traffic**; **negative leakage
  tests remain mandatory**.
- Stopping the public site's Cloudflare script is **code + later build configuration**, with
  **no** online secret or deployment action and **no** production-data action.

**Not approved, and not inferable from the above:** production database cleanup, a new
tracking identity, a new site column, or a whole-set Python upgrade.

**Design status is still NOT DONE** — this addendum records a decision, not an
implementation and not a permission-matrix test result.

### Superseded: the plan's original B1 route-template regex

The regex `^/[a-z0-9]*(?:/[a-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)?)*$` from the earlier draft of
plan task B1 is **deprecated and not implementable as written** — it has counterexamples and
**42 mutants**; it admits numeric-only segments and arbitrary digit runs, so internal numeric
ids and coordinate-like paths pass. **Rejecting it does not authorise a forbidden-digit
character class.** The replacement direction is a **finite canonical route-template
allowlist** + **raw path-parameter normalisation** into the canonical template +
**front/back drift verification** between the templates the portal can emit and the server
allowlist.

## 9. Verification posture

TDD route is **off** (user decision). No test-first ordering is prescribed. Regression
coverage is still mandatory for behaviour changes. Everything below must be adapted to the
machine per `.ai-memory/LOCAL-RUN-ENV.md` and `docs/dev/mamba-validation-environment.md`
— thread caps `GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`, turbo
`--concurrency=1`, and the `mamba` PATH export — rather than guessed.

- Frontend gates, in the order `scripts/verify-frontend-artifacts.sh` runs them:
  `pnpm turbo run test`, `pnpm turbo run lint`, `pnpm turbo run typecheck`,
  `bash scripts/check-bundle-size.sh apps/web/dist/external/assets`, plus
  `python3 scripts/check_page_registry.py`, `python3 scripts/check_web_query_keys.py`,
  `python3 scripts/check_admin_content_architecture.py`,
  `python3 scripts/check_visible_i18n.py`,
  `node scripts/check_visible_i18n_react.mjs`, and the OpenAPI client contract check.
- Analytics: `apps/api` pytest for the collector and the summary; the analytics tests
  must include **negative leakage** assertions — a pageview naming a public id, an
  internal numeric id, a release slug, a query string or a full URL must not reach stored
  rows or the admin response; a non-administrator is refused; DNT is honoured. Plus
  `python3 -m pytest infra/clickhouse/test_schema_contract.py -q` for the DDL guard.
- Charts: `packages/charts` Vitest, the web and admin route tests, and a real browser
  check that a chart renders, resizes on viewport change, disposes on route change, and
  falls back to its exact-value table when the engine fails to initialise.
- Python: `packages/jobs-py`, `apps/mcp-server` and `apps/api` pytest under the 3.15
  interpreter, with pass/fail counts recorded. Layers needing Docker are reported
  **not covered**, never as passing.

## 10. Risks

| Risk | Severity | Handling |
| --- | --- | --- |
| AntV engine exceeds the 370 KB gzip `charts` budget | high | measured before any migration (D3); stop and re-decide |
| G2 needs explicit work to match the existing CSS-variable theme | medium | theme bridge is scoped work, not an assumption (§2.1) |
| No upstream React 19 compatibility evidence for `@ant-design/plots` | medium | runtime smoke in step 1; `react >=16.8.4` is metadata only |
| AntV supply-chain advisory unverified | high | advisory check before install; no version-safety claim made |
| The console contradicts itself on Cloudflare vs first-party | medium | D2 before the new route ships |
| `uniqExact(session_id)` mislabelled as "visitors" | medium | mandatory UI wording (§3.3) |
| `get_summary` masking failure as zeros | medium | additive `available` field (§3.6) |
| Encrypted/derived referrer origins still identifying | medium | category-first, origin-only, documented |
| ClickHouse integration unverifiable on this host | medium | DDL-text guards + chdb unit tests; real-store evidence marked not covered |
| 3.15 wheels missing for part of the biology stack | medium | expected; worker tier is last and may legitimately stop at "blocked" |
| Python pin drift if the whole set is not moved together | high | phase 1 touches zero production pins (§4.4) |
| Pre-existing dirty files overlap the files this work must edit | high | see the work record; coordinate before editing |

## 11. Self-review

Approved scope covered: all four directions have an owner, an order and a verification
route. Placeholders: none — every task in the plan names files and commands. Owner
consistency: one chart owner (`packages/charts`), one analytics owner (first-party
ClickHouse), one chart definition type. Minimum change: additive schema and additive
response field; no drops, no reorders, no rewrites. Compatibility: §7. Exact verification:
§9 with machine-specific adaptation, and explicit not-covered reporting. Conditional
triggers: bundle-budget and Python-pin triggers are written in as stops, not as silent
relaxations. Retirement: ECharts removal is the last task with its own verification;
`use-echarts.ts` and the orphan CDN setting retire there. Open decisions are isolated in
§8 rather than assumed inside the design.

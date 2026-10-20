# Plan — AntV charts, visit analytics loop, Python 3.15 isolation

- Design: `docs/superpowers/specs/2026-10-10-antv-analytics-python315-design.md`
- 附属计划：[`2026-10-11-ant-design-mobile.md`](./2026-10-11-ant-design-mobile.md)（公共站移动端
  antd-mobile 候选方案）。该附属计划**仅为研究与计划，不新增任何 implementation 授权**：其
  T1–T5 未获本主计划背书，不随本主计划执行派发；其 A 轨 bundle 预算实测依赖本主计划的
  integration 结论，由协调者**串行后置派发**，不阻塞本主计划任何轨道。
- Date: 2026-10-10
- TDD Route: **off** (user decision). No test-first ordering. Regression coverage is still
  mandatory for behaviour changes, and every task below names the regression it must add.
- ArchitectureReviewRequired: **yes** — cross-module compatibility (3 apps + 1 shared
  package + bundler config + CI), a privacy-bearing telemetry write path, an additive
  analytical-store schema change, and a new admin route. Review is satisfied by the design
  spec; the five decisions in §8 of that spec are still open and are gating.
- Execution route: `subagent-driven`. The tracks below are genuinely independent and have
  disjoint write scopes. The coordinator captures `TaskStartSnapshot` per slice and owns all
  Git lifecycle. Nothing here commits.

## Approval record — 2026-10-11 (analytics privacy policy)

Recorded from the user's real choice in `ask_user_question` (`analytics_privacy_policy`):
**selected = 第一方隐私统计（推荐）**. Its description is the approved contract: **use the
existing backend, record only route templates, send no tracking cookie under DNT, stop the
public site's third-party analytics scripts, and do not touch production data.** Both
candidate options excluded internal identifiers, raw search text and full URLs, so that
exclusion is approved without further choice. This closes decisions; it approves **nothing
beyond what the user chose**. No production database cleanup, no new tracking identity, no
new `site` column and no whole-set Python upgrade were approved, and none may be inferred
from this record.

| Decision | State after this record |
| --- | --- |
| D1 GoatCounter | **answered** — dropped; the first-party owner is repaired, not replaced |
| D2 Cloudflare copy | **answered in direction** — public-site third-party analytics scripts stop; the `analytics-settings.tsx` wording and the CSP must stay consistent with the code and are reconciled **after** the code lands, **serially**, not improvised |
| D3 charts budget | unchanged — still gated on a real measurement (§ Risks and stop conditions) |
| D4 search text | **answered** — no raw search terms; `top_searches` stays empty and labelled not collected |
| D5 `site` column | **NOT approved** — no additive `site LowCardinality(String)`, and no new column at all. **B2 does not start** |

Constraints that travel with the approval:

- **Route templates only.** Raw `q` / `ref` / `source` / `path` client text is **never
  stored and never echoed back**; it is normalised server-side or into a fixed enum. If an
  API parameter is kept for **request** backward compatibility only, its raw value must not
  be stored.
- **The internal build does not enter the anonymous producer.** A client `site` marker is
  **not** a permission boundary and **not** a variant decision: the API must never decide the
  variant from a guessable host, IP or user agent. If a schema/site dimension is genuinely
  needed, re-check the current settings and read queries in a separate step. **D5 is not
  implicitly approved by this record.**
- **DNT is handled before any `Set-Cookie`.** Existing historical cookies are **not**
  deleted and no store is cleared. The cookie-based figure is labelled **session count, not
  people**.
- **IP and other extra stable identifiers** are assessed against the minimal-collection goal
  before adoption; until that assessment exists, **do not claim the measurement scope has
  changed**.
- **Summary responses are private / `no-store`.** **Availability is not zero traffic** — a
  working-but-empty store must never be shown as no traffic. **Negative leakage tests remain
  mandatory.**
- Stopping the public site's Cloudflare/third-party script is **code plus a later build
  configuration** step. It performs **no** online secret, deployment or production-data
  action.

**Plan status is still NOT DONE.** An approval is not an implementation, and it does not
substitute for the real permission-matrix tests.

## Goal

Remove the ECharts runtime by moving every chart onto `@ant-design/plots` through the
existing `@soymutdb/charts` facade, while adding native lazy boundaries on the way; close
the website PV/UV/referrer loop on the existing first-party ClickHouse analytics owner from
portal producer to admin display, without ever persisting an internal identifier, a full
URL, an unreleased record or a raw search term; and obtain real solver-plus-test evidence
for Python 3.15 in a throwaway mamba environment that changes no production pin.

## Architecture

Four tracks, three owners:

```
  packages/charts (@soymutdb/charts)      <- single chart runtime owner
    ^            ^                              (lazy engine, theme bridge,
    |            |                               resize/dispose, a11y + exact-value table)
  apps/web      apps/admin

  apps/web/src/lib/analytics.ts  --pageview-->  GET /track.gif  -->  analytics_events (CH)
                                                                   |
  apps/admin/src/routes/analytics/visitors.tsx  <-- getAdminAnalyticsSummary <-- GET /admin/analytics/summary

  .mamba-root/envs/py315  (isolated; touches no pin)
```

Single-owner discipline: one chart runtime owner, one analytics owner, one chart
definition type. No second analytics backend. No dual-render fallback.

## Tech stack

React 19.3.0, antd 6.6.5, Umi Max 4.7.20 (webpack `chainGroups`, so cache groups are
config-driven), TanStack Router/Query, Vitest, pnpm 12.5.1 catalog; FastAPI + ClickHouse +
`structlog` on the API; mamba 2.5.0 + uv for the Python track.

## Baseline / authority refs

`docs/superpowers/specs/2026-10-10-antv-analytics-python315-design.md` §1 is the read
baseline and must be re-read if any of it is contradicted by the working tree.

Authoritative contracts that constrain this work:

- `AGENTS.md` — product/data invariants, delivery pipeline, toolchain pins.
- `docs/dev/database-core-contract.md` — `public_id`/`internal_id`, unreleased-record
  exclusion, mandatory negative leakage tests, no site-variant inference.
- `.ai-memory/LOCAL-RUN-ENV.md` — how this host actually runs things.
- `docs/dev/mamba-validation-environment.md` — the isolated-env and PostgreSQL-fixture
  pattern reused by track C.
- `plan.md:527-536,606-608` — `@soymutdb/charts` is the designated sole chart entry.

## Compatibility boundary

Summarised here; full statement in the design spec §7. Non-negotiables: existing
`/track.gif` GET+POST and its `event` pattern; `sm_sid` name/attributes/lifetime; DNT
handling; the trusted-proxy rule for `X-Forwarded-For`; `web_vitals` and its TTL; all
seven existing `/admin/analytics/summary` fields; `categoryBarChart`/`trendAreaChart`/
`ChartFigure` names, props and `data-testid` hooks; `/api/v1/stats` and the public
`/analytics` content page; `/admin/dashboard-stats` and `/admin/dashboard-series`; every
production Python pin. No production data is deleted. No database identity changes.

## Verification

Machine-adapted; do not run these verbatim without the `LOCAL-RUN-ENV.md` exports.

```bash
export PATH="/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH"
export GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2
```

```bash
# Frontend (order matches scripts/verify-frontend-artifacts.sh)
pnpm turbo run test
pnpm turbo run lint
pnpm turbo run typecheck
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
python3 scripts/check_page_registry.py
python3 scripts/check_web_query_keys.py
python3 scripts/check_admin_content_architecture.py
python3 scripts/check_visible_i18n.py
node scripts/check_visible_i18n_react.mjs
python3 -m pytest infra/clickhouse/test_schema_contract.py -q
```

Full single-source frontend gate when a slice touches bundler config or the lockfile:

```bash
bash scripts/verify-frontend-artifacts.sh
```

Backend without Docker, per `docs/dev/mamba-validation-environment.md`:

```bash
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_testfixtures
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_testfixtures
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  bash scripts/verify-backend-tests.sh
```

Note from `LOCAL-RUN-ENV.md` §8: no Docker (so testcontainers and ClickHouse integration
are SKIPPED, never passed), no Redis server (Celery worker tests will not run), `uv` under
`~/.local/share/uv/tools` is read-only on this host, `max dev` hangs in `Preparing...` so
use `max build`, and `/tmp` does not survive between bash calls.

---

## Track A — ECharts → AntV

Write scope: `packages/charts/**`, `apps/web/config/config.ts`, `apps/web/src/components/charts/**`,
`apps/web/src/lib/use-echarts.ts`, `apps/web/src/routes/analytics.tsx`,
`apps/web/src/routes/genes/$geneId.tsx`, `apps/web/src/routes/tools/{enrichment,exppattern}.tsx`,
`apps/admin/src/components/charts/**`, `apps/admin/src/routes/index.tsx`,
`apps/admin/src/routes/settings.tsx`, `apps/{web,admin}/package.json`,
`packages/charts/package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`,
`dependency-governance.json`, `packages/i18n-core/src/locales/{en,zh}/common.json`.

### Task A1 — Install, measure, React-19 smoke (gates everything)

- **Files**: `pnpm-workspace.yaml` (catalog: add `@ant-design/plots` exact pin, **remove
  nothing**), `pnpm-lock.yaml`, `apps/web/config/config.ts:146-151`,
  `dependency-governance.json` if a new check is needed.
- **Change**: add the catalog entry. Repoint the `charts` cache-group test from
  `(?:echarts|zrender)` to the new package names so the required group still emits.
  Do not touch any component.
- **Before installing**, record what the advisory check found: npm advisory feed, GitHub
  Security Advisories, AntV's own announcement. The design states no safe-version ceiling
  and this task must not invent one.
- **Regression**: none needed yet; this task only proves feasibility.
- **Proof**: `pnpm why @ant-design/plots`; a Vitest render that mounts a real
  `@ant-design/plots` component under React 19.3.0 in jsdom (peer metadata says
  `react >=16.8.4` with no upstream React 19 evidence — this is the runtime check that
  replaces it); then `bash scripts/check-bundle-size.sh apps/web/dist/external/assets` and
  **record the `charts.*.js` gzip total against the 370 KB cap**.
- **Stop condition (hard)**: if the `charts` group exceeds 370 KB gzip, **stop and return
  to design**. Do not raise `CHARTS_MAX_KB` without an explicit decision (design §8 D3).

### Task A2 — Facade runtime + migrate `packages/charts`

- **Files**: `packages/charts/src/{ChartFigure.tsx,definitions.ts,index.ts}`, new
  `packages/charts/src/{ChartCanvas.tsx,theme.ts}`, `packages/charts/package.json`
  (swap `echarts` for `@ant-design/plots`), `packages/charts/src/ChartFigure.test.ts`.
- **Change**: one runtime wrapper owning lazy engine import, init on a measured element,
  `ResizeObserver` resize, dispose on unmount and theme change, CSS-variable → engine theme
  bridge, reduced-motion/animation-intensity input, and a serializable `ChartDefinition`
  that no longer aliases `EChartsOption`.
- **Invariant**: `ChartFigure` keeps `role="img"` + `aria-label` + `aria-describedby`, the
  `<details>` exact-value table, and the `chart-empty` / `chart-unavailable` /
  `chart-values` test ids. `trendAreaChart` must keep a **category** x axis
  (`definitions.ts:86`) — the quantitative-scale ISO-date crash documented at
  `docs/dev/vue-parity/README.md:22` must not be reintroduced.
- **Regression**: extend `ChartFigure.test.ts` for dispose-on-unmount, resize, theme swap,
  engine-init failure → `chart-unavailable`, and category-axis trend rendering.
- **Proof**: `pnpm --filter @soymutdb/charts test`, `lint`, `typecheck`.

### Task A3 — Admin 3 charts

- **Files**: `apps/admin/src/components/charts/{import-throughput,query-latency,storage-growth}.tsx`,
  `apps/admin/package.json` (add `@soymutdb/charts`, drop `echarts`).
- **Change**: rewrite the three options onto the facade. Replace the two static
  `import * as echarts from "echarts"` top-level imports (`import-throughput.tsx:2`,
  `storage-growth.tsx:2`) and the one engine-specific API in the set
  (`storage-growth.tsx:83` `echarts.graphic.LinearGradient`) with an explicit theme-bridge
  gradient.
- **Invariant**: `apps/admin/src/routes/index.tsx:156-160` call sites and their
  `<Suspense fallback={<ChartLoading />}>` stay unchanged; the `role="img"` /
  `aria-label` / antd `Empty` empty-state contract stays.
- **Regression**: admin dashboard test asserts charts mount with data, render the empty
  state for empty data, and do not throw on dark-mode toggle.
- **Proof**: `pnpm --filter @soymutdb/admin test lint typecheck`.

### Task A4 — Web 5 charts

- **Files**: `apps/web/src/components/charts/{variant-type-chart,chromosome-density-chart,impact-distribution,release-trend,expression-bar-chart}.tsx`,
  `apps/web/src/routes/analytics.tsx`, `apps/web/src/routes/genes/$geneId.tsx`.
- **Change**: rewrite options onto the facade; delete `apps/web/src/lib/use-echarts.ts`
  and its imports.
- **Invariant**: the existing native boundaries at `analytics.tsx:15-18,161-170` and
  `$geneId.tsx:54,459-461` — `React.lazy` + `<React.Suspense fallback={<Skeleton/>}>` —
  are the mechanism; nothing new is introduced. `use-echarts.ts:164-182` documented a real
  engine crash when a series goes empty↔populated; reproduce that as an explicit state.
- **Regression**: `/analytics` renders 4 charts with real data, 4 empty states with no
  data, and one degraded chart falls back to its exact-value table with **no** page error
  (this is the `docs/dev/vue-parity/README.md:72` shape).
- **Proof**: `pnpm --filter @soymutdb/web test lint typecheck`; bundle gate.

### Task A5 — Web tool charts

- **Files**: `apps/web/src/routes/tools/enrichment.tsx`,
  `apps/web/src/routes/tools/exppattern.tsx`.
- **Change**: move the chart definitions out of the route module into the lazy facade so
  the route chunk stops carrying chart code; migrate the heatmap and the enrichment
  dual-view (`view`) rendering onto the facade.
- **Regression**: both tools render, switch views, and degrade to the value table without a
  page error.
- **Proof**: `pnpm --filter @soymutdb/web test lint typecheck`; bundle gate.

### Task A6 — Remove ECharts

- **Files**: delete `apps/web/src/lib/use-echarts.ts`;
  `pnpm-workspace.yaml:25` (drop `echarts: 5.5.1`);
  `apps/{web,admin}/package.json` (drop `echarts`);
  `packages/charts/package.json`; `pnpm-lock.yaml`;
  `apps/admin/src/routes/settings.tsx:981-986` (remove the orphan `ECharts CDN URL` field
  and `id="cdn-echarts"`); `packages/i18n-core/src/locales/{en,zh}/common.json`
  (`admin.settings.echartsUrl`, `admin.settings.placeholderEchartsUrl`).
- **Repair track**: every remaining `echarts`/`EChartsOption`/`useECharts` reference must
  be gone — re-grep the workspace and read `docs/dev/project-status.md` for stale mentions.
- **Retirement track**: this is the retirement point. There is no ECharts runtime, no CDN
  setting and no helper left in the tree.
- **Regression**: i18n key-parity gate (`pnpm --filter @soymutdb/i18n-core check:locale-keys`)
  proves the removed keys are gone from both locales.
- **Proof**: grep returns zero ECharts references; `pnpm install` succeeds; full
  `bash scripts/verify-frontend-artifacts.sh` passes; bundle gate shows the `charts` group
  present and within budget.

### Task A7 — Budget and native-lazy regression

- **Files**: none (verification-only slice; fix whatever it finds in the owning task's scope).
- **Proof**: `bash scripts/check-bundle-size.sh apps/web/dist/external/assets` — record
  `charts.*.js` gzip total, per-asset totals, and the `index.html` entry total; confirm no
  static top-level engine import remains in any chart module; browser check that a chart
  renders, resizes on viewport change, disposes on route change, and honours reduced motion.

---

## Track B — PV/UV/referrer loop

Write scope: `apps/api/app/api/v1/analytics.py`,
`apps/api/app/services/analytics_service.py`, `apps/api/tests/**`,
`packages/api-client/src/admin-analytics.ts`, `packages/api-client/src/admin-analytics.test.ts`,
`packages/api-client/openapi.json`, `infra/clickhouse/init.sql`,
`infra/clickhouse/upgrade_*.sql`, `infra/clickhouse/test_schema_contract.py`,
`apps/web/src/lib/analytics.ts` (new), `apps/web/src/react-app.tsx`,
`apps/admin/src/App.tsx`, `apps/admin/src/routes/analytics/visitors.tsx` (new),
`apps/admin/src/components/admin-shell.tsx`, `apps/web/src/router/routes.ts`,
`packages/i18n-core/src/locales/{en,zh}/common.json`.

**Gate superseded 2026-10-11** by the user's `analytics_privacy_policy` choice — see
"Approval record" above. D1, D4 and the D2 direction are answered, so **B1 may start** under
the approval's constraints. **D5 is explicitly NOT approved: B2 must not start**, and B1 must
not infer the variant from anything a client can guess.

### Task B1 — Server-side normalisation and allowlist

- **Files**: `apps/api/app/api/v1/analytics.py`,
  `apps/api/app/services/analytics_service.py`, `apps/api/tests/test_analytics_*.py`.
- **Change — the regex from the earlier draft of this task is DEPRECATED and MUST NOT be
  implemented as written.** `^/[a-z0-9]*(?:/[a-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)?)*$` has
  counterexamples and **42 mutants**: it admits numeric-only segments and arbitrary digit
  runs, so `/12345` (internal numeric id), `/0/0/0` (coordinate-like) and other leak-shaped
  paths pass the filter. **Deprecating it does not authorise a forbidden-digit character
  class** — that fix was rejected. Approved direction: a **finite canonical route-template
  allowlist** (fixed templates only) + **raw path-parameter normalisation** into the canonical
  template + **front/back drift verification** that diffs what the portal can emit against
  the server allowlist. Then, unchanged in intent: a hard length cap with non-match → a
  counted `"/other"` bucket; a pure referrer categoriser (category into `source`,
  `scheme://host[:port]` only into `referrer`); **stop populating `path`** and delete its
  query parameter from the collector signature rather than leaving an unused optional field;
  keep the `sm_sid` and trusted-proxy logic byte-identical.
- **Change (approval constraints, 2026-10-11)**: raw `q` / `ref` / `source` / `path`
  client-supplied text is **never stored and never echoed back** — normalise server-side or
  into a fixed enum, and store the server-resolved route template. A parameter kept for
  **request** backward compatibility only must not store its raw value. `site` is **not**
  taken from the client as a variant decision — it is not a permission boundary, the API
  must not decide the variant from a guessable host/IP/UA, **no `site` column and no new
  column is written** (D5 not approved) — and **the internal build never enters the anonymous
  producer**.
- **Change (cookie ordering)**: **DNT is honoured before any `Set-Cookie` is emitted.**
  Existing historical cookies are **not** deleted and no store is cleared. The cookie-based
  figure stays labelled **session count, not people**. IP and other extra stable identifiers
  are assessed against the minimal-collection goal before adoption; until then **do not
  claim the measurement scope has changed**.
- **Invariant**: `event` still accepts `pageview|click|search|widget|performance`; `perf.ts`
  and `web_vitals` untouched.
- **Negative leakage tests** (the mandatory core of this task): a pageview whose `page` is
  `Glyma.01G000100`, an internal numeric id, a numeric-only path segment, a dotted release
  slug, `..`, a full URL, a
  query string and a fragment must **not** reach a stored row or the admin response; a
  `Referer` containing a gene URL must yield only its category and origin; a client-supplied
  `site` value must never decide the variant or be persisted as one; DNT must suppress
  persistence **and no tracking cookie may be set**; raw `q` / `ref` / `source` / `path` must
  be absent from stored rows, the admin response and any client-visible log; the summary
  response must be private / `no-store`; a working-but-empty store must report as available
  with zeros, **never as zero traffic**; a non-administrator
  must be refused with no analytics payload in the body.
- **Proof**: `cd apps/api && .venv/bin/python -m pytest tests -q` (or the isolated
  `SOYMUTDB_TEST_DATABASE_URL` form), recording pass/fail counts.

### Task B2 — Additive schema change

- **Files**: `infra/clickhouse/init.sql`, `infra/clickhouse/upgrade_*.sql`,
  `infra/clickhouse/test_schema_contract.py`.
- **Change**: `ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS site LowCardinality(String) DEFAULT ''`.
  No `ORDER BY` change, no new table, no materialised view, no history rewrite.
- **Explicitly out of scope**: the parts-per-INSERT pressure and the
  `ORDER BY (event_type, toDate(timestamp), session_id)` recommendation at
  `docs/dev/performance-optimization-plan.md:416-482` are a **pre-existing, separately
  planned** item.
- **Regression**: a DDL guard asserting `site` is declared `LowCardinality(String)` in both
  DDL files, next to the existing timestamp/TTL guards at
  `test_schema_contract.py:285-313`.
- **Proof**: `python3 -m pytest infra/clickhouse/test_schema_contract.py -q`.

### Task B3 — `available` field and client contract

- **Files**: `apps/api/app/services/analytics_service.py`,
  `packages/api-client/src/admin-analytics.ts`,
  `packages/api-client/src/admin-analytics.test.ts`, `packages/api-client/openapi.json`.
- **Change**: add an **additive** `available: bool` to `get_summary`. Today
  `analytics_service.py:248-258` logs and returns zeros on any exception, which makes
  "ClickHouse is down" indistinguishable from "no traffic". Existing consumers ignore
  unknown keys, so this is backward compatible; the endpoint is in the committed OpenAPI
  snapshot, so regenerate/merge only these fields and record any remaining snapshot drift
  rather than claiming global parity.
- **Invariant**: all seven existing fields keep their names and types.
- **Regression**: client test for `available: false` with zeroed counters; client test that
  the seven legacy fields still parse.
- **Proof**: `pnpm --filter @soymutdb/api-client test`; the OpenAPI client contract gate.

### Task B4 — Portal producer

- **Files**: new `apps/web/src/lib/analytics.ts`, `apps/web/src/react-app.tsx:105-114`.
- **Change**: PROD-only, dynamically imported (never top-level), route-change `pageview` via
  the existing `GET /track.gif` with `event=pageview&page=<template>&site=<build-time
  variant>`. Honours `navigator.doNotTrack`. Sends no query string, no hash, no title, no
  self-supplied referrer, no cookie.
  - **SUPERSEDED 2026-10-11** — the `site=<build-time variant>` parameter in the line above is
    **no longer the accepted design**. Per the user's `analytics_privacy_policy` choice (D5,
    **NOT approved**), there is **no `site` column and no new column at all**, **B2 does not
    start**, and a client-supplied `site` value must never decide the site variant or be
    persisted as one. The internal build does not enter the anonymous producer; the variant is
    selected explicitly at build/runtime, never inferred from host, IP, cookie or user agent.
    This note annotates the old plan in place and **does not rewrite history** — the rest of
    Task B4 below stands, subject to the D5 decision. Interim state of B4 itself:
    **NOT DONE** (see the 2026-10-12 interim acceptance ledger in
    `docs/aegis/work/2026-10-10-antv-analytics-python315/20-checkpoint.md`).
- **Invariant**: do not disturb the existing `perf.ts` wiring in `react-app.tsx`.
- **Regression**: jsdom test asserting one beacon per route change, none when DNT is on,
  and that no query/hash ever appears in the emitted request.
- **Proof**: `pnpm --filter @soymutdb/web test`.

### Task B5 — Admin visitors route

- **Files**: `apps/admin/src/App.tsx`, new `apps/admin/src/routes/analytics/visitors.tsx`,
  `apps/admin/src/components/admin-shell.tsx`,
  `packages/i18n-core/src/locales/{en,zh}/common.json`.
- **Change**: a lazy admin route consuming `getAdminAnalyticsSummary` — its **first** React
  consumer — rendering PV, UV, daily trend, route-template ranking and referrer source mix.
  Charts come from the Track A facade, so B5 depends on A2 at minimum.
- **Invariant**: `React.lazy` + the existing `withSuspense()` helper (`App.tsx:69-75`);
  antd `Skeleton` while loading, `Empty` when genuinely zero, `Alert` when `available` is
  false. UV must be labelled "distinct sessions (365-day first-party cookie)", never
  "unique visitors". `top_searches` is labelled not collected.
- **Regression**: route test for loading → populated, zero-data → `Empty`, failure → `Alert`,
  and that the UV label contains the cookie caveat.
- **Proof**: `pnpm --filter @soymutdb/admin test lint typecheck`;
  `python3 scripts/check_admin_content_architecture.py`.

### Task B6 — Reconcile the settings copy

- **Files**: `apps/admin/src/routes/analytics-settings.tsx`,
  `packages/i18n-core/src/locales/{en,zh}/common.json`.
- **Change**: make the console internally consistent once first-party is the source for
  PV/UV/referrer. Line 151 currently inverts that. **Blocked on design §8 D2** for the exact
  wording — do not improvise operator-facing copy.
- **Regression**: i18n locale-key parity gate; the page must still never call the backend.
- **Proof**: `pnpm --filter @soymutdb/i18n-core check:locale-keys`;
  `node scripts/check_visible_i18n_react.mjs`.

---

## Track C — Python 3.15 isolated verification

Write scope: `.mamba-root/envs/py315/**`, `.mamba-root/pkgs/**`,
`docs/dev/mamba-python315-validation.md` (new, single evidence page).
**No production pin file is in scope for this track.**

### Track C addendum (user-supplied upgrade checklist, added after C1/C2 ran)

- **Compatibility checklist added to this track**, verified against the official
  <https://www.python.org/downloads/release/python-3150/> (HTTP 200, release date
  Oct. 9, 2026) and against the interpreter itself:
  1. `-X warn_default_encoding` regression check plus an honest `DeprecationWarning`
     census on every test run. **No mechanical third-party deprecation fixes** and
     **silencing is never reported as a pass** — note that `apps/api/pyproject.toml`
     already sets `filterwarnings = ["ignore::DeprecationWarning", …]`, so an api run
     must override it before its warning count means anything.
  2. Removed stdlib surface probed with `importlib.util.find_spec`: `sre_*`,
     `cgi`/`cgitb`, and the rest of the 3.15 removal list, plus the legacy `sqlite3`
     attributes (`version`, `version_info`, `enable_shared_cache`).
  3. **"Current stage changes no production pin" is a property of this phase, not the
     end state of the work.** The overall goal remains the core migration once the
     evidence is sufficient; zero pins is not the permanent terminal condition.
- **Python native lazy imports (PEP 810) are a phase-2 candidate only** — they are
  **not** merged into this compatibility track, and they are **not** enabled globally.
  `sentinel` (PEP 661), `frozendict` (PEP 814), the experimental JIT and PEP 799
  profiling form the rest of that phase-2 list and must be checked against official
  sources first. This changes nothing about the already-approved **frontend** native
  React lazy/Suspense scope, which stays exactly as approved in Track A/D.
- **No LLVM is installed on this host** and none will be installed to probe the JIT.
- Evidence lives in `docs/dev/mamba-python315-validation.md`.

### Task C1 — Create the interpreter only

- **Files/dirs**: `.mamba-root/envs/py315`, `.mamba-root/pkgs`.
- **Change**: `MAMBA_ROOT_PREFIX=$PWD/.mamba-root CONDA_PKGS_DIRS=$PWD/.mamba-root/pkgs
  mamba create -p $PWD/.mamba-root/envs/py315 --override-channels -c conda-forge python=3.15.0 -y`.
  Pin the **regular CPython build** (the `cp315` build string), never the free-threaded
  `cp315t` build — not approved. Record the resolved interpreter path and version.
- **Invariant**: `mamba env list` output unchanged for the user's environments; `webdb`
  (3.14 + PostgreSQL server) untouched.
- **Proof**: `.mamba-root/envs/py315/bin/python -V` reports 3.15.x and is not free-threaded.

### Task C2 — Core tier: jobs-py, api, mcp-server

- **Files**: none outside the env.
- **Change**: install each project's pinned dependencies with uv against the 3.15
  interpreter (`uv pip install --python .mamba-root/envs/py315/bin/python …`). mamba supplies
  the interpreter; uv/pip supplies the packages — installing project dependencies through
  conda would create a second invisible resolution path. Do **not** regenerate any
  `uv.lock`; resolve from the existing pins.
- **Order**: `packages/jobs-py` → `apps/api` → `apps/mcp-server`.
- **Proof**: `packages/jobs-py` pytest; `apps/mcp-server` pytest; `apps/api` pytest for the
  layers reachable without Docker (scratch PostgreSQL fixture DB via the documented
  `postgres16` pattern). Record exact pass/fail counts and the interpreter version.

### Task C3 — Worker tier, biology last

- **Files**: none outside the env.
- **Change**: install `apps/worker` against 3.15 and record what actually resolves. Treat
  the metadata as unproven: `pyfaidx` (pure wheel) and `igraph`/`leidenalg` (abi3) are
  expected to be fine; `polars` native runtime wheels and `cyvcf2` (no 3.15 wheel seen,
  would need an sdist/Cython build) are the genuine unknowns. Run the **non-biology** worker
  tests (job contract, export, Celery) on 3.15; biology stays on 3.14.
- **Honest stop**: if the biology stack does not resolve, the result is **blocked with
  evidence**, not a failure and not a pin change. Note the earlier "no cp315 wheels at all"
  conclusion was wrong and must not be repeated.
- **Proof**: recorded resolution log + non-biology worker test counts.

### Task C4 — Evidence page, zero pin changes

- **Files**: new `docs/dev/mamba-python315-validation.md`.
- **Change**: one page recording the interpreter build, what resolved, what did not, exact
  test counts, and the explicit statement that no production pin moved.
- **Explicitly forbidden in this track**: `requires-python`, `ruff target-version`, any
  `uv.lock`, `.cnb.yml` images, `.cnb/env/Dockerfile.frontend`, `infra/docker/Dockerfile.*`,
  `apps/mcp-server/Dockerfile`, `scripts/ci-job-steps.sh`,
  `scripts/test_ci_job_contracts.py`. The last one hardcodes `PYTHON_VERSION = "3.14"` and
  asserts it in several places; a partial edit breaks the delivery contract for no benefit.
- **Promotion criteria** (a separate, separately-approved slice): a 3.15 `uv.lock`
  re-resolve for every project; the biology stack either shipping 3.15 wheels or moving to
  conda-forge; `.cnb.yml` image bumps re-validated against the recorded glibc constraint
  (`.cnb.yml:150-151`: node 26.10.0 is bookworm/glibc 2.36 while python 3.14 needs 2.38, so
  a 3.15 Debian base is a strictly newer baseline that must be re-verified); all three
  `Dockerfile` families bumped together.
- **Proof**: `git diff --name-only` shows no pin file touched. The goal is **not** to
  permanently end 3.14 — this slice only produces evidence.

---

## Ordering

```
C1 ──▶ C2 ──▶ C3 ──▶ C4                       (independent of A and B)

A1 ──▶ A2 ──┬─▶ A3 ──┐
            ├─▶ A4 ──┼─▶ A6 ──▶ A7
            └─▶ A5 ──┘

B1 ──▶ B2   (B1/B2 parallel; both before B3)
B3 ──▶ B4
A2 ──▶ B5 ──▶ B6
```

A1 gates A2–A5 because it measures the budget. B5 depends on A2 (it needs the chart
facade). B6 is last and is blocked on decision D2. Track C is fully independent.

## Risks and stop conditions

| Stop | Trigger | Action |
| --- | --- | --- |
| Chart budget | A1 measures `charts.*.js` > 370 KB gzip | stop, return to design, escalate D3 |
| Advisory | install-time advisory check finds an issue | stop, do not install, report |
| React 19 | A1 runtime smoke fails under 19.3.0 | stop, report; do not force |
| Pin drift | any Track C task is about to touch a production pin | refuse; that is a separate slice |
| Data | any task proposes deleting rows or changing a database identity | refuse; out of scope |
| D1 | GoatCounter turns out to be still wanted | stop Track B; the design is superseded |
| Analytics privacy | a negative leakage test cannot be written to pass honestly | stop and report the gap |
| Baseline ≠ budget | the 2026-10-11 pre-AntV web build (child `00f0b…`, **real exit 0, 24.92 s**) is read as the chart measurement | refuse; it is a **baseline only**, the AntV gzip sample still does not exist and D3 stays open |

## Retirement

- `apps/web/src/lib/use-echarts.ts` retires in A4/A6.
- `echarts` / `zrender` retire from the catalog, three `package.json` files and the lockfile
  in A6.
- The orphan `ECharts CDN URL` admin setting retires in A6 (last ECharts reference).
- The dormant-first-party-analytics owner is **reactivated**, not replaced. Nothing is
  retired on the analytics side; what retires is the console copy that misdescribes it (B6).
- `packages/charts` is **not** deleted — it is promoted from a zero-consumer package to the
  designated single chart owner.

## Self-review

Approved-scope coverage: all four approved directions have ordered tasks with named files.
No placeholders. Owner consistency: one chart owner, one analytics owner, one definition
type; the dual-render fallback is explicitly forbidden. Minimum change: additive schema and
additive response field; one new shared runtime owner; no drops, no reorders, no rewrites.
Compatibility: restated above and in design §7. Verification: machine-adapted commands
with an explicit not-covered rule. Conditional triggers: budget, advisory, React 19, pin
drift, data deletion, D1, privacy — each has a named stop. Retirement: ECharts only, in one
task, with its own gate. Open decisions D1–D5 stay in the design spec and gate the tasks
that depend on them; they are not assumed away. **Superseded 2026-10-11** by the "Approval
record" above: D1, D4 and the D2 direction are answered, **D5 is not approved** (B2 does not
start), D3 stays open, and task B1's original route-template regex is deprecated in place.
The plan is **NOT DONE**.

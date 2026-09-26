# e2e — Online Smoke Test (deployed gh-pages site)

Automated smoke tests for the **live** SoyMutDB site
`https://caoronglin.github.io/soymutdb-next/` (GitHub Pages). Runs nightly,
manually, and automatically after every successful deployment
(`.github/workflows/e2e-smoke.yml`).

`e2e/` is an **independent npm package** — it deliberately sits outside the
pnpm workspace so the root `package.json` / `pnpm-lock.yaml` stay untouched.

## What is tested (assertion contract)

### 1. Resource loading (homepage)
- **Zero** responses with HTTP status >= 400 (strict — a missing favicon is
  a bug too, not something to filter out).
- **Zero** failed same-origin `script`/`stylesheet` requests
  (`page.on('requestfailed')`).
- At least one `/assets/*.js` bundle answered `200` (key-resource check).

### 2. Route rendering (parameterized over 10 key routes)
`/`, `/search`, `/genes`, `/variants`, `/blast`, `/news`, `/browser`,
`/about`, `/help`, `/tools`

Per route: `goto → networkidle` then assert
- `body` text is non-empty,
- no `"Not Found"` (TanStack Router not-found state),
- no `"Unexpected application error"` (default error boundary text),
- at least one `h1`/`h2` (homepage is special-cased: `h1` **or** ≥200 chars
  of body text, so hero-only redesigns don't false-positive),
- page `title` is collected into the JSON report.

### 3. Script health (same routes)
- **Zero** `pageerror` events.
- **Zero** `console.error` messages, except the tolerated classes below.

**Tolerated console errors (recorded in the report, not asserted):** anything
matching `404 | net::ERR_* | Failed to load resource | Failed to fetch |
NetworkError | ERR_ABORTED | CSP-frame-ancestors-meta warning |
EventSource-MIME-abort | CSP violation`. These are network/environment or
browser-security-layer noise:

- Placeholder API origin (`https://api.example.com`) — resolves via
  example.com wildcard DNS and answers `text/html`, so `/blast`'s SSE stream
  aborts with an EventSource MIME error (the app falls back to polling
  gracefully). That is a deployment configuration gap, not a script bug.
- `/browser`'s JBrowse iframe: `VITE_JBROWSE_URL` is unset at build time, so
  the app defaults to `http://localhost:5175`, which `frame-src` blocks → CSP
  violation message (browser security layer; the page itself renders).
- Chrome's "frame-ancestors is ignored via <meta>" message fires on every
  page (SSG CSP meta carries `frame-ancestors`).

All tolerated entries land in `test-results/smoke-report.json` so they stay
visible for review. Any *other* `console.error` is treated as a real
regression.

## Outputs

- `test-results/smoke-report.json` — always written, machine-readable summary
  (per-route title/body-length/document status, all collected errors).
- `playwright-report/` + `test-results/` — uploaded as CI artifacts
  (`e2e-smoke-failure`) when the suite fails.

## Triggering

| Trigger | When |
| --- | --- |
| `schedule` | nightly 02:00 UTC |
| `workflow_dispatch` | manual — Actions tab → "E2E Smoke (online)" → Run workflow |
| `workflow_run` | after "Deploy Web to Pages" completes **successfully** (the `if` guard skips failed deployments) |

## Running locally

```bash
cd e2e
npm install                 # installs @playwright/test + playwright (^1.62)
npx playwright install chromium
npx playwright test --list  # show collected tests
npx playwright test         # run against the live site
```

Point at any environment (staging, local dist preview):

```bash
SMOKE_BASE_URL=http://localhost:4173 npx playwright test
```

## Demo vs. Production E2E separation

There are **two independent browser suites**; do not conflate them:

| Suite | Config | Target | Gate semantics |
| --- | --- | --- | --- |
| **Demo smoke** | `playwright.config.ts` / `playwright-public.config.ts` | gh-pages **demo** site | placeholder API 404s / JBrowse CSP noise are *tolerated* and only recorded |
| **Production gate** | `playwright-production.config.ts` / `production-gate.spec.ts` | real **production/staging** release | API 404/405, demo fixtures, placeholder origins, and fallback states are **hard failures** |

The public demo site legitimately carries fixture data (`SMDB-00001` pages) and
stubs (no real API), so the demo smoke only asserts rendering/script health. The
production gate targets a deployment that must serve **real** release data.

## Production E2E gate

Target a real release deployment (production or staging) and run the strict
gate. It asserts:

- key release routes are free of `SMDB-00001` / `Demo fixture` /
  `demonstration data` / `example.com` / `localhost` / `change-me`;
- no static-asset HTTP >= 400 and **no API 404/405** (a 404/405 means the SPA is
  in a fallback state, not serving release data);
- at least one API data endpoint answers 2xx; the demo sample route
  `/samples/SMDB-00001.html` must be a 404;
- the `/browser` JBrowse frame loads (not CSP-blocked) and the Admin console
  login page is reachable and renders.

```bash
PRODUCTION_BASE_URL=https://soymutdb.org \
  npx playwright test -c playwright-production.config.ts

# discover / validate the suite without a browser
PRODUCTION_BASE_URL=https://soymutdb.org \
  npx playwright test -c playwright-production.config.ts --list
```

`PRODUCTION_BASE_URL` is required — a missing value fails the whole gate rather
than silently testing the wrong environment.

## Admin production-artifact gate

This isolated smoke suite serves the already-built `apps/admin/dist` output
from a minimal static server. It does not run a Vite development server and
does not submit the login form, so it catches emitted-bundle regressions
without requiring an API or test credentials.

From the repository root, first create or refresh the production artifact,
then run the gate:

```bash
pnpm --dir apps/admin build
pnpm --dir e2e exec playwright test -c playwright-admin-production.config.ts
```

The gate requires `/login` to retain the `SoyMutDB Admin` title, render a
visible username field, password field, and `Sign in` button, accept typed
credentials locally, and produce no Playwright `pageerror` events. Its server
listens on `127.0.0.1:4174`, serves only `apps/admin/dist`, and uses an SPA
fallback for `/login`. Failure artifacts are written to
`e2e/test-results-admin-production/` and
`e2e/playwright-report-admin-production/`.

## Admin console authenticated E2E (deployed stack)

`admin-production-login.spec.ts` only proves the emitted bundle boots at
`/login`. `admin-console.spec.ts` goes past the form on a **deployed** console:
an anonymous deep link must bounce to `/login?redirect=…`, then
dashboard/imports/settings/news/content must mount in the console chrome, let
their data query settle, and raise no unexpected console error or pageerror.

```bash
cd e2e
ADMIN_BASE_URL=https://admin.soymutdb.test/ \
ADMIN_STORAGE_STATE=/secure/admin-storage-state.json \
  npx playwright test -c playwright-admin-console.config.ts
```

Prerequisites: a deployed console with its API/CORS/CSP configured and, for the
authenticated routes, a Playwright storage state captured from a real sign-in
(this suite never reads or fabricates credentials):

```bash
npx playwright codegen --save-storage=admin-storage-state.json "$ADMIN_BASE_URL/login"
```

A missing `ADMIN_BASE_URL` skips the redirect test; a missing
`ADMIN_STORAGE_STATE` skips the authenticated routes. No value ever silently
tests the wrong environment.

## Portal `/browser` embed regression (deployed stack)

`portal-browser-embed.spec.ts` gates the public embed contract: the `/browser`
iframe carries `portalOrigin`, the postMessage bridge reaches its ready state
(`[data-testid="browser-ready"]`), and no URL in the embed — portal location,
iframe `src`, shell frame URL or new-tab link — exposes a private persistence
identifier or an unexpected bridge parameter.

```bash
PORTAL_BASE_URL=https://soymutdb.test/ \
  npx playwright test -c playwright-portal-embed.config.ts
```

Prerequisites: a deployed portal built with `VITE_JBROWSE_BASE_URL` and a CSP
`frame-src` allowing the shell, with `/browser` enabled by its feature gate.
Unset `PORTAL_BASE_URL` (and `SMOKE_BASE_URL`) skips the suite.

Local static-server run (no network dependency) — **serve dist under the
`/soymutdb-next` prefix**: the build bakes that base into dynamic-import
chunk paths, so mounting at the root would produce fake "module script MIME"
errors. Use a fallback-capable server (unknown paths → `index.html`, real
404 for missing `/assets/*`), e.g. the repo-agnostic one at
`/tmp/opencode/static-server.mjs` (dev-only helper, not part of the repo):

```bash
node /tmp/opencode/static-server.mjs ../apps/web/dist 4188 /soymutdb-next &
SMOKE_BASE_URL=http://localhost:4188/soymutdb-next/ npx playwright test
```

Slow-network / CN-network tips:

- `npm install` follows your `~/.npmrc` (npmmirror if configured) — fine.
- Playwright browser download: if the default CDN is unreachable,
  `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/ npx playwright install chromium`
- The suite is already hardened: `workers=1`, `retries=1`, 60 s per-test
  timeout. Transient connection resets are retried once before failing.

## Entity detail E2E (deployed stack)

`entity-detail.spec.ts` gates the three entity detail views against a deployed
portal: a mutant addressed by its `public_id`, a variant (`/compare?ids=…`) with
assembly/release provenance rows, and a gene with assembly-scoped coordinates and
a JBrowse deep link. Each page must render a stable, reloadable URL and a stable
link, with no unexpected console error or pageerror; a mutant URL must never
carry a private persistence key.

```bash
PORTAL_BASE_URL=https://soymutdb.test/ \
  npx playwright test -c playwright-entity-detail.config.ts

# discover / validate the suite without a browser
npx playwright test -c playwright-entity-detail.config.ts --list
```

Entity identifiers are derived from the target's own lists; pin them with
`ENTITY_MUTANT_PUBLIC_ID`, `ENTITY_VARIANT_ID` and `ENTITY_GENE_ID` when a list
is not representative. A missing `PORTAL_BASE_URL`/`SMOKE_BASE_URL` skips every
test, and an empty list skips the dependent test instead of failing. The suite
never invents identifiers and never reads credentials.

## Internal site variant E2E (deployed stack)

The internal artifact is served at the origin root `/`, while the public
artifact lives under `/soymutdb-next` (running the public suite against internal
fails with `No route for /soymutdb-next/login`). `internal-site.spec.ts` proves
the boundary: the internal document is served from `/`, carries the internal
`noindex, nofollow, noarchive` robots meta, requests only root-relative
`/assets/*` bundles (never the public sub-path), publishes a `Disallow: /`
robots.txt, reports the `internal` site variant, and serves its login form at
`/login`. It never fills or submits credentials.

```bash
INTERNAL_BASE_URL=https://internal.soymutdb.test/ \
  npx playwright test -c playwright-internal.config.ts

# discover / validate the suite without a browser
npx playwright test -c playwright-internal.config.ts --list
```

Unset `INTERNAL_BASE_URL` skips every test. Set `PUBLIC_BASE_URL` (or
`PORTAL_BASE_URL`/`SMOKE_BASE_URL`) as well to additionally assert the internal
base is not the public origin + base path.

## JBrowse 2 deep-link fixture (offline)

The `genes.spec.ts` "JBrowse 2 action opens an assembly-scoped locus deep link"
test is conditionally skipped, not unconditionally skipped. It runs against
either:

- the opt-in offline fixture:
  `GENES_JBROWSE_FIXTURE=1 npx playwright test -c playwright-public.config.ts`.
  `e2e/static-server.mjs` then returns one deterministic gene row for the fixture
  query, and the test asserts the row's
  `/browser?assembly=…&loc=chr:start-end` link and the new tab it opens;
- a live stack: `GENES_JBROWSE_QUERY=<gene id>` with the public config pointed at
  that stack.

Without either, the test skips with the exact missing prerequisite. The default
mock response stays empty, so the empty-state assertions are unchanged.


## 本地离线公开站 E2E（正确构建命令，勿再踩坑）

`playwright-public.config.ts` 由 `static-server.mjs` 在 `/soymutdb-next` 前缀下
同源提供 `apps/web/dist`，并把 API 基址指向同源 mock，因此构建必须绑定 **base**
与 **同源 API origin**，否则 SPA 资源/动态 import 404（历史上曾导致 20+/29 失败）。

```bash
cd <repo-root>

# 单站制品（E2E 用，必须落在 apps/web/dist）
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo \
  VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/soymutdb-next/jbrowse/ \
  pnpm --filter @soymutdb/web build

# 公开站 E2E（无 Docker / 无后端可运行）
cd e2e && npx playwright test -c playwright-public.config.ts
```

注意：

- 构建会触发 esbuild 的 Go 运行时 `newosproc` 崩溃 → 必须 `GOMAXPROCS=2`。
- 本环境 `CI=true` 会让 `build-sites.ts` 判定为生产构建并要求
  `SOYMUTDB_SITE_URL` / `SOYMUTDB_INTERNAL_SITE_URL`。跑双站制品时显式覆盖：
  `CI= VITE_DEPLOYMENT_MODE=demo ... pnpm --filter @soymutdb/web build:sites`。
- 双站制品后做泄漏扫描：
  `python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external --internal-root apps/web/dist/internal --sentinel "Internal Research Workspace for SoyMutDB"`
  （哨兵必须真实存在于 internal；当前生产哨兵为
  `Internal Research Workspace for SoyMutDB`）。

### 交互前的就绪等待（重要）

web 制品是 **replacement-render SPA**：构建期 SSG 标记是惰性的，Vue 首次提交
（handoff）后才可交互。`src/main.tsx` 在 `<html>` 上以 `data-app-ready` 通告该边界。

因此任何交互前必须等待就绪，否则点击会落在静态回退上并被静默丢弃。用
`e2e/tests/helpers.ts` 的 `gotoReady(page, url)` / `waitForAppReady(page)`：

```ts
import { gotoReady } from "./helpers";
await gotoReady(page, "/soymutdb-next/login");
```

另外 `/search/genes` 的提交按钮在 genome version（assembly）解析完成前
保持 disabled——缺少 assembly 的请求在 v4/v5 命名空间下是歧义的，因此按钮
显式报告"尚未可选"，而不是静默丢弃提交。测试应等待 `toBeEnabled()`。

## Known issues / false-positive notes

- **Document status 404 on 6 routes**: GitHub Pages currently serves
  `/genes`, `/variants`, `/blast`, `/news`, `/browser`, `/tools` with HTTP
  **404** + the SPA-fallback `404.html` (SSG emits flat `.html` only for a
  subset of routes). The pages **render fine client-side** (verified by the
  rendering assertions), so the smoke suite does not fail on this — the
  document status is recorded per route in `smoke-report.json`. Fixing it
  means emitting those routes in `apps/web/scripts/ssg-build.ts` (or adding
  redirects) — tracked as a follow-up, and it also matters for SEO/crawlers.
- **Cross-origin request failures** (`fonts.googleapis.com` preconnects,
  analytics, JBrowse iframe on `/browser`) are recorded, not failed — they
  depend on the runner's network, not on the deployment. Same-origin JS/CSS
  failures are the hard gate.
- **Placeholder origins in the current deployment** (`api.example.com` in
  the HTML, `VITE_JBROWSE_URL` unset → `http://localhost:5175` iframe
  default): data pages show fallback states; `/blast` SSE aborts (MIME) and
  falls back to polling; `/browser`'s JBrowse frame is CSP-blocked. All of
  it is tolerated + recorded in the report. Deploying with the
  `API_BASE_URL` / `VITE_JBROWSE_URL` secrets set removes these classes
  entirely — see the workflow's build step in `.github/workflows/pages.yml`.

## 生产 secrets 配置清单（API 就绪后执行）

| Secret | 用途 | 示例 | 设置命令 |
|---|---|---|---|
| `API_BASE_URL` | 前端 API 基址（不带路径） | `https://api.soymutdb.org` | `gh secret set API_BASE_URL --repo caoronglin/soymutdb-next` |
| `JBROWSE_URL` | JBrowse 部署地址（须与 CSP frame-src 一致） | `https://caoronglin.github.io/soymutdb-jbrowse/` | `gh secret set JBROWSE_URL --repo caoronglin/soymutdb-next` |
| `CONTENT_SNAPSHOT_URL` | 内容快照端点（SSG 内容页） | `https://api.soymutdb.org/api/v1/content/snapshot` | `gh secret set CONTENT_SNAPSHOT_URL --repo caoronglin/soymutdb-next` |

设置后 push main（或手动重跑 pages.yml）→ 部署完成自动触发 E2E Smoke。

**Smoke 语义**：`API_BASE_URL` 未配置时同源 API 404 记为报告不失败（SPA 相对 /api/v1 回退 + GitHub Pages 404）；一旦检测到跨域 API 请求（已配置），API 404 变为硬失败。静态资源（js/css/fonts/images）404 永远是硬失败。

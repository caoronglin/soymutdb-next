# Checkpoint — AntV charts, visit analytics loop, Python 3.15 isolation

Single continuous carrier for this workstream. Append to this file; do not create a
per-slice document. The coordinator owns the Git lifecycle (no commits here).

- Plan: `docs/aegis/plans/2026-10-10-antv-analytics-python315.md`
- Design: `docs/superpowers/specs/2026-10-10-antv-analytics-python315-design.md`
- Opened: 2026-10-10
- TDD route: **off**. Regression coverage still mandatory for behaviour changes.

## Intent

Four user-approved directions: (1) replace ECharts with `@ant-design/plots` in batches and
remove ECharts at the end; (2) close the website PV/UV/referrer loop end to end on the
existing analytics owner, preserving database content statistics and runtime metrics;
(3) verify Python 3.15 in an independent mamba environment — API/MCP/jobs-py first, biology
worker later; (4) use native React lazy/Suspense loading with antd Skeleton/Empty/Alert, no
custom framework.

Non-goals: adopting GoatCounter or any new analytics SaaS; introducing a new cookie
identity or a new authoritative store; changing any production Python pin; raising the
chart bundle budget without a decision; deleting production data or altering a database
identity.

## TaskStartSnapshot (captured by the planning subagent on the coordinator's authority)

Read-only. No branch, worktree, stage, commit, reset, clean, checkout or branch operation
was performed.

| Field | Value |
| --- | --- |
| branch | `chore/node-26-pin-20261010` |
| HEAD | `166f76bda6ed347af86c658d374c3525995c6a11` |
| HEAD subject | `166f76bda 2026-10-10 21:18:06 +0800 chore(e2e): remove leftover probe script` |
| tracked-modified | `.ai-memory/project_memory.md`, `apps/admin/src/components/admin-shell.tsx`, `apps/admin/src/regression/pro-table-migration.test.ts`, `apps/web/src/lib/animation-context.tsx`, `apps/web/src/lib/antd-theme.ts`, `apps/web/src/lib/view-transitions.ts`, `apps/web/src/react-app.tsx`, `packages/i18n-core/src/locales/en/common.json`, `packages/i18n-core/src/locales/zh/common.json`, `packages/ui-react/src/index.tsx`, `scripts/test_locale_language_purity.py` |
| staged (renamed) | `apps/web/src/lib/motion-policy.test.ts` → `packages/ui-react/src/motion-policy.test.ts`, `apps/web/src/lib/motion-policy.ts` → `packages/ui-react/src/motion-policy.ts` |
| untracked | `apps/admin/src/lib/motion-preference.ts`, `docs/dev/admin-console-overhaul-20261010.md`, `e2e/func.mjs`, `e2e/portal.mjs`, `e2e/r.mjs` |
| total dirty entries | 18 |

### Pre-existing changes that overlap this plan's write scopes — coordinate before editing

These are **not** ours. Three of them sit directly on files Track B and Track A must edit:

| Dirty file | Overlaps |
| --- | --- |
| `apps/web/src/react-app.tsx` | B4 (producer wiring, next to the existing `perf.ts` block at :105-114) |
| `apps/admin/src/components/admin-shell.tsx` | B5 (admin nav entry for the new route) |
| `packages/i18n-core/src/locales/{en,zh}/common.json` | A6 (removed ECharts keys), B5/B6 (new analytics keys) |

Also dirty and adjacent but not directly edited: `apps/web/src/lib/antd-theme.ts` and
`apps/web/src/lib/animation-context.tsx` (both feed the chart theme bridge),
`apps/admin/src/regression/pro-table-migration.test.ts` (an admin architecture regression
test that must still pass), and the untracked `e2e/*.mjs` scratch scripts.

Untouched by us: `apps/web/src/lib/motion-policy*` (staged rename into `packages/ui-react`).

**Rule for every slice**: capture a fresh `TaskStartSnapshot` before starting, rebase onto
whatever the coordinator has landed, and do not include someone else's dirty hunk in a
commit. Never `git checkout`/`reset`/`clean` these paths.

## Baseline read set

Acknowledged and read this session (see design §1 for the per-file findings):
`AGENTS.md`, `.ai-memory/LOCAL-RUN-ENV.md`, `docs/dev/mamba-validation-environment.md`,
`docs/dev/database-core-contract.md`, `plan.md` §2.3/Phase 4, `pnpm-workspace.yaml`,
`apps/web/config/config.ts`, `scripts/check-bundle-size.sh`,
`scripts/verify-frontend-artifacts.sh`, `knip.json`, `dependency-governance.json`,
`apps/web/src/lib/{perf.ts,use-echarts.ts}`, `apps/web/src/react-app.tsx`,
`apps/web/src/routes/analytics.tsx`, `apps/admin/src/{App.tsx,routes/index.tsx,routes/analytics-settings.tsx,routes/settings.tsx}`,
`apps/admin/src/components/charts/{storage-growth,query-latency}.tsx`,
`packages/charts/{package.json,src/{definitions.ts,ChartFigure.tsx,index.ts}}`,
`packages/api-client/src/admin-analytics.ts`,
`apps/api/app/api/v1/analytics.py`, `apps/api/app/services/analytics_service.py`,
`infra/clickhouse/{init.sql,test_schema_contract.py}`,
`apps/{api,worker,mcp-server}/pyproject.toml`, `packages/jobs-py/pyproject.toml`,
`{apps/api,apps/worker,apps/mcp-server}/uv.lock`, `.cnb.yml`,
`scripts/{ci-job-steps.sh,test_ci_job_contracts.py}`, `infra/docker/Dockerfile.*`,
`apps/mcp-server/Dockerfile`, `.cnb/env/Dockerfile.frontend`, `docs/aegis/adr/` (empty),
`docs/aegis/work/2026-09-28-portal-quality-improvements/10-intent.md`,
`docs/aegis/plans/2026-09-28-admin-editable-footer-search-font.md`.

Missing / not read: none blocking. `docs/dev/performance-optimization-plan.md` was read
selectively (§416-482) to confirm the ClickHouse parts-pressure item is pre-existing and
out of scope.

## Todo map

| # | Task | State |
| --- | --- | --- |
| A1 | Install `@ant-design/plots`, measure `charts.*.js`, React-19 smoke | pending — **hard gate for A2** |
| A2 | Facade runtime + migrate `packages/charts` | pending |
| A3 | Admin 3 charts | pending |
| A4 | Web 5 charts + delete `use-echarts.ts` | pending |
| A5 | Web tool charts (`enrichment`, `exppattern`) | pending |
| A6 | Remove ECharts (catalog, 3 deps, lockfile, orphan CDN setting, i18n keys) | pending |
| A7 | Bundle + native-lazy regression verification | pending |
| B1 | Server route allowlist, referrer categoriser, stop writing `path` + negative leakage tests | pending — gated on D1/D4/D5 |
| B2 | Additive `site LowCardinality(String)` column + DDL guard | pending — gated on D5 |
| B3 | Additive `available` field + client/OpenAPI contract | pending |
| B4 | Portal `pageview` producer | pending |
| B5 | Admin visitors route (first consumer of the typed client) | pending — needs A2 |
| B6 | Reconcile the Cloudflare-vs-first-party console copy | pending — gated on D2 |
| C1 | Create `.mamba-root/envs/py315` (regular CPython build) | **done** — 3.15.0 `h6e52b48_100_cp315`, SOABI `cpython-315`, `Py_GIL_DISABLED=0`, UTF-8 mode on |
| C2 | Core tier: jobs-py → api → mcp-server | **partial** — jobs-py 95/95 pass; api installed (orjson needs a Rust sdist build) with 6 passed / 5 Docker-fixture errors; mcp-server 28 passed / 6 failed / 3 error, single fastmcp import root cause |
| C3 | Worker tier, biology last (honest blocked is a valid result) | pending — **next** |
| C4 | Evidence page; prove zero production pin changes | **partially done** — page written at `docs/dev/mamba-python315-validation.md`; C3 still owes its section |

## Blocking decisions (must be answered before the gated task starts)

| ID | Question | Blocks |
| --- | --- | --- |
| D1 | Is GoatCounter dropped in favour of repairing the first-party owner? Evidence says it was never an accepted ADR, has no code, no deploy and no infra entry. | B1–B6 |
| D2 | Exact reconciled wording for `analytics-settings.tsx:151` and whether the visitors route is the console's single owner of PV/UV/source | B6 |
| D3 | If A1 measures `charts.*.js` above 370 KB gzip: reviewed budget change, or a different engine? | A2+ |
| D4 | Confirm this slice does not collect raw search terms, so `top_searches` stays empty and is labelled not collected | B1, B5 |
| D5 | Confirm the additive `site LowCardinality(String)` column rather than inferring the variant at the API | B1, B2 |

## Evidence recorded so far

Planning only. **Nothing was installed, no service was started, no file outside `docs/`
was modified, and no Git operation was performed.**

- `mamba --version` → 2.5.0; `mamba env list` → no 3.15 environment anywhere; the established
  isolated-env precedent is `.mamba-root/envs/postgres16`.
- `docs/aegis/adr/` is empty → no accepted architecture record for GoatCounter.
- `getAdminAnalyticsSummary` has zero React consumers (the admin dashboard uses
  `/admin/dashboard-stats` + `/admin/dashboard-series`). The Vue-era docs claiming otherwise
  are stale.
- `pageview` has no frontend producer; `perf.ts` is the only `/track.gif` caller and sends
  `event=performance`.
- The `charts` cache group is `enforce: true` over `(?:echarts|zrender)` with a 370 KB gzip
  cap, so the whole engine lands in one chunk — the reason A1 must measure first.

## Environment ceiling (not-covered, never passed)

No Docker → testcontainers and ClickHouse integration cannot run here. No Redis server →
Celery worker tests cannot run. `uv` under `~/.local/share/uv/tools` is read-only on this
host. `max dev` hangs at `Preparing...`; use `max build`. `/tmp` does not survive between
bash calls. Port 80 needs root. See `.ai-memory/LOCAL-RUN-ENV.md` §8.

## Slice update — 2026-10-10, C1 + C2 (implementation slice, not a coordinator close-out)

Full detail: `docs/dev/mamba-python315-validation.md`. The coordinator still owns the
overall task state; this entry does **not** mark the whole task complete.

### Fresh TaskStartSnapshot (read-only, no Git lifecycle operation)

branch `chore/node-26-pin-20261010`, HEAD `166f76bda6ed347af86c658d374c3525995c6a11`,
21 dirty entries (13 tracked/staged + 8 untracked). The 11 modified + 2 staged-renamed
tracked paths are the **same set** as the planning snapshot; the 3 extra untracked entries
are this workstream's own `docs/` files. No new dirty path under `packages/jobs-py`,
`apps/api` or `apps/mcp-server`. The 18 inherited dirty paths were not touched.

### C1 evidence

Solver dry run first: `python 3.15.0 h6e52b48_100_cp315` — the **regular** `cp315` build,
not `cp315t`. Create pinned to that build string, exit 0. Interpreter facts verified:
`sys.executable` = `.mamba-root/envs/py315/bin/python`, `sys.version` = `3.15.0 | packaged
by conda-forge | (main, Oct  9 2026, 18:56:31) [GCC 15.3.0]`, `SOABI cpython-315`,
`Py_GIL_DISABLED 0`, empty `abiflags`, `sys.flags.utf8_mode 1`.
`.gitignore:215` covers `.mamba-root/`, verified by `git check-ignore -v`, so no mamba
artifact can enter version management. No old env was deleted; `mamba env list` unchanged.

### C2 evidence

| Project | Outcome |
| --- | --- |
| `packages/jobs-py` | **95 passed, 0 failed, exit 0** — plain and `-X warn_default_encoding` runs, zero warnings |
| `apps/api` | install **exit 0** after one documented failure; tests **6 passed, 5 errors (exit 1)** — the 5 errors are testcontainers hitting the absent Docker socket, i.e. **not covered** |
| `apps/mcp-server` | install **exit 0**; tests **collection error exit 2**; excluding `tests/test_tools.py`: **6 failed, 28 passed, 3 errors, exit 1** |

### Failed / uncovered this slice

1. **api sync attempt #1, exit 1** — verbatim minimum: `orjson (v3.11.9)` → `maturin failed
   … failed to start cargo metadata: Text file busy (os error 26)`. Two separate causes:
   `apps/api/uv.lock:1304-1316` ships **only `cp314` wheels** for orjson 3.11.9 (no cp315,
   no abi3), so 3.15 needs a **Rust source build**; the `Text file busy` part was the
   rustup toolchain still being written under `~/.cache/puccinialin`. The identical command
   succeeded once the toolchain was materialised. No project file was changed.
2. **mcp-server** — `ImportError: FastMCP server support is not installed. Install fastmcp
   or fastmcp-slim[server].` raised from the project's own `src/mcp_server/server.py:47`;
   `apps/mcp-server/uv.lock:394-399` resolves `fastmcp 3.4.7` → `fastmcp-slim[client,
   server]`. Recorded as a dependency-set question to investigate — **not** a claim that
   fastmcp is 3.15-incompatible, and **not** a claim that the project is broken on 3.14.
3. **Not covered** — api PostgreSQL-backed layers (`SOYMUTDB_TEST_DATABASE_URL` against
   `.mamba-root/envs/postgres16` on 55432), the permission and security-matrix tests,
   testcontainers and ClickHouse layers, and everything in C3. None counted as passing.
4. **Network** — `https://docs.python.org/3/whatsnew/3.15.html` via the Jina reader timed
   out (curl exit 124, no bytes). The python.org 3.15.0 release page **did** return HTTP 200
   and was used; the failed fetch is recorded as a failure, not as a read.
5. `apps/api/pyproject.toml` already ignores `DeprecationWarning`/`PendingDeprecationWarning`
   in pytest — **left alone** (no mechanical third-party fixes). A clean api run therefore
   proves nothing about deprecations until that is overridden.

### Deviations recorded

`uv sync --locked` was used instead of the plan's one-line `uv pip install`, with
`UV_PROJECT_ENVIRONMENT` set explicitly and `--python` pinned to the mamba interpreter, so
no `uv sync` ever fell through to an existing `apps/*/.venv`, `webdb` or a running service
env. **Three isolated venvs** were created under `.mamba-root/envs/py315/venvs/` because one
shared env would have made `uv sync` prune the previous project's dependencies and produce
a fake pass. `pytest` was added locally to the mcp-server scratch venv only. **No lock
validation is claimed beyond "sync with `--locked` succeeded."**

### Scope statements

**No production pin moved** — `requires-python`, `ruff target-version`, every `uv.lock`,
`.cnb.yml`, `.cnb/env/Dockerfile.frontend`, `infra/docker/Dockerfile.*`,
`apps/mcp-server/Dockerfile`, `scripts/ci-job-steps.sh` and
`scripts/test_ci_job_contracts.py` are untouched. That is a property of the **current
stage**, not the permanent end state: the overall objective is still the core migration
once the evidence is sufficient.

**Python native lazy imports (PEP 810) are a phase-2 candidate only**, not merged into the
compatibility work and not enabled globally, alongside `sentinel` (PEP 661), `frozendict`
(PEP 814), the experimental JIT and PEP 799 profiling. No LLVM installed. This does not
change the approved **frontend** native React lazy/Suspense scope.

### Next smallest safe action

**C3** — worker tier on the existing `.mamba-root/envs/py315/venvs/` layout, biology last.
Before it, the cheap C2 remainder is worth folding in: (a) the api PostgreSQL-backed tests
via `SOYMUTDB_TEST_DATABASE_URL` + `.mamba-root/envs/postgres16` on port 55432, and (b) the
fastmcp `fastmcp-slim[server]` question. AntV/statistics remain with a later subagent; no
service was started and no service environment was touched.

## Slice update — 2026-10-11, A1 scene recovery (read-only, no build/install/run)

A recovery slice after two `run failed` takeover subagents. **Nothing was installed, built,
started or edited except this checkpoint.** The intent of A1 is unchanged; this entry only
corrects the inherited picture.

### Fresh TaskStartSnapshot (read-only, no Git lifecycle operation)

branch `chore/node-26-pin-20261010`, HEAD `166f76bda` — **both unchanged** from the C1/C2
entry. **37 dirty entries (19 tracked + 18 untracked)**, up from 21. The 18 inherited dirty
paths from the planning snapshot are all still present and were not touched; the 6 new
tracked paths are exactly the A1 probe wiring:

`pnpm-workspace.yaml`, `pnpm-lock.yaml`, `packages/charts/package.json`,
`apps/web/package.json`, `apps/web/config/config.ts`, `apps/web/src/umi-entry.tsx`.

### Dependency state: declared = locked = installed (verified)

| Package | Catalog declared | Lock resolved | Installed in `node_modules` |
| --- | --- | --- | --- |
| `@ant-design/plots` | `2.6.8` | `2.6.8` | symlink → `.pnpm/@ant-design+plots@2.6.8_react-dom@19.3.0_react@19.3.0__react@19.3.0` |
| `@antv/g2` | transitive | `5.4.8` | `.pnpm/@antv/g2@5.4.8` |
| `@antv/g` | transitive (`^6.1.7` upstream) | `6.3.1` | — |

`.a1-meta.json` is registry metadata confirming `2.6.8` is `latest`, MIT, published
2025-12-24. **The install half of A1 is genuinely complete** — the earlier "install failed"
report is wrong on this point.

### Correction: the build never produced evidence

- `job_list` → **no background jobs at all**; nothing visible to wait on.
- Read-only `ps` → **no `max build` / vite / rspack / webpack / turbo process for this repo**.
  The only matching PIDs are the user's own preview servers
  (`local-preview-server.mjs --app portal --port 5173`, `--app admin --port 5174`,
  ~52 158 s old). **Not touched, not killed.**
- **`apps/web/dist` does not exist.**
- `apps/web/.turbo/turbo-build.log` mtime **Sep 26 15:35**; newest root `.turbo/cache`
  entry **Oct 8 19:49**. Both predate the A1 work (probe files: Oct 10 22:44–22:48).

So the trailing `Build running...` was a **run that was killed with its subagent**, not a
build in flight and not a completed build. Build state: **not started / no exit code,
unknown**. `.a1-audit.err` is **0 bytes**, so no build error was even captured.

### Consequence: the A1 measurement does not exist

`.a1-audit.json` is **a pnpm security audit**, not a bundle measurement — its payload is
`{advisories, metadata}` over 1889 dependencies. **No `charts.*.js` gzip sample exists at
all**; the 370 KB cap is therefore **unmeasured**, not passed and not failed. **No raw/gzip
chart sample can be reported, old or new.**

Budget itself is untouched and was **not** raised: `scripts/check-bundle-size.sh:24`
`CHARTS_MAX_KB:-370`, checked at `:154` as `charts.*.js`, gzip, `required`.

Audit finding worth keeping: **1 high** (`braces` stack-exhaustion DoS) + **8 moderate**
+ **1 low**. The moderate `echarts` XSS (patched `>=6.1.0`, repo pins `5.5.1`) is
**retired by A6 by design**. **No advisory is `@antv`/`@ant-design/plots`** — the AntV
install added no known vulnerability.

### Probe: present, intact, deliberately KEPT

`.a1-probe-backup/hashes.txt` backups were verified against the tree:
`apps/web/src/routeTree.gen.ts` and `packages/charts/src/index.ts` **match their backup
hashes exactly** (no residue in either). `apps/web/package.json` differs from its backup by
exactly one line — the `@soymutdb/charts` workspace dep, added 24 s *after* the backup.

The probe is complete and functional: `packages/charts/src/a1-antv-budget-probe.tsx` renders
Column/Line/Area/Heatmap, reached from `apps/web/src/routes/a1-budget-probe.tsx` through
`React.lazy` + `<Suspense>` (the approved native loading path), wired via the `./probe`
export subpath in `packages/charts/package.json`.

**Nothing was deleted.** The probe is the instrument for the one remaining A1 step; removing
it now would destroy the scene and force a rebuild of what already works. Cleanup belongs
after a real measurement exists.

### Scope held

No install, no build, no server start, no `git add/commit/reset/clean/stash/checkout/branch`.
No statistic-collection behaviour or third-party analytics config was touched. Python was
**not** re-verified this slice (the prior 3.15.0 build and jobs-py 95/95 stand as previously
recorded, unverified by this slice) and **no pin was changed**.

### Next smallest safe action

**A1-final: run the web build once and read the real number.** Exact command per
`.ai-memory/LOCAL-RUN-ENV.md` §2 (`cd apps/web`, mamba `opencode` PATH,
`GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`, `SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true`,
`VITE_*` vars, `./node_modules/.bin/max build`), then read
`apps/web/dist/charts.*.js` gzip against `scripts/check-bundle-size.sh`'s 370 KB.
Run it in a **managed background job** and read the job to a real exit code — a bare
`Build running...` is not evidence. **D3 cannot be answered until that gzip number exists.**

Only after a measurement: answer D3, then delete the probe
(`apps/web/src/routes/a1-budget-probe.tsx`, `packages/charts/src/a1-antv-budget-probe.tsx`,
the `./probe` export, the `umi-entry.tsx` import, `.a1-audit.*`, `.a1-meta.json`,
`.a1-probe-backup/`, `.ph/`) and revert the `charts` cache-group widening in
`apps/web/config/config.ts` to the ECharts-only test, then start **A2**.

### Drift check

Intent and scope fence hold. **State: `needs-verification`** — A1 is *installed but
unmeasured*, which is weaker than the inherited record implied. No new owner, fallback or
compatibility branch was introduced. The `config.ts` cache-group widening and the
`umi-entry.tsx` probe import are **live production-build changes that must not be forgotten
at the end of Track A**; they are now recorded here as a retirement obligation.

## Drift check

Intent, scope, compatibility boundary, retirement path and evidence freshness are all
consistent as of this entry. No new owner, fallback, adapter or compatibility branch has
been introduced by the planning pass. State: **needs-verification** until the first slice
produces fresh evidence.

## Corrections to inherited claims

Two claims from earlier sessions were checked against the current tree and are **wrong**;
do not carry them forward:

1. "`packages/charts` is a public package that must not be deleted on zero-consumer
   evidence." — `packages/charts/package.json` declares `"private": true`, so it is not a
   published surface. It is still not deleted, but for the opposite reason: `plan.md:532,606`
   designates it as the destination chart owner.
2. "No cp315 wheels exist, so Python 3.15 is fully blocked." — `pyfaidx` ships a pure wheel
   and `igraph`/`leidenalg` ship abi3 wheels. The genuine unknowns are `cyvcf2` (no 3.15
   wheel seen; would need an sdist/Cython build) and the `polars` native runtime. All of it
   remains metadata-level until an install actually runs.

### Correction added here (does not rewrite the entries above)

Item 2's wording above is now itself **narrowed** in `docs/dev/mamba-python315-validation.md`
§C3: "ships an abi3 wheel" is a **lock-tag reading**, not an install fact. The whole-migration
claim stays false and unproven — see the stage entry below.

## Stage — mobile plan attached + probe-state correction (2026-10-11)

**Mobile doc exists and is linked.** `docs/aegis/plans/2026-10-11-ant-design-mobile.md` now
carries a back-link to the main plan, and the main plan header carries a forward-link to it,
flagged as **research-and-planning only: it grants no implementation authorization**. Its T1–T5
are not dispatched by this workstream.

**Correction to the entry above — the umi-entry root probe is REVOKED.** The earlier text
("the `umi-entry.tsx` probe import [is a] live production-build change that must not be
forgotten") described state at that time and is **no longer current**: executor `ac1e…` and
reviewers `6ad7…` / `7cbed…` removed the root probe, confirmed by the coordinator's own 9-line
read-back. Treat that retirement obligation as **discharged for the root import**; the record
above is left intact as history rather than back-dated.

**What the two stages actually produced:** static inspection only — **static PASS**. **No
build, no test, no install, no stage, no commit.** Two artifacts remain deliberately parked for
a later slice: the two source probe files plus their `./probe` export and the `config.ts`
cache-group widening (and `.a1-*` scratch). They are **not** yet retired; cleanup waits for a
real measurement.

**Still unmeasured:** the installed `plots` bundle against `CHARTS_MAX_KB=370`. A1 remains
**installed but unmeasured** — no gzip number exists.

**Python C3:** the only real diagnostic is the recorded `uv sync --locked --no-build` run —
**exit 2 at `clickhouse-connect 1.7.0`, 0 packages installed**. That is a failed binary-only
install attempt in this environment for this lock; source builds, new wheels and alternative
versions are **unverified**, and **no import test ran**. Nothing here moves the worker or the
whole migration forward.

**Task state: NOT DONE.**

## Slice update — 2026-10-11, privacy-policy approval recorded (docs-only, no code)

Documentation patch only: the plan, this checkpoint and the design spec. **No product code
was edited, no build/install/test/git/network operation was run, and no other source writer
touched `docs/`** (the concurrent writer is probing `config.ts` / `umi-entry` only).

### The user's real decision — recorded exactly

Source: `ask_user_question`, `analytics_privacy_policy`.
**`selected = 第一方隐私统计（推荐）`.** Its description *is* the approved contract: **use the
existing backend; record only route templates; under DNT send no tracking cookie; stop the
public site's third-party analytics scripts; do not touch production data.** Both options
excluded internal identifiers, raw search text and full URLs, so that exclusion stands
without another question. No open question is left implying the work cannot start.

**Not approved and not inferable:** production database cleanup, a new tracking identity, a
new site column, a whole-set Python upgrade. None of these is claimed anywhere in these docs.

| Decision | State |
| --- | --- |
| D1 GoatCounter | **answered** — dropped; first-party owner repaired, not replaced |
| D2 Cloudflare copy | **answered in direction** — third-party scripts stop; settings copy + CSP stay consistent **after** the code lands, serially |
| D3 charts budget | **still open** — needs a real gzip sample |
| D4 search text | **answered** — no raw terms; `top_searches` empty and labelled not collected |
| D5 `site` column | **NOT approved** — no column, no additive `ALTER`; **B2 does not start** |

### B1 override: the original regex is deprecated, not repaired

Plan task B1's `^/[a-z0-9]*(?:/[a-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)?)*$` **must not be
implemented**: counterexamples and **42 mutants**, admitting numeric-only segments and
arbitrary digit runs, so internal numeric ids and coordinate-like paths pass. **Rejecting it
does not authorise a forbidden-digit character class.** The direction is a **finite canonical
route-template allowlist** + **raw path-parameter normalisation** into that template +
**front/back drift verification** between portal-emitted and server-allowlisted templates.

### Constraints bound to the approval

- Route templates only. Raw `q` / `ref` / `source` / `path` is **not stored and not echoed**;
  normalise server-side or into a fixed enum. A parameter kept for **request** backward
  compatibility only must not store its raw value.
- **The internal build never enters the anonymous producer.** A client `site` marker is not a
  permission boundary; the API must not decide the variant from guessable host/IP/UA. If a
  schema/site dimension is genuinely needed, re-check current settings and read queries as a
  separate step. **D5 is not implicitly approved.**
- **DNT is handled before any `Set-Cookie`.** Existing historical cookies are **not** deleted
  and no store is cleared. The figure is **session count, not people**.
- IP and other extra stable identifiers are assessed against minimal collection; until then
  **no claim that the measurement scope has changed**.
- Summary is **private / `no-store`**; **availability ≠ zero traffic**; **negative leakage
  tests remain mandatory**.
- Stopping the public site's Cloudflare script is **code + later build config**: no online
  secret, no deployment action, no production-data action.

### Inherited state, unchanged and re-stated precisely

- **Pre-AntV web build**: child `00f0b…` recorded **real exit 0, 24.92 s**. That is a
  **baseline only** — it is **not** the AntV measurement, `charts.*.js` gzip against
  `CHARTS_MAX_KB=370` still does not exist, and **D3 stays open**.
- **Mobile plan** `docs/aegis/plans/2026-10-11-ant-design-mobile.md` stays **plan-only**:
  it grants no implementation authorization and its T1–T5 are not dispatched by this
  workstream.
- **Root probe withdrawal is confirmed**: two static review passes, **no Git commit**. The
  two parked source probe files, the `./probe` export and the `config.ts` cache-group
  widening are **still not retired** — cleanup waits for a real measurement.

### Scope held

`docs/` only. No product code, no pin, no store, no cookie, no schema, no deploy. **Task
state: NOT DONE** — an approval is not an implementation, and the real permission-matrix
tests still have to run.

## Slice update — 2026-10-11, B1a sanitisation landed (docs-only record)

Record only. **This writer changed no product code and ran no test, build, install, Git or
network operation.** The API writer `0397` owns router/service/tests and does not write this
document; this entry only records receipts that already happened.

### B1a: `analytics_privacy.py` + `test_analytics_sanitization.py`

- First green run **133 passed**.
- Review `1135` raised **P1 — dynamic template not idempotent** and **P2 — relative query /
  hash lose attribution**.
- After `bbed`'s fix the original **133 are kept**, **+35** new cases = **168**; the author
  additionally covered **3.14.8**.

### Verification receipts

- `2574` stage-1 re-review complete, run through the **absolute** interpreter
  `/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/api/bin/python`, **Python 3.15.0**:
  **168 passed, 0 skipped, 0 xfail**; with **EncodingWarning escalated to error it also
  passes**.
- `9b15` stage-2 quality review **PASS with P2, no P0 / P1**: copy em-dash coupling,
  mirror-regex parse boundary, comment scope and similar micro items — **still unfixed**. An
  advisory pass is **not** a merge.
- `5488`: `-V` and `-c` with those same two absolute prefixes both **exit 0**. This **corrects**
  other children that concatenated the prefix into a `$HOME`-relative `.mamba-root`. A missing
  `mamba env list` entry or a glob miss **does not prove** this machine lacks 3.15. The erroneous
  receipts stay in the log **as history, marked corrected** — no number is rewritten.

### Still open — nothing in this slice closes these

- **B1a still has no HTTP and no real ClickHouse / PostgreSQL integration.** `0397` is wiring
  **B1b**; without its receipt it **must not be marked complete**.
- AntV: `d8` and `6739` probe attempts **failed to run — no measurement exists**. The `00f0b`
  pre-AntV **24.92 s** baseline is **not** an AntV budget and must not be spent as one. Latest
  coordinator read: `umi-entry` is **9 lines with no probe**, while the parked source probe, the
  `./probe` export and the `config.ts` cache-group widening are **still not fully retired** —
  cleanup waits for a real measurement. `CHARTS_MAX_KB=370` stays **UNKNOWN**, **not relaxed**;
  **D3 stays open**.
- The mobile plan stays **plan-only**; no AntV and no MCP 3.15 candidate is resolved.

### Scope held

`docs/` only, append-only, no history rewritten. No Git commit, release, push or online-data
action. **Task state: NOT DONE.** Next: **B1b receipt plus the two reviews**; AntV and the MCP
3.15 candidates remain **pending**.

## Slice update — 2026-10-11, B1b + C2 candidate + AntV rollback (docs-only record)

Append-only record. **This writer changed no product code and ran no test, build, install, Git or
network action.**

### Receipts

- `0397` **B1b real 3.15: 219 passed**; storeSpy only, no CH/PG.
- `beeb` spec **FAIL**, two P1 (contract description; SDK + pre-merge LIMIT 50). `8f` fixed it:
  **219→239 analytics**, openapi contract **260 passed**, SDK **155** plus typecheck / lint /
  generate / check-contract all **exit 0**. Typed `AnalyticsSummary` 7 data + 7 availability, empty
  raw search without query, raw groups unlimited before merge cap 20 (old limit 49 ≠ 120 is the
  counter-example). bool NaN rejected, rejected values not logged, referrer single owner + blank
  adapter, no em-dash assertion on real copy. **A `0397` receipt is not an approval**; `b264` runs
  an independent spec re-review, quality review still pending; 9 Docker errors ≠ pass, live CH
  unknown.
- `e595` new isolated candidate, real 3.15, beartype **0.23.1** (PyPI 2026-10-11T05:36:52Z),
  py-key-value-aio 0.4.5 (>=0.20 licence OK). After syncing **75** locked packages: env-only
  override / pip check / import FastMCP OK, **66 passed** with **7 EncodingWarning**s, error mode
  **3 failed / 63 passed** — **not a formal lock**. `a0ec` is advancing the real lock + explicit
  UTF-8 tests and the 3.14/3.15 double regression; **no receipt, not done**. Worker 3.15
  locked-wheel boundary unchanged.
- `cf48` staged an 11-line temp entry; `f090`'s isolated build child failed with no closing and no
  real exit budget, so **UNKNOWN stands and `CHARTS_MAX_KB=370` is unchanged**. `5f937` withdrew
  exactly 2 lines back to a 9-line ReactApp-only entry, no probe in the root graph. Source probe /
  `./probe` export / `config.ts` residue **not retired**, full migration incomplete; **no refreshed
  dist and no successful build claimed**; 24.92 s remains the pre-AntV baseline only.

Mobile stays **plan-only**. **Task state: NOT DONE.**

## Readiness — 2026-10-11, round opening (docs-only, append-only)

This writer changed no product code and ran no install, build, test, server, Git-mutating or
network action. The only write is this append; the history above is unchanged.

### TaskStartSnapshot (read-only, re-captured this round)

`git rev-parse HEAD` = **`166f76bda6ed347af86c658d374c3525995c6a11`** (branch
`chore/node-26-pin-20261010`, subject `chore(e2e): remove leftover probe script`).
`git status --short` = **27** tracked-modified, **2** staged renames, **22** untracked;
`git diff --stat` = 27 files, +1963 / -557.

Pre-existing dirty paths, **not authored by this workstream and not owned by this round**: the
API analytics trio (`apps/api/app/api/v1/analytics.py`, `app/schemas/analytics.py`,
`app/services/analytics_service.py`) plus untracked `analytics_privacy.py` and its two test
files; MCP `apps/mcp-server/tests/test_smoke.py`, `test_transport_auth.py`, `uv.lock`; web
motion/admin/i18n (`animation-context.tsx`, `antd-theme.ts`, `view-transitions.ts`,
`react-app.tsx`, `umi-entry.tsx`, `config.ts`, `admin-shell.tsx`, `pro-table-migration.test.ts`,
both `common.json`, the `motion-policy` renames into `packages/ui-react`,
`motion-preference.ts`); the AntV A1 probe set (`a1-budget-probe.tsx`,
`a1-antv-budget-probe.tsx`, `.a1-probe-exports.mjs`, `.a1-audit.*`, `.a1-meta.json`,
`.a1-probe-backup/`, `.ph/`); `docs/**`; plus `pnpm-lock.yaml`, `pnpm-workspace.yaml`,
`packages/charts/package.json`, `packages/api-client/*` and `e2e/*.mjs`.

**All of those are user modifications and every one is protected.** So is all production data:
no row deletion, no identifier reassignment, no store or cookie clearing, no schema change.
`git diff --check` exits **0** with no output — a **clean inherited baseline, nothing to repair**.

### Governance

- ChangeNecessity: finish the already-approved charts / privacy-analytics / core-3.15 loop.
- ArchitectureReviewRequired: **yes**. TDD route: **off** (regression coverage still required).
- Dispatch is the main coordinator's alone; this writer dispatched nobody and recursion is
  prohibited. No publish, push, commit or other Git mutation.

### Status carried forward — nothing here is closed

- **B1b history**: **239** analytics, **260** openapi contract, **155** SDK, plus typecheck /
  lint / generate / check-contract exit 0. An independent **spec re-review then a quality
  review** is this round's work; **an author receipt is not an approval**. Live ClickHouse is
  still unknown and the 9 Docker errors are not a pass.
- **MCP 3.15 formal lock status is unverified** — `e595` stayed a candidate and `a0ec`'s
  beartype lock + explicit UTF-8 tests + 3.14/3.15 double regression still owe a receipt.
- **A1 budget stays UNKNOWN**; `CHARTS_MAX_KB=370` is **not relaxed** and **D3 stays open**.
  Read this round: `apps/web/src/umi-entry.tsx` is **9 lines, `ReactApp` only, no probe**, so
  the root-graph withdrawal holds — yet the parked source probe, the `./probe` export and the
  `config.ts` cache-group widening remain **not retired**, and no refreshed `dist` or successful
  build may be inferred. 24.92 s is a pre-AntV baseline only.
- **Mobile plan stays research-only** and grants no implementation authorisation.
- **Toolchain promote (Track C)** may only become its **own slice** once evidence is sufficient
  and the biology boundary is preserved. **No production pin may be upgraded here**, directly
  or by implication.

### In flight (read-only children; they write no document)

`f9aec` runs the stage-1 analytics review and `559b` the Python 3.15 side. Their receipts land
in a later append; nothing is claimed for them here.

### Backlog mapping from the older console design — no new work record

`docs/dev/admin-console-overhaul-20261010.md` still holds items this workstream does **not** own
and does **not** authorise: 127 missing portal i18n keys, motion polish, removing `pro-layout`
(239 call sites), `admin_imports.py:262` durable writer OFF, `analyses/index.tsx:82` TODO,
`sra.py:16` `unknown` stub, and the settings-home entry-card question. They stay visible to the
coordinator as backlog; editing them here would be scope drift.

### Next and risks

Next: independent spec re-review, then quality review, of B1b; the MCP formal-lock receipt; and
one real gzip sample before any chart decision. Risks that must not be papered over: an
approval read as a merge, **24.92 s** read as the AntV budget, **UNKNOWN** read as **PASS**, and
a pin or production-data change smuggled in as a side effect. **Task state: NOT DONE.**

## Slice update — 2026-10-12, A1 measured (build + budget verdict, no product chart touched)

Append-only record. This slice **installed nothing, changed no lockfile, touched no business
chart, ran no service, and performed no Git operation**. A2 was not started.

### Root cause of the "333,656 is maybe AntV" ambiguity

**It is ECharts.** `charts.50a9bf9a.async.js` carries the ECharts runtime marker
`_echarts_instance_` and ECharts-only literals (`Sankey is a DAG, the original data has cycle!`,
`MagicType.js` path data), and contains **zero** G2-only literals. `grep @antv` could never have
settled it: minification mangles identifiers. The reason no AntV was present is structural, not a
measurement bug — `apps/web/config/config.ts` declares Umi routes explicitly (`/`, `/*` ->
`@/umi-entry`), Umi does **not** scan `src/routes/`, and `src/routeTree.gen.ts` is a committed
TanStack artifact with no in-repo generator. So the parked probe file was in no webpack graph at
all. The probe was wired through a `config.ts` route (`SOYMUTDB_A1_PROBE=1`), never by editing the
generated route tree.

### Receipts (exact commands)

Build env per `.ai-memory/LOCAL-RUN-ENV.md` §2 (mamba `opencode` PATH, `GOMAXPROCS=2
RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`, `VITE_SITE_VARIANT=external`, `VITE_BASE_URL=/`,
`VITE_API_BASE_URL=http://100.77.182.76/api/v1`,
`VITE_JBROWSE_BASE_URL=http://100.77.182.76/jbrowse/`), run from `apps/web`:

1. `./node_modules/.bin/max build` (probe **off**) — **exit 0**, **22.907 s**.
2. `./node_modules/.bin/max build` (probe **on**) — **exit 0**, **30.561 s**; repeated with the
   delivered config — **exit 0**, **35.087 s**, identical `charts.216a4796` hash.
3. `./node_modules/.bin/max build` into `SOYMUTDB_DIST_DIR=dist-a1-baseline` (probe **off**, stats
   instrumentation **on**) — **exit 0**; emitted byte-identical `charts.50a9bf9a`, which proves the
   stats plugin is output-inert.
4. `bash scripts/check-bundle-size.sh apps/web/dist-a1-baseline/assets` — **exit 0**.
5. `bash scripts/check-bundle-size.sh apps/web/dist/assets` — **exit 1**.
6. `packages/charts`: `./node_modules/.bin/vitest run` — **10 passed / 2 files, exit 0**
   (the A1 React-19 smoke file is 5 of those; jsdom cannot rasterise, and the test asserts that
   boundary).
7. `apps/web`: `./node_modules/.bin/tsc --noEmit` — clean.

### The numbers

| Build | charts chunk | raw | gzip | `CHARTS_MAX_KB=370` |
| --- | --- | --- | --- | --- |
| probe off (ECharts only) | `charts.50a9bf9a.async.js` | 1,037,024 B | **333,656 B (326 KB)** | gate **PASS**, exit 0 |
| probe on (ECharts + AntV) | `charts.216a4796.async.js` | 2,086,844 B | **628,162 B (614 KB)** | gate **FAIL**, exit 1 |

All-asset gzip total: 1,756,619 B -> 2,186,410 B, **+429,791 B**.

Real AntV increment, split by where it actually landed:

| Where | gzip delta | What it is |
| --- | --- | --- |
| `charts` chunk | **+294,506 B** | `@antv/g2`, `@antv/g`, `@ant-design/plots` (all match the group regex) |
| new `609.e2882906.async.js` | **+129,804 B** | **AntV spill outside the group**: `lodash` 545,945 B src, `html2canvas` 441,542 B, `gl-matrix` 86,443 B, `d3-scale-chromatic` 44,751 B, `tslib` 29,422 B — all `@ant-design/plots` / `@antv/g` / `@antv/g-canvas` dependencies |
| `ui` chunk | **+2,872 B** | `@ant-design/charts-util` 15,273 B src, matched by the `ui` regex instead of `charts` |

**AntV-attributable cost ~= 427,182 B gzip (~417 KB).** The `charts` budget line alone sees
294,506 B of it: the cache-group regex under-reports the engine.

### Proof that real AntV modules are in the build

1. **Build entry**: `config.ts` route -> `src/routes/a1-budget-probe.tsx` ->
   `React.lazy(import("@soymutdb/charts/probe"))` -> `packages/charts/src/a1-antv-budget-probe.tsx`
   -> `@ant-design/plots` (`Area`, `Column`, `Heatmap`, `Line`). The probe emits its own
   `routes__a1-budget-probe.cc6cc2be.async.js` (644 B), so the route is in the graph.
2. **Engine-exclusive literals** (string literals survive minification): the G2-only literals
   `Missing encode for x or y channel.`, `component.legendContinuousBlockSize`,
   `interaction.elementSelectByColor`, `The container is not initialized!`,
   `legend-category-item-focus-group` each occur **exactly once in `charts.216a4796` and zero
   times in `609`, `ui`, and the probe-off charts chunk**. `@antv/g` dist literals: 218 hits in the
   charts chunk.
3. **Chunk-level module stats** (`SOYMUTDB_A1_STATS` webpack `done` hook, writes a file only):
   the `charts` chunk lists `@ant-design/plots` modules plus the 3,878,464 B `echarts`
   concatenation; the `609` chunk lists `lodash` / `html2canvas` / `gl-matrix` /
   `d3-scale-chromatic` / `tslib`. Umi's `stats` config collapses concatenated children
   (`filteredChildren`), so per-package numbers come from the declared dependency tree rather than
   from per-module source bytes — labelled as such, not as module-level precision.

### Verdict and recommendation for D3

**Do not raise the budget.** 614 KB is a *dual-engine* number: ECharts is still in production
until A6, and the migration deliberately keeps both engines in one `charts` chunk so the engine
is never split across vendors. The AntV marginal cost is **294,506 B gzip (~288 KB)**, i.e. 78 % of
the 370 KB cap on its own; removing ECharts at A6 is what makes the cap hold. Estimated post-A6
`charts` group ~= 628,162 - 333,656 ~= **294 KB gzip**, ~76 KB under the cap. That is an estimate
from the measured marginal delta, **not** a post-removal build — A7 must re-measure and that
re-measurement is the only thing that may declare PASS. **No state may ship in which both engines
are present**, because that state fails the gate twice: `charts` 614 KB > 370 KB **and**
`charts.216a4796` 614 KB > `CHUNK_MAX_KB=600`.

### Carried into A2/A6/A7

- **Widen the `charts` cache group** to the engine's real dependency set (or add a matching
  budget) — `lodash`, `html2canvas`, `d3-*`, `gl-matrix`, `tslib`, `@ant-design/charts-util`.
  Until then `check-bundle-size.sh` under-reports the chart engine by ~133 KB gzip.
- A6 removes `echarts|zrender` from the regex; A7 re-runs the same two-build comparison.
- The temp probe is **inert by default** (`SOYMUTDB_A1_PROBE=1` / `SOYMUTDB_A1_STATS=<path>`), so
  an ordinary `max build` ships neither the probe page nor the stats file. Retirement of the probe
  files / `./probe` export is still the coordinator's call.


## Interim acceptance ledger — 2026-10-12 (accepted evidence + explicit pending; NOT a final state)

Append-only interim ledger. Every row below is written at its **current** verification state. A row
marked pending is **not** an implied completion and must not be read as one by a later slice. Nothing
here was committed, pushed or deployed; the coordinator owns the Git lifecycle. No code, lockfile,
pin or production data was changed by this ledger, and no user hunk was reverted. The exact absolute
evidence paths for `liveCH` and for the D3 selective-G2 runtime probe are **pending receipt** and do
not block the accepted rows below.

### Ledger summary

| Track | Item | State |
| --- | --- | --- |
| build | `Makefile:211` `src/soymutdb/` -> `app/` | **accepted** (`make -n` passes; mypy still red) |
| B1b | analytics spec + quality review | **accepted, no confirmed P0/P1** |
| B3 | seven `*_available` fields | **implemented + accepted** |
| MCP | dual strict-encoding candidates | **accepted**, 66 + 66 passed |
| C2 | API three-group PG-backed run | **accepted**, 93 passed |
| D3 | bundle budget decision + measurement | **measurement accepted, budget FAIL** |
| D3 | selective real G2 runtime probe | **pending — in progress, not accepted** |
| B4 | portal producer | **NOT DONE** |
| liveCH | ClickHouse lifecycle | **NOT DONE**, 36/37; the one failure is the item under repair |
| D5 / B2 | `site` column | **NOT APPROVED — does not start** |
| C3 | worker plan | **UNDECIDED** |
| production | Python 3.15 migration | **NOT APPROVED** |

### Build — `Makefile:211` path fix (accepted; the gate it feeds is still red)

`apps/api` has no `src/soymutdb/`; the package is `app/`. The single-line diff replaces the stale
path in the `typecheck` target. `git diff -U1 Makefile` shows **exactly one changed line** at
`Makefile:211`: `cd $(API_DIR) && mypy src/soymutdb/` -> `cd $(API_DIR) && mypy app/`.

- `make -n` (dry run): **passes** — the target now names a real directory.
- The real `mypy` run is **not green**: **179 errors across 61 files / 218 source files, exit 1**.

The path correction is accepted evidence; **typecheck as a gate is NOT DONE**. The `make -n` pass is
not a typecheck pass.

### B1b — independent spec and quality review: accepted, no confirmed P0/P1

Both reviews passed independently, with **no confirmed P0 or P1**.

Two earlier inferences are **withdrawn** and must not be carried forward:

1. The **Secure cookie** concern is withdrawn: `uvicorn --proxy-headers` plus the nginx
   `X-Forwarded-Proto` path already handle it.
2. The **ACAO** concern is withdrawn: CORS and `no-store` are orthogonal — a CORS header is not
   required for, and does not interfere with, the cache directive.

Accepted receipts:

- Analytics on the correct environment, the `py315` / `apps/api` venv at Python **3.15**:
  **239 passed**.
- OpenAPI contract, run independently: **21 passed**.
- **260** is the arithmetic total of those two runs. The prior author's *exact* commands are **not**
  asserted from that arithmetic; only the two independent pass counts are claimed.
- SDK: **155 tests / 28 files**.
- `check-contract.sh` with a temp dir, **read-only**, **PASS**.
- The earlier claim that no Python **3.15** or **httpx 2** support was required is **withdrawn**.
- `TestClient` inside the sandbox hangs; run **outside the same env** it **passes**. That is an
  environment/permission effect, not a product defect.

**B3** is **implemented and accepted** — seven `*_available` fields. This is **not** a single-flag
change and must not be recorded as one.

### MCP — two strict-encoding candidates, both fully green

| Candidate | Version | Result |
| --- | --- | --- |
| `.mamba-root/envs/py315/venvs/mcp-candidate` (3.15 candidate) | 3.15.0 | **66 passed, exit 0** |
| `.mamba-root/envs/py315/venvs/mcp-compat314` | 3.14.8 | **66 passed, exit 0** |

Both: zero skipped, zero xfailed, zero `EncodingWarning`. `uv lock --check`: **pass**.

Carried caveats: on **3.15** a `beartype` upstream `DeprecationWarning` is retained (upstream, not
ours). **Production pins were not changed, and no image was verified.** This is an isolation and
compatibility result only — it authorises no production pin movement.

### C2 — API against a temporary PostgreSQL (three groups, all green)

Temporary cluster at `/tmp/c2pg`, **PostgreSQL 16.15**. Three groups, all **exit 0**, zero skips:

| Group | Tests |
| --- | --- |
| A — `test_health_unit.py`, `test_public_id_service.py`, `test_analytics_privacy.py` | **11** |
| B — `test_mutants.py`, `test_search_database_integration.py`, `test_release_service.py` | **27** |
| C — `test_auth.py`, `test_auth_sessions.py` | **55** |
| **Total** | **93** |

The PostgreSQL process started for this run was **stopped** (its own PID). Limits that stay on the
record: **PG 16 is not CI's PG 18**; this is **not** the full API suite, **not** the security matrix,
and **not** an authentication-matrix sign-off.

### D3 — measurement accepted; the budget verdict is FAIL; migration still deferred

The user has **explicitly** stated **370 KiB** is the complete chart dependency budget, and the order
is: **optimise and re-measure until the measured result passes, then migrate.**

| Build | gzip size |
| --- | --- |
| Dual engine (ECharts + AntV) | **628,162 B** |
| Baseline (ECharts only) | **333,656 B** |
| `charts` group delta | **+294,506 B** |
| Vendor spill outside the group | **+129,804 B** |
| `ui` chunk | **+2,872 B** |
| **Complete AntV-attributable increment** | **427,182 B ~= 417 KiB** |
| Whole-JS net increase | **+429,791 B** |

Independent isolated measurement: **six chart types with no ECharts** give a real complete closure
floor of **427,466 B (417.45 KiB)** against the **378,880 B (370 KiB)** cap. The build succeeds but the
**budget gate FAILs**.

**Retracted inference**: the earlier "294 KiB is enough / it fits" reading must **not** be kept. It
measured only the `charts` cache group and under-counted the vendor spill by ~133 KB.

**G2 selective runtime probe** — a real, selective runtime probe **has been authorised by the main
Agent and is under implementation. Not accepted. A2–A6 have not started.**

### B4 — portal producer: NOT DONE

A new producer once reached **31 tests / `tsc` / lint passing**, but an **independent real router
check** found two defects: **six search sub-pages share a duplicated `routeId`**, which collapses
them, and `Image` **sends the original query by default referer**. The fix — full path, full
consumption, `no-referrer` — **is being executed now**. So **B4 is NOT DONE**, and the earlier 31-test
pass must not be read as acceptance.

PROD browser capability exists on this machine: **Playwright 1.62.1** and **Chromium 1234** are
available. **No Playwright run has been executed**, so there is no browser-level evidence yet.

### liveCH — ClickHouse lifecycle: NOT DONE

The earlier acceptance run gave **37 checks, 36 pass, 1 fail**. The single failure is **`AsyncClient`
has no `aclose`** — a close-lifecycle defect only. The fix in `core.database` / `test_db_pool_config`
**is under execution. NOT DONE**.

What genuinely passed: a real API run + `AsyncClient` + async insert landing on disk, and the summary
path with `GROUP BY` and sentinel checks. Do **not** claim a graceful stop: the original CH PID **no
longer exists and there is no listener** — the process is gone, which is not a clean shutdown.

**Pending receipt**: the exact absolute evidence directories for the liveCH run are **not yet
recorded**. To be supplied in a later append; they do not block the accepted rows above.

### Not approved / undecided — recorded so no later slice infers permission

- **D5**: **NOT APPROVED**. No additive `site` column; **B2 does not start**.
- **C3**: worker approach **UNDECIDED**.
- **Production Python 3.15 migration**: **NOT APPROVED**.

### Verified architecture boundaries (re-confirmed; must not be blurred)

1. **Routing**: Umi declares routes **explicitly** in `apps/web/config/config.ts`; entry is
   `umi-entry` -> `ReactApp`; routing is **TanStack**. `apps/web/src/routes/` is **not** scanned by
   Umi, which is why the parked A1 probe file was never in any webpack graph.
2. **Storage roles**: **PostgreSQL is authoritative** for identities, relationships, releases,
   permissions and workflow state; **ClickHouse is an analytical projection** of bulk variant facts;
   **MinIO** stores objects; **Redis** is disposable cache/broker state. No new authoritative store,
   and no SQLite on the production/full-development path.
3. **Shared contracts**: `packages/api-client` (generated from OpenAPI) and `packages/jobs-py` are
   the shared contract surfaces between the frontend and the Python services.
4. **Non-negotiable domains**: biological identity (`public_id` vs private `internal_id`),
   assembly-scoped coordinates and identifiers, release provenance, and the external/internal site
   boundary **must not be conflated**. A `site` value never decides the variant, and the variant is
   never inferred from host, IP, cookie or user agent.

### Carried into the next append

The final state of this workstream is **not** written here. D3's optimise-then-migrate loop, the G2
runtime probe, B4's router/referrer repair, liveCH's close-lifecycle repair, and the unapproved D5 /
C3 / production-3.15 decisions all remain **open**. A later append records the terminal state; this
interim ledger records only what is verified as of 2026-10-12 and marks everything else pending.


## Runtime stage update — 2026-10-12 (measurement accepted; budget PASS; render pending)

This append records the coordinator-supplied, independently accepted Runtime measurement.
Earlier A1/D3 pending tables are historical snapshots: their current-status reading is
**superseded by this latest append**. Their measured results remain intact. D3 currently has
**budget PASS / render pending**; the candidate's measurement is accepted, its functionality
is not yet accepted. The user requires the **370 KiB complete chart closure** to pass before
migration. **A2 does not start.**

### Selective Runtime implementation and build evidence

The selective G2 Runtime is implemented in `packages/charts/src/a1-runtime.ts` with six probe
samples. It uses direct `@antv/g2` at exactly **5.4.8**, without upgrading existing dependencies.
The `dist-a1-runtime` build completed with **exit 0**. Reported evidence locations:

- Stats: `/mnt/data02/T25ronglin/code/web/apps/.a1-runtime-stats.json`.
- Build log: `/mnt/data02/T25ronglin/code/web/apps/.a1-runtime.log`.

An independent explorer recomputed the complete chart dependency closure from the real chunk
graph. The accepted gzip measurement is:

| Closure component | gzip bytes |
| --- | ---: |
| charts | 236,052 |
| vendor chunk 46 | 79,072 |
| probe chunk 292 | 2,034 |
| route chunk 352 | 460 |
| **Complete chart closure** | **317,618 (310.17 KiB)** |
| Budget | 378,880 (370 KiB) |
| **Remaining budget** | **61,262** |

**Budget verdict: PASS.** All eight JavaScript assets total **459,527 B (448.76 KiB)**.
Platform initial JavaScript is **141,909 B**, contains no chart dependencies, and is excluded
from the chart closure budget. This is explicitly a **chart dependency budget**, not a page
JavaScript budget. No plots, ECharts or zrender runtime module is present in this build.

### Runtime capabilities and corrected dependency interpretations

The Runtime registers **65 components**, including capabilities for the six samples. This
is not evidence that only six required modules were bundled. The six samples map to **five
marks**: `interval`, `line`, `area`, `cell`, and `point`; the heatmap uses categorical **Cell**.
No claim of an exact six-module minimal Runtime is made.

React and ReactDOM actually resolve to **19.3.0**, with one resolved entity each. The earlier
**18.3.1** interpretation came from an unused dependency peer suffix and is **withdrawn**.

The default `@soymutdb/charts` entry (`index`) contains only `ChartFigure` and definitions.
Its ECharts imports are type-only and erased. Manifest dependency declarations do not
automatically bundle both engines. Earlier inferences that the default entry automatically
pulls plots or ECharts into the bundle are **withdrawn**.

### Measurement stages remain distinct

| Stage | gzip measurement | Accepted interpretation |
| --- | ---: | --- |
| Earlier dual-engine build | 427,182 B | AntV-attributable increment across charts, vendor and UI; historical over-budget result retained |
| Earlier isolated plots-only instrument | 427,466 B | Complete closure without ECharts; historical budget FAIL retained |
| New selective G2 Runtime | 317,618 B | Complete closure from the real chunk graph; current budget PASS |

These are different measurement stages. The new Runtime result does **not** invalidate or
rewrite either historical over-budget measurement. The former 294 KiB cache-group-only
estimate remains withdrawn; the current PASS uses the full dependency closure.

### Acceptance still pending

Real browser **render, tooltip, update, unmount and React 19** acceptance has **not passed**.
The successful build and accepted closure measurement do not establish those behaviours.
The selective Runtime remains a candidate pending functionality acceptance; **A2 is not
started**. **B4 and the `close_db` repair remain pending**, with neither marked DONE by this
append. No unknown receipt or other-agent response was awaited for this record.

## Python 3.15: main-agent takeover and full API verification (2026-10-13)

The user requested that the main agent take over execution. This append supersedes earlier
Python candidate test counts where a fresh result is given; historical receipts above remain
unchanged. It does not mark the chart migration or production Python promotion complete.

### Repairs made directly by the main agent

- Seven offline Alembic test helpers injected `apps/api/.venv/lib/python*/site-packages`
  into a subprocess launched with `sys.executable`. On this machine that mixed Python 3.14
  binary extensions with the Python 3.15 candidate, causing 18 failures. Remove that injected
  dependency directory; the subprocess now uses its own interpreter's dependencies. Keep
  the API/workspace source paths and all migration assertions.
- Specify UTF-8 for the affected subprocess text output and test fixture reads. Thirteen
  API test files changed in this takeover; no application, migration SQL, lockfile, or
  production interpreter pin changed.

### Fresh API results

Interpreter: `.mamba-root/envs/py315/venvs/api/bin/python`, Python 3.15.0.
Workdir: `apps/api`. PostgreSQL: isolated `/tmp/c2pg/data`, PostgreSQL 16.15, loopback
port 55432, database `soymutdb_c2`. **Local PostgreSQL 16 is not CI PostgreSQL 18.**

```bash
env SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_c2 \
  SOYMUTDB_RUN_POSTGRES_INTEGRATION=1 \
  PYTHONPATH=/mnt/data02/T25ronglin/code/web \
  /mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/api/bin/python \
  -m pytest tests -q -p no:cacheprovider --tb=short
```

Result: **2294 passed, 50 warnings, exit 0**, 57.75 seconds; no skipped or xfailed cases.
This includes the PostgreSQL tests selected by the suite. Redis/ClickHouse/S3 fixtures remain
the suite's existing doubles; this is not a live ClickHouse shutdown or container gate.

With `-X warn_default_encoding -W error::EncodingWarning` before `-m pytest`, the same full
suite gives **2292 passed, 2 failed, 52 warnings, exit 1**, 57.61 seconds. Both remaining
failures are `test_module_schema_registry.py` XLSX tests: openpyxl 3.1.5's
`worksheet/_writer.py:create_temporary_file()` calls `NamedTemporaryFile(mode='w+')`
without an encoding. The repository callers now pass the strict gate; the upstream failures
are retained, not suppressed, skipped, or represented as a strict-mode pass.

Durable, gitignored receipts:

- `.cache/python315-main-20261013/api315-main-full.log`
- `.cache/python315-main-20261013/api315-main-strict.log`

Ruff passes on 12 modified test files. `test_migrate_clickhouse.py` has the same three lint
findings as HEAD (I001 and two E501 findings); the encoding-only change introduces none.
`git diff --check` passes for the thirteen changed test files. The repository-wide check
still reports existing trailing blank lines in three admin chart files outside this slice.

The temporary PostgreSQL was stopped with `pg_ctl -D /tmp/c2pg/data -m fast -w stop`:
exit 0, `server stopped`. No production or existing development database was modified.

### MCP and worker boundaries

The fresh independent MCP receipt has **66 passed on 3.15.0 and 66 passed on 3.14.8**,
both exit 0 under `-X warn_default_encoding -W error::EncodingWarning`, with zero
EncodingWarning. The 3.15 warning audit exposes one upstream beartype DeprecationWarning.
Containerized MCP E2E/image acceptance remains unrun.

The main agent inspected the worker candidate directly: Python 3.15.0, **zero installed
distributions**. The earlier locked source-build probes did not complete an install
transaction. They must not be counted as a worker migration or test pass.

Two dependency restrictions prevent a supported locked promotion today:

1. Locked numba 0.67.0's real `setup.py` has an exclusive Python 3.15 upper guard.
   A compatible numba/llvmlite upgrade must be resolved and tested together; skipping those
   packages in diagnostic probes does not satisfy the scientific stack gate.
2. The installed API clickhouse-connect 1.7.0 metadata itself declares `>=3.10,<3.15`.
   The checked latest release 1.10.0 also declares `<3.15,>=3.10` in
   [official PyPI metadata](https://pypi.org/pypi/clickhouse-connect/1.10.0/json).
   A pre-existing candidate environment passing tests is **not** proof that a fresh locked
   install is supported. No driver compatibility guard was bypassed in this takeover.

The PyArrow/Gandiva and other build-tool issues in the earlier probes are separate from
these version restrictions. chdb-core's abi3 wheel availability is not itself a hard block;
its actual 3.15 runtime remains unverified. No scientific dependency was removed, no
split-runtime architecture introduced, and no production/CI Python pin changed.

**Status:** API standard suite and MCP candidate tests accepted within the stated limits.
API strict encoding gate, fresh-install dependency compatibility, worker scientific stack,
live ClickHouse shutdown, image/CI acceptance and formal Python 3.15 promotion remain open.

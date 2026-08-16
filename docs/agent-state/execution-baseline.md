# SoyMutDB Next — Execution Baseline (QA / Phase 5)

> Captured by `qa-verify` (task t1) as the pre-execution quality gate for the
> AgentsTeams run "soymutdb-execution" (Phase 2 admin page builder, Phase 3
> static multi-target publication, Phase 4 public web UI refactor).
>
> This is a **live snapshot of a moving working tree**: teammates
> (admin-builder, publish-core, ui-frontend) were already editing files when
> this baseline was captured. Failures flagged here are therefore *pre-existing
> or in-flight*, not regressions introduced by QA.

- **Captured:** 2026-08-16 15:22 +0800
- **Git:** branch `main`, HEAD `91f4f8f97`
- **Environment:** Node v26.6.0, pnpm (store broken — see §0), Python 3.14.6
  (`apps/api/.venv`, `apps/worker/.venv`), Docker **not available**.

---

## 0. Environment blocker: pnpm store is unusable

`pnpm` (globally and via `turbo run`) fails with
`ERROR: unable to open database file` (SQLITE_CANTOPEN, errno 14) on the
content-addressable store `~/.local/share/pnpm/store/v11/index.db`. The store's
`index.db` is present and `file` reports it valid, but SQLite cannot open it
(verified `sqlite3 … "SELECT count(*) FROM files;"` → same error). Same error
for `pnpm store path` and every `turbo run <task>`.

Consequences:
- **CI-style `pnpm … typecheck` / `pnpm … test` / `turbo run` cannot run in this
  shell.** I worked around it by invoking the package-local binaries directly
  (`node_modules/.bin/tsc`, `vitest`, `eslint`, `openapi-typescript`) — no pnpm
  invocation. All results below were produced that way.
- This is an **environment** issue in the user's global pnpm store, not a repo
  issue. I did **not** modify the global store (repairing/rebuilding it is
  destructive and out of scope for a baseline). Recommend a non-destructive fix
  (`pnpm store status` / `pnpm store prune` / recreate store) before any CI
  runner relies on pnpm.

---

## 1. Typecheck — summary

Per-package `tsc --noEmit` (direct binary; `packages/shared` has no `scripts`
and no local `tsc`):

| Package | Exit | Errors | Status |
|---|---|---|---|
| `packages/motion` | 0 | 0 | ✅ |
| `packages/i18n` | 0 | 0 | ✅ |
| `apps/admin` | 0 | 0 | ✅ |
| `apps/jbrowse` | 0 | 0 | ✅ |
| `apps/web` | 2 | **14** | ❌ contract drift |
| `packages/ui` | 2 | **64** | ❌ test typings |
| `packages/api-client` | 2 | **345** | ❌ test typings + 1 real |
| `packages/shared` | n/a | — | no tsc/scripts |

### 1.1 `apps/web` — 14 errors (real contract drift)

The client is out of sync with the backend OpenAPI (see §3). Representative
errors:

- `src/routes/blast.tsx`, `genes/index.tsx`, `variants/index.tsx`,
  `search/genes.tsx`: `Object literal may only specify known properties, 'page'
  does not exist` and `Property 'total' does not exist` — pagination params
  `page`/`total` present in callers but missing from the generated client types.
- `src/routes/search.tsx`: `'@soymutdb/api-client' has no exported member named
  'FederatedSearchResponse'` and `Property 'sources' does not exist`.
- `src/routes/login.tsx`: unsafe cast warning.

These all trace to §3 (stale `src/generated/openapi.d.ts`).

### 1.2 `packages/api-client` — 345 errors (mostly test-file typings)

Breakdown: `244× TS2304` (missing `expect`/`vi`/`beforeEach`/…), `97× TS2582`
(`describe`/`it`), `2× TS7006`, `1× TS2345`, `1× TS2339`.

All but **one** are in `*.test.ts` files (`client.test.ts` 150,
`auth.test.ts` 69, `analyses.test.ts` 43, `tools.test.ts` 36, …). Root cause:
`tsconfig.json` uses `"include": ["src"]` which sweeps in `*.test.ts`, but vitest
globals are not configured for `tsc` (no `types: ["vitest/globals"]`, tests rely
on vitest's runtime globals). The one **real** error:

- `src/client.ts:23` — `Property 'env' does not exist on type 'ImportMeta'`
  (needs `vite/client` or `import.meta.env` typing).

**Resolution option (not performed in baseline):** exclude `**/*.test.*` from
`tsc`, or add vitest globals, then fix `client.ts`.

### 1.3 `packages/ui` — 64 errors (all `TS2339`)

All 64 are `Property 'toHaveTextContent' / 'toBeInTheDocument' does not exist on
type 'Assertion<HTMLElement>'` in `states.test.tsx` and `toast.test.tsx`. The
`@testing-library/jest-dom` matcher types are not picked up by `tsc` (vitest
setup file registers them at runtime only). **Test typings issue, not runtime.**

---

## 2. Python typecheck — summary

The `Makefile` `typecheck` target calls `mypy src/soymutdb/` for the API, but the
API package layout is `app/` (not `src/soymutdb/`), so the Makefile path is a
**no-op** (`Cannot read file 'src/soymutdb'`). I ran the correct paths directly.

| Package | Command | Errors |
|---|---|---|
| `apps/api` | `mypy app/` | **115** (113 unique) |
| `apps/worker` | `mypy src/` | **49** |

### 2.1 `apps/worker` — 49 errors; 1 critical

- **`src/soymutdb_worker/tables.py:88-91`** — malformed `Table(...)` call:
  `import_tasks = Table("data_sets", "import_tasks", "module_data_rows", metadata, …)`
  passes three table names plus `metadata` as positional args. This makes
  `metadata` bind to the `schema` parameter → `AttributeError: 'str' object has
  no attribute 'schema'` **and blocks the entire worker test suite at import**
  (see §4). This is an in-flight edit (likely Phase 3 static-publish work).
- 18× `import-untyped` (celery, dominate, scanpy, cyvcf2 — stub gaps, benign).
- 6× `import-not-found` incl. `soymutdb_jobs.module_schema` (new in-flight
  module), 6× `call-arg` in `ingest.py` (`info(import_task_id=…)` keyword args
  on stdlib `Logger`), 1× `no-any-return`.

### 2.2 `apps/api` — 115 errors

Breakdown: 25× `arg-type`, 22× `no-any-return`, 18× `call-arg`, 11×
`import-untyped`, 9× `attr-defined`, 7× `assignment`, 6× `import-not-found`,
6× `dict-item`, 3× `index`. Notable clusters:

- `app/widgets/router.py` — `PageLayout` vs `Widget` confusion
  (`_widget_to_descriptor` arg type, `.name`/`.permissions` attr-defined) +
  `WidgetResponse` enum-typed fields.
- `app/api/v1/admin.py` — SQLAlchemy result vs row attribute accessor confusion.
- `app/main.py` — exception-handler / mount signatures.

These are broadly **pre-existing typing debt** (not verified crash bugs), several
in Phase 2/3 surfaces currently being edited.

---

## 3. OpenAPI contract check (api-client) — DRIFT ⚠️

Ran `apps/api/scripts/export_openapi.py` → fresh `openapi.json`, then
`openapi-typescript` → fresh `openapi.d.ts`, and diffed against the committed
`packages/api-client/src/generated/openapi.d.ts`.

**Result: CONTRACT DEBT — 1141 diff lines (committed client is stale).**

The committed `openapi.d.ts` is **missing** backend routes/schemas that now
exist (in-flight work, not yet regenerated):

- Routes: `/api/v1/admin/publications` (list/create),
  `/api/v1/admin/publications/{publication_id}` (update/delete),
  `/api/v1/admin/modules/{module_key}/template` (download template).
- Schemas: `PublicationCreate`, `PublicationUpdate`, `PublicationListResponse`,
  paginated widget list (`WidgetListResponse.items`, `/widgets` now paginated),
  `module_key` params, etc.

This is exactly why `apps/web` fails typecheck (§1.1). **Action for the team:**
once Phase 2/3 backend routes are merged, run
`pnpm --filter @soymutdb/api-client generate:api-client` (or the underlying
`export_openapi.py` + `openapi-typescript`) and re-commit the generated client
so the web UI typechecks against the new contract.

(Note: `check-contract.sh` normally uses `apps/api/.venv/bin/python` and
`pnpm exec openapi-typescript`; the pnpm part fails here due to §0, so I invoked
`openapi-typescript` directly.)

---

## 4. Frontend tests (vitest) — PASS ✅

Direct `vitest run` (no pnpm):

| Package | Files | Tests | Result |
|---|---|---|---|
| `packages/api-client` | 10 | 76 | ✅ all pass |
| `apps/web` | 3 | 35 | ✅ all pass |
| `packages/ui` | 6 | 46 | ✅ all pass |
| `apps/admin` | 2 | 16 | ✅ all pass |

**Frontend total: 21 files, 173 tests, 0 failures.**

Notes:
- `packages/ui` and `apps/admin` use vitest v4 (no `--reporter=basic`; earlier
  run with that flag crashed on the missing `basic` reporter — cosmetic only).
- `packages/ui` logs a `<tbody> cannot contain nested <div>` DOM warning from
  the `data-table` component (runtime-invalid markup; tests still pass).

---

## 5. Backend tests (pytest) — partial; Docker unavailable

`PYTHONPATH=<repo-root> pytest -q` (the `tools` import in `tests/a0/*` requires
repo root on `PYTHONPATH`, which the Makefile `test-api` does not set — another
Makefile gap).

### 5.1 `apps/api` — **888 passed, 39 failed, 65 errors**

- **65 errors** are `docker.errors.DockerError` — testcontainers cannot start
  PostgreSQL because **Docker is not available** in this environment. All
  DB-backed integration tests (auth, genes, variants, search, health, etc.)
  error out at fixture setup. **Not code failures** — environment limitation.
- **38 failures** are in `tests/a0/*` (release-lifecycle "RL" contract tooling):
  real assertion mismatches in `rl_gate_evidence` / `rl_reviewer_attestation` /
  `rl_schema_reconciliation` (finding-text drift). Pre-existing, committed
  (`git ls-files` confirms `tools/a0/` and `tests/a0/` are tracked).
- **1 failure** is the `tables.py` bug fallout:
  `test_task_contract.py::test_api_blast_task_name_is_registered_by_worker`
  (crashes importing `soymutdb_worker.tables`).

### 5.2 `apps/worker` — **0 collected; 7 collection errors**

Every worker test that imports `soymutdb_worker.repositories` (→ `tables.py`)
fails at collection with the same `AttributeError: 'str' object has no attribute
'schema'`. **The worker test suite is 100% blocked** by the `tables.py:88`
malformed `Table(...)` call (§2.1). This must be fixed before Phase 3
(static-publish) can be validated.

---

## 6. Lint (eslint) — summary

| Package | Errors | Warnings |
|---|---|---|
| `apps/web` | **8** | 42 |
| `apps/admin` | 0 | 18 |
| `packages/ui` | 0 | 2 |
| `packages/api-client` | 0 | 4 |
| `packages/motion` | 0 | 3 |
| `packages/i18n` | 0 | 0 |

`apps/web` errors: 1× `no-restricted-imports` (`@soymutdb/ui` is frozen/retired —
upgrade-plan §二; the file awaiting migration to AntD 5), several
`@typescript-eslint/no-unused-vars`, `react-hooks/set-state-in-effect`, and one
`Cannot create components during render`. These intersect the Phase 4 UI-refactor
scope (ui-frontend) — handoff below.

---

## 7. E2E — enumerated, not executed

`e2e` has 25 Playwright tests in 2 files (`online-smoke.spec.ts` [route render +
console-error checks], `primer-design.spec.ts`). **Not run**: they require a
live web server / API and Dockerless infra; out of scope for this baseline. Will
run as part of Phase 5 end-to-end acceptance once the web UI and a running
environment are available.

---

## 8. Priority findings for the team (actionable)

1. **🔴 `apps/worker/src/soymutdb_worker/tables.py:88` — malformed `Table(...)`
   call breaks worker imports.** Blocks the entire worker test suite (7
   collection errors) and `test_task_contract.py`. Whoever is editing `tables.py`
   (publish-core, Phase 3) must fix this immediately.
2. **🟠 OpenAPI client drift (1141 lines).** Regenerate
   `packages/api-client/src/generated/openapi.d.ts` after Phase 2/3 backend
   routes land; this unblocks `apps/web` typecheck (14 errors).
3. **🟠 `apps/api` RL gate tooling (`tests/a0/*`) has 38 failing assertions**
   (finding-text drift in `rl_gate_evidence` etc.). Pre-existing, needs a
   separate triage; not on the Phase 2-4 critical path but will gate release.
4. **🟡 Test-file typings** (`packages/api-client` 345, `packages/ui` 64):
   `tsc` sweeps `*.test.ts` without vitest globals / jest-dom matcher types.
   Cosmetic to `tsc` but makes typecheck red; exclude test files or add globals.
5. **🟡 Makefile drift:** `typecheck` runs `mypy src/soymutdb/` (should be
   `app/`); `test-api` omits `PYTHONPATH=repo-root` (needed by `tests/a0/*`).
6. **🟡 Environment:** pnpm store broken (§0) — CI/local must repair before
   relying on `turbo run` / `pnpm run`.

## 9. Baseline numbers (quick reference)

| Gate | Result |
|---|---|
| Frontend (vitest) | ✅ 21 files / 173 tests / 0 fail |
| Backend API (pytest) | ⚠️ 888 pass / 39 fail / 65 docker-errors |
| Backend worker (pytest) | 🔴 blocked at collection (tables.py bug) |
| TS typecheck | ❌ web 14, ui 64, api-client 345 (rest 0) |
| Python mypy | ❌ api 115, worker 49 |
| OpenAPI contract | ⚠️ drift (1141 diff lines) |
| ESLint | ⚠️ web 8 errors; others warnings only |
| E2E | not run (needs live env) |

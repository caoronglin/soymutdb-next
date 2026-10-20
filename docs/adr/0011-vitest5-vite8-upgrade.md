# ADR-0011: upgrade Vitest 3 → 5 and Vite 6 → 8 (test tooling)

Status: accepted (2026-10-18)
Context: ADR-0010 held the remaining major upgrades. The largest single risk in
that hold list was the test substrate: Vitest 3.2.7 powered 1071 unit tests
across ten workspace projects, and Vite 6.4.3 was its engine. Both were two
majors behind (`vitest` 5.0.5, `vite` 8.3.4 upstream at the time of writing),
and the tree was green on every gate before the change, so the migration could
be verified behavior-for-behavior.

Decision: take the Vitest 5 + Vite 8 upgrade in this release, as the first item
of the ADR-0010 follow-up order.

Changes:

* `pnpm-workspace.yaml` catalog: `vitest` 3.2.7 → **5.0.5**, `vite` 6.4.3 →
  **8.3.4**. Packages that pinned `vitest` outside the catalog
  (`api-client`, `genome-view-model`, `i18n-core`, `query-keys`, `shared`) now
  use `catalog:` so the version cannot drift again.
* Vitest 5 removed `poolOptions`: every one of the ten `vitest.config.ts`
  files moved from `poolOptions.forks.singleFork` to
  `pool: "forks", maxWorkers: 1`. Per-file isolation stays **on** (the default):
  test files share module mocks and globals (`globalThis.React`, `vi.mock`
  factories), and running them non-isolated in one worker made
  `admin-command-palette.test.tsx` and `module-import-upload.test.ts` fail with
  another file's state. The serial worker keeps the sandbox resource profile
  while preserving isolation.
* Vite 8 transforms with Oxc instead of esbuild, and Oxc refuses the
  `"jsx": "preserve"` that the shared tsconfig keeps for the Umi build
  (`Error: ... content contains invalid JS syntax ... make sure to not set jsx
  to preserve`). Every JSX-bearing project config now sets
  `oxc: { jsx: { runtime: "automatic" } }`; the application build is untouched.
* `scripts/test_platform_delivery_contracts.py` PLATFORM_CATALOG moves to
  `vite 8.3.4` / `vitest 5.0.5`, and the dated validation report commands were
  updated from the removed `--poolOptions.forks.singleFork` flag to
  `--maxWorkers=1` so they remain runnable.

Evidence (local, all green after the change):

* `turbo run test`: **11/11 tasks, 1071 tests** (web 373, admin 172,
  api-client 184, genome-data 121, charts 84, shared 49, genome-view 43,
  genome-view-model 23, i18n-core 11, query-keys 11).
* `turbo run lint typecheck`: all workspace tasks pass.
* Platform contract suite: 37 passed (catalog pins asserted).
* Requires Node ≥ 22.12 (Vitest 5) / Vite's Node floor; the repo pins Node 26.
  Vite 8 is ~15 MB larger (Rolldown + lightningcss); it is a dev dependency, so
  no artifact or runtime change.

Consequences:

* the unit-test substrate is current for the next two majors, and the upgrade
  order in ADR-0010 advances to i18next 26 / react-i18next 17;
* the production build is unchanged (Umi/webpack); Vite 8 only affects Vitest's
  transform pipeline;
* `pnpm peers check` still reports the pre-existing Umi/webpack peer gaps; none
  of the 11 findings involve vite or vitest.

Rollback: revert the catalog bumps, the ten config files, the platform contract
pins and the lockfile; no persisted data or runtime contract is involved.

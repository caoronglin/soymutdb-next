# Dependency governance

## Current JS patch observation — 2026-10-25

Subsequent user-authorized verification on Node 26.13.0 / pnpm 12.11.2 / Python 3.15.0 rebuilt both portal variants, admin and JBrowse successfully, passed their scoped regression/type/lint and artifact checks, and repeated the acceptance-policy readback on the same audit JSON using Python 3.15. **The frontend translation-test-double contract still fails on 10 test files**, so this is not a full green pipeline. See the [integration verification receipt](../../.cache/integration-verification-20261025/SUMMARY.md); no database, server, install or Git mutation was performed in that verification lane.

This dated observation supersedes older live-status statements below; the earlier batch records remain historical. The workspace now pins `body-parser: 1.20.9` and `fast-uri: 3.1.9`, retaining the follow-redirects/hono floors and parent-scoped Vite override. The interrupted implementation left successful lock-delta, frozen-install and dedupe logs; peer checking still exited 1.

A fresh **full-severity** npm-registry audit reports **3 advisories: 0 high/critical, 2 moderate (react-router), 1 low (elliptic)** and exits **1**. Evaluating that same JSON with the unchanged repository policy and the real **empty** acceptance list passes the high/critical gate with no accepted findings. This is not a full governance-job or workspace pass. No new acceptance or release-age exception was introduced. The stale braces acceptance was previously removed with explicit user authorization; earlier sections describing it as live must not be read as current policy.

Evidence: [recovery receipt](../../.cache/direct-recovery-20261025/SUMMARY.md), [audit JSON](../../.cache/direct-recovery-20261025/audit-full.json), [policy evaluation](../../.cache/direct-recovery-20261025/gate-evaluation.json). Policy readback used Python 3.14.9, not the project 3.15 pin. Existing vendored `body-parser` inside Umi is outside the npm dependency graph and cannot be cleared by these overrides or audit results. Runtime reachability, peer remediation, new artifact builds and full regression remain unverified by this observation.

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
| `follow-redirects` | 1.16.1 | GHSA-q3jh-wrc6-jgq8, GHSA-8r9p-f939-6h3c (credential headers survive a cross-origin redirect; reached through `axios`) |
| `hono` | 4.13.11 | GHSA-5r4p-p66f-jhc7 (`serveStatic` decodes the request path a second time; reached through `@utoo/pack`) |
| `vite` (only under `@umijs/bundler-vite`) | 7.3.7 | GHSA-587h-7wmj-h5pm and four more `vite` advisories; parent-scoped override, see "Targeted Vite patch" |

The `follow-redirects` and `hono` floors were added together as one batch. Both
are exact pins on transitive packages; neither is a direct dependency of any
workspace project, so the floor lives in `overrides` rather than in a manifest.
Verified in the installed sources: `follow-redirects` 1.16.1 normalises
array-form headers into an object before the credential-stripping routine and
extends `escapeRegex` to escape `[`, `^` and `|`; `hono` 4.13.11 rejects a
request path that still contains `%` after routing decoding.

The `vite` floor is an exact pin as well, but it is parent-scoped
(`"@umijs/bundler-vite>vite": 7.3.7`) because a workspace-wide `vite`
override would rewrite the `vite` peer declarations of `vitest` and
`@vitejs/plugin-react` and downgrade vitest's resolved engine. The reason,
the measured lock delta and the audit result are in "Targeted Vite patch"
below.

Direct dependencies are raised in the owning manifest instead — `@tiptap/*` is a
direct Admin dependency, so its floor lives in `apps/admin/package.json`.

`pnpm dedupe --check` is a blocking gate. Because the overrides above change the
resolved graph, the lockfile must be regenerated (`pnpm dedupe`) in the same
commit, or the gate reports `[ERR_PNPM_DEDUPE_CHECK_ISSUES]`.

## Accepted residual advisories (`pnpm audit`, reviewed 2026-10-18)

> Historical record. The list below is what the registry feed reported on
> 2026-10-18. The current observation is in "Audit state after the
> `follow-redirects` / `hono` batch" below; the two lists differ, and the
> difference is explained there.

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

## Audit state after the `follow-redirects` / `hono` batch (observed 2026-10-24)

`pnpm audit --registry https://registry.npmjs.org/ --json` was run against the
baseline lockfile and against the lockfile produced by this batch:

| Lockfile | Advisories | high | moderate | low |
| --- | --- | --- | --- | --- |
| Baseline (`follow-redirects` 1.16.0, `hono` 4.13.9) | 11 | 3 | 6 | 2 |
| This batch (`follow-redirects` 1.16.1, `hono` 4.13.11) | 8 | 1 | 5 | 2 |

The batch removed exactly three findings and introduced none:

| Advisory | Package | Severity | State after this batch |
| --- | --- | --- | --- |
| GHSA-q3jh-wrc6-jgq8 | `follow-redirects` | high | resolved by the 1.16.1 floor |
| GHSA-8r9p-f939-6h3c | `follow-redirects` | high | resolved by the 1.16.1 floor |
| GHSA-5r4p-p66f-jhc7 | `hono` | moderate | resolved by the 4.13.11 floor |

The eight findings that remain are identical before and after the batch:

| Package | Severity | Path | Why it is still open |
| --- | --- | --- | --- |
| `vite` 7.3.6 | high | Umi 4 → `@umijs/bundler-vite` → `vite` | GHSA-587h-7wmj-h5pm. A patched 7.3.7 exists, but a workspace-wide `vite` range override was deliberately excluded from this batch because it also rewrote the `vite` peer declarations of `vitest` and `@vitejs/plugin-react`. It needed its own reviewed decision; that decision was taken afterwards and is recorded in "Targeted Vite patch" below. |
| `vite` 7.3.6 | moderate ×3, low ×1 | same paths | GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22, GHSA-9jrq-w75r-8gcw. Same cause and same follow-up decision as the `vite` row above. |
| `react-router` 6.30.6 | moderate ×2 | Umi 4 renderer/server | GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg. Fixed only in `>=7.18.0`; Umi 4 does not support that major. The shipped SPA uses TanStack Router. |
| `elliptic` 6.6.1 | low | Umi → `crypto-browserify` bundler shim | GHSA-848j-6mx2-7j84. No patched release; development bundling only. |

Two packages this file still listed on 2026-10-18 — `braces` 3.0.3
(GHSA-vfj7-8cjw-p6xm) and `sprintf-js` 1.1.3 — are still in the lockfile, but
the registry advisory feed did **not** report them on 2026-10-24. That is a
change in what the feed reported, not evidence that the packages are safe: a
package the audit does not mention has only not been reported, and a package
the audit does mention may still be unreachable in this repository.
`security/advisory-acceptances.json` still carries the `braces` entry, and that
file's own policy fails an acceptance which no longer matches a reported
finding, so the entry needs its own review. Both packages are outside this
batch's write scope.

`pnpm audit` exits non-zero on this tree because of the `vite` high finding.
The exit code is a finding count, not an execution result: this batch was
verified by the count change (11 → 8) and by the disappearance of the three D1
advisories, not by a zero exit code. The `vite` high was cleared afterwards by
the targeted slice recorded below; this paragraph describes the D1 batch
alone.

### `@hono/node-server` keeps its own `serveStatic` (recorded limitation)

The `hono` floor fixes Hono's own `serveStatic` middleware: in 4.13.11,
`dist/middleware/serve-static/index.js` rejects a request path that still
contains `%` after routing decoding (the `allowPercentInPath` guard), so a
crafted path can no longer be routed as one path and served as another.

`@hono/node-server@1.19.17` ships a **separate** `serveStatic`
(`dist/serve-static.mjs`). Its `filename = tryDecodeURI(c.req.path)` still
performs that second decode, and the file contains no `allowPercentInPath`
guard. Raising `hono` does not change `@hono/node-server`, so that copy is
**not** fixed by this batch.

- **Where it is reached:** `@utoo/pack@1.5.26` declares
  `"@hono/node-server": "^1.19.11"` and imports `serveStatic` from
  `@hono/node-server/serve-static` in its `dev` command
  (`esm/commands/dev.js`), mounting it as
  `app.get("/*", serveStatic({ root: distRoot, rewriteRequestPath }))`.
- **Trigger condition:** the Umi 4 development server serving a request whose
  path still contains a percent-encoded sequence after Hono's routing decode.
  `@hono/node-server@1.19.17` is the newest `1.x` release; a `2.x` line exists
  but `@utoo/pack` declares `^1.19.11`, so any fix is a separate decision.
- **Scope:** the development server only. `root` is the build output directory,
  and the published portal/admin artifacts are not produced through this code
  path.
- **No advisory ID is claimed for this copy.** The three advisories above
  cover `hono` and `follow-redirects`, and the npm advisory feed reported
  nothing for `@hono/node-server@1.19.17` on 2026-10-24. The limitation is
  recorded from the package source, not from an advisory.

Review trigger: an upstream `@hono/node-server` release that carries the same
guard as `hono` 4.13.11, or a Umi/`@utoo/pack` upgrade that moves off the
`1.x` line.

## Targeted Vite patch (D1 follow-up slice, observed 2026-10-24)

The `vite` high finding that the D1 batch left open was cleared by its own
reviewed slice, on the same three-file surface: `pnpm-workspace.yaml`,
`pnpm-lock.yaml` and this document. No manifest, source file or risk
acceptance was touched.

### Why the override is parent-scoped

`vite` 7.x is reachable in this tree through two package-graph edges: the
`@umijs/bundler-vite@4.7.24` → `vite` dependency, and the
`@vitejs/plugin-react` peer context that edge carries. The package graph
carries four resolved `vite` dependency edges in total, and this slice
changed **two** of them — the bundler's direct edge and the plugin-react peer
context. The two `vite` 8.3.4 edges are unchanged:

| Edge | Before | After |
| --- | --- | --- |
| `@umijs/bundler-vite@4.7.24` → `vite` | 7.3.6 | **7.3.7** |
| `@vitejs/plugin-react@5.2.0` → `vite` (peer context) | 7.3.6 | **7.3.7** |
| `vitest@5.0.5` → `vite` (peer context) | 8.3.4 | 8.3.4 |
| `@vitest/mocker@5.0.5` → `vite` (optional dependency) | 8.3.4 | 8.3.4 |

The three peer **range** declarations (`@vitejs/plugin-react`,
`@vitest/mocker`, `vitest`) are byte-identical before and after.

The three app-level importers (`apps/web`, `apps/admin`, `packages/charts`) also
take `vite` from the catalog at 8.3.4.

A workspace-wide `vite` override was therefore rejected: it would also have
rewritten the `vite` peer declarations of `vitest` 5.0.5
(`^6.4.0 || ^7.0.0 || ^8.0.0`) and `@vitejs/plugin-react` 5.2.0
(`^4.2.0 || ^5.0.0 || ^6.0.0 || ^7.0.0 || ^8.0.0`), and it would have
downgraded vitest's resolved engine from vite 8.3.4 to a 7.x copy — a new
major downgrade on the test substrate. The applied override is a
parent-scoped selector, which moves exactly the two edges listed above (the
bundler's own `vite` dependency and the plugin-react peer context it carries)
and nothing else — the peer ranges and vitest's 8.3.4 edge are untouched:

```yaml
overrides:
  "@umijs/bundler-vite>vite": 7.3.7
```

The parent is deliberately **not** version-qualified;
`"@umijs/bundler-vite@4.7.24>vite"` was the rejected alternative. An
unqualified parent keeps the floor applied after a future `@umijs/bundler-vite`
upgrade instead of silently ceasing to apply and letting vite 7.3.6 return.
The residual risk of the unqualified form is that a future major of
`@umijs/bundler-vite` would also be bound by the floor; that risk is bounded
because the child stays an exact pin (7.3.7), so a future parent can change
only *which* package carries the floor, not the floor itself.

### Lockfile delta (measured)

| | Before | After |
| --- | --- | --- |
| `packages` entries | 1880 | 1880 |
| `snapshots` entries | 1886 | 1886 |
| importers | 14 | 14 |
| resolved `vite` versions | 7.3.6, 8.3.4 | **7.3.7**, 8.3.4 |
| `overrides` entries | 24 | 25 (exactly one added, none removed or edited) |

The complete lockfile diff is 65 lines in four classes: the new `overrides`
line; the `vite@7.3.6` → `vite@7.3.7` resolution including its integrity
hash; the `@umijs/bundler-vite` → `@vitejs/plugin-react` peer-context suffix
and its `vite:` edge; and the `@vitejs/plugin-react` snapshot key plus its
`vite:` edge. `vitest@5.0.5`'s peer declaration and `@vitejs/plugin-react@5.2.0`'s
peer declaration are byte-identical before and after, every importer block is
byte-identical, and the two `vite` 8.3.4 edges (vitest's and
`@vitest/mocker`'s) are untouched.

### Commands and results

| Command | Exit | Note |
| --- | --- | --- |
| `pnpm install --lockfile-only` | 0 | lockfile regenerated by pnpm itself; `✓ Lockfile passes supply-chain policies (1880 entries)` |
| `pnpm install --frozen-lockfile --ignore-scripts` | 0 | `Lockfile is up to date, resolution step is skipped`; `Packages: +3 -2` |
| `pnpm dedupe --check` | 0 | blocking duplicate-version gate |
| `pnpm audit --registry https://registry.npmjs.org/ --json --audit-level high` | 0 | no high/critical finding remains |
| `pnpm peers check` | 1 | 11 findings, the same set as before the slice; none involves `vite` |
| `pnpm --filter @soymutdb/api-client typecheck` | 0 | |
| `pnpm --filter @soymutdb/api-client check:contract` | 0 | `status: PASS` |
| `pnpm --filter @soymutdb/web build:sites` | 0 | dual-site (external + internal) artifact build |

No supply-chain knob was changed: `minimumReleaseAge`,
`minimumReleaseAgeExclude`, `allowBuilds` and the registry are untouched, and
no `vite` entry was added to `minimumReleaseAgeExclude`. The policy verdict
that counts is pnpm's own — every install and dedupe run above re-verified the
lockfile against the workspace supply-chain policies and passed.

### Audit state after the targeted Vite patch (observed 2026-10-24)

| Lockfile | Findings | high | moderate | low |
| --- | --- | --- | --- | --- |
| D1 batch (`follow-redirects` 1.16.1, `hono` 4.13.11, `vite` 7.3.6) | 8 | 1 | 5 | 2 |
| This slice (`vite` 7.3.7) | **3** | **0** | **2** | **1** |

The five `vite` advisories are gone — GHSA-587h-7wmj-h5pm (high),
GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw, GHSA-rq7h-c2jc-7f22 (moderate) and
GHSA-9jrq-w75r-8gcw (low) — because the only `vite` 7.x copy left in the graph
is 7.3.7.

The three that remain were confirmed by the formal audit and are **not**
fixable in this batch:

| Package | Severity | Advisory | Why it is still open |
| --- | --- | --- | --- |
| `react-router` 6.30.6 | moderate ×2 | GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg | Fixed only in `>=7.18.0`; Umi 4 does not support that major. The shipped SPA uses TanStack Router. |
| `elliptic` 6.6.1 | low | GHSA-848j-6mx2-7j84 | No patched release; development bundling only. |

### The governance gate is still red — on a pre-existing stale acceptance

`pnpm audit --audit-level high` now exits 0, but the repository's own
`pnpm-audit` gate **still fails**. Evaluating the fresh report with the
repository's own `load_advisory_acceptances` and `evaluate_advisory_report`
(from `scripts/dependency_governance.py`) yields exactly one unaccepted item:

```
braces: acceptance for GHSA-vfj7-8cjw-p6xm matches no reported finding; delete it — a stale acceptance is not a record of a live risk
```

That stale `braces` acceptance predates this slice. In the D1 batch it was the
blocking item together with the `vite` high; the `vite` high is now gone and
the stale acceptance is what remains. Removing or re-signing it is a change to
`security/advisory-acceptances.json` — a signed risk-acceptance action — and
is **outside this slice's write scope**. It is deliberately not closed here,
and the gate must not be reported as green.

### What the dual-site build does and does not prove

The production portal build runs through Umi's **webpack** bundler
(`[webpackbar] ℹ Compiling Webpack` in the build log);
`@umijs/bundler-vite` is used only when a Umi project explicitly selects the
vite bundler, which this repository does not do. The dual-site build therefore
proves that the lock change does not disturb the shipped external/internal
artifact pipeline — both variants compiled, 28 static documents each, CSP
finalized, service worker written, and the placeholder, build-path and
app-shell artifact checks green — but it does **not** exercise vite 7.3.7 at
runtime.

The unit-test substrate is likewise unaffected: `vitest@5.0.5` still resolves
`vite` 8.3.4, byte-identically, and the installed packages keep their
original peer ranges.

So vite 7.3.7's runtime behaviour under `@umijs/bundler-vite` is still
unproven. The residual risk is a same-minor patch release (7.3.6 → 7.3.7) on
a code path this repository does not currently build with; the workspace
Vitest run is the check that does cover the test substrate, and it was not
part of this slice.

### Correction record (2026-10-24, documentation-only)

A read-only review of this slice found four misstatements in the evidence
artifacts and in the work records. They are corrected here and in the work
records; the lock, the build and the audit results themselves are unchanged,
and no code, manifest, lockfile or risk acceptance was modified.

**C1 — the prose undercounted the edges this slice moved.** The section
above originally said the graph carries three `vite` edges and that this
slice "changed one of them", while the table directly beneath it showed two
rows moving from 7.3.6 to 7.3.7. Recomputed from the lock against the
byte-exact D1 baseline (`out/pnpm-lock.baseline.yaml`), the package graph
carries **four** resolved `vite` dependency edges and this slice moved **two**
of them: `@umijs/bundler-vite` → `vite` (direct dependency) and
`@vitejs/plugin-react` → `vite` (peer context). The `vitest` and
`@vitest/mocker` → `vite` 8.3.4 edges are unchanged and the three peer
*range* declarations are byte-identical. The prose now says "changed two".

**C2 — the "+316" and "+281" figures were not added-line counts.** `+316`
is the **line count of the diff file**
`.cache/vite-targeted-implementation/out/final-governance-doc.diff` (316
lines); `+281`, quoted in that slice's `SUMMARY.md`, matches no measured
quantity. The measured figures, taken at the pre-correction snapshot of this
document (`sha256 5888de8e…`, 420 lines):

| Baseline | Measured | How it was obtained |
| --- | --- | --- |
| vs `HEAD` | **+287 / −0** | `git diff --numstat HEAD -- docs/ops/dependency-governance.md` |
| the D1 batch's share of that | **+108** | diffstat recorded in `.cache/d1-implementation/13-final-scope-check.log` |
| this slice's share (line count) | **+179** | 287 − 108 |

These are **line counts**, not a diff. This slice also edited two sentences
*inside* lines the D1 batch had already added (the `vite` high row of the
audit table and the `pnpm audit` exit-code paragraph), and a line-count
subtraction cannot show such in-place edits. **No byte-exact pre-slice copy
of this document was retained** — only its `sha256` in
`.cache/vite-targeted-implementation/out/source-files.sha256.txt` — so a true
single-slice document diff **cannot** be reproduced, and none has been
fabricated. `out/final-governance-doc.diff` is therefore labelled **vs `HEAD`
(a different baseline)**, not "this slice". The lockfile is in the better
position: a byte-exact pre-slice lock copy **does** exist
(`out/pnpm-lock.baseline.yaml`, `sha256 667a7f3d…`, identical to the recorded
pre-slice lock hash), so the 65-line patch in
`out/final-lock-diff-vs-d1-baseline.patch` **is** a true single-slice diff.

Because this record changes the document, the numbers above are pinned to the
pre-correction snapshot; the post-correction values (this document's own
length and diffstat) are recorded, with their own snapshot hash, in
`.cache/vite-targeted-implementation/out/correction/01-doc-diff-accounting.md`.
They are deliberately **not** repeated here: a document cannot carry its own
hash without changing it.

**C3 — `out/artefact-hashes.sha256.txt` holds source-file hashes, not
artefact hashes.** Its three lines hash `pnpm-workspace.yaml`,
`pnpm-lock.yaml` and this document — the same kind of content as
`out/source-files.sha256.txt`, minus the pre-slice values. The file has
**not** been renamed, moved or deleted; an accurately named, explicitly
source-only copy was added at
`.cache/vite-targeted-implementation/out/correction/source-only.post-correction.sha256.txt`.
Neither file hashes any build output.

**C4 — four green artifact checks are not a rebuild of the three apps.**
`scripts/check-production-artifact.sh` scanned `apps/web/dist/external` only;
`scripts/check_artifact_headers.py` checked 4 files;
`scripts/check_artifact_build_paths.py` and `scripts/check_app_shell_assets.py`
*reference* `apps/admin/dist` and `apps/jbrowse` without rebuilding them.
`apps/admin/dist` is still the pre-existing **2026-10-18** tree and
`apps/jbrowse/dist` **does not exist**, so those four checks are **not**
evidence that the admin console and jbrowse build green.

**Independent review.** A separate read-only reviewer recomputed the lock
delta, the audit counts and the gate verdict and returned *accept-with-gaps*
for this slice. That verdict covers the slice only: it is not an acceptance
of the residual risk, not a merge approval, and not a statement that the
dependency goal is complete.

## Reproducing locally

```bash
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/api
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/worker
UV_CACHE_DIR=/tmp/uv-cache uv lock --check --project apps/mcp-server
PNPM_HOME=/tmp/pnpm-home pnpm install --frozen-lockfile --ignore-scripts --lockfile-only
```

The full governance runner additionally requires network access to the package registries and vulnerability services.

### JS side, as run for the `follow-redirects` / `hono` batch

```bash
# Node 26.13.0 (.nvmrc pin) and pnpm 12.11.2 (package.json pin)
pnpm install --lockfile-only                                    # regenerate the lock
pnpm install --frozen-lockfile --ignore-scripts                 # lock is up to date + installable
pnpm dedupe --check                                             # blocking duplicate-version gate
pnpm audit --registry https://registry.npmjs.org/ --json        # finding list (exit code != execution result)
pnpm --filter @soymutdb/api-client typecheck
pnpm --filter @soymutdb/api-client check:contract
```

### JS side, as run for the targeted Vite patch

Same toolchain and the same first four commands; the additions are the gate
evaluation and the dual-site artifact build:

```bash
# Node 26.13.0 (.nvmrc pin) and pnpm 12.11.2 (package.json pin)
pnpm install --lockfile-only                                    # regenerate the lock
pnpm install --frozen-lockfile --ignore-scripts                 # lock is up to date + installable
pnpm dedupe --check                                             # blocking duplicate-version gate
pnpm audit --registry https://registry.npmjs.org/ --json --audit-level high
pnpm peers check                                                # peer inventory (exit 1 on the pre-existing set)
pnpm --filter @soymutdb/api-client typecheck
pnpm --filter @soymutdb/api-client check:contract

# dual-site artifact build (the step scripts/verify-frontend-artifacts.sh runs)
VITE_DEPLOYMENT_MODE=demo \
VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
SOYMUTDB_PORTAL_ORIGIN=https://portal.soymutdb.test \
SOYMUTDB_ADMIN_ORIGIN=https://admin.soymutdb.test \
SOYMUTDB_SITE_URL=https://api.soymutdb.test \
  pnpm --filter @soymutdb/web build:sites
```

On a machine where `$XDG_RUNTIME_DIR` is writable, no extra environment is
needed. Where the host mounts `/run/user/1001` read-only (EROFS), pnpm cannot
create its store-operation lock directory there; point `PNPM_HOME` and
`XDG_RUNTIME_DIR` at the workspace-local directories that earlier successful
runs already use (`.ph/` for the store, `.ph/run/` for the runtime locks)
rather than disabling any policy.

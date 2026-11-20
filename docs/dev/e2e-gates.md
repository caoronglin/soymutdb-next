# Browser artifact gates (Playwright)

The repository carries 16 Playwright configs (15 `playwright-*.config.ts` plus
the default online smoke). **Ten serve a locally built artifact and need no
deployment**; the rest target a deployed stack and are skipped without
credentials. History matters here: eleven configs used to be unwired, and
the unwired ones rotted silently (admin-production asserted
English copy for a Chinese-first console; entity-detail served a dist root that
no longer existed; primer pointed at an artifact with no `index.html`).

## Run all offline gates

```bash
# build every artifact the gates serve (web external+internal, admin, jbrowse)
bash scripts/build-all-static-apps.sh

# one sweep; exits nonzero if any gate fails or an artifact is missing
pnpm verify:artifact-e2e
# or build + sweep in one command
bash scripts/verify-artifact-e2e.sh --build
# subset / diagnostics
bash scripts/verify-artifact-e2e.sh public entity-detail
ARTIFACT_E2E_LOG_DIR=.cache/my-run bash scripts/verify-artifact-e2e.sh
```

## CI wiring

Two lanes run the sweep (both providers call the same script, `.cnb.yml` is
authoritative):

- **Pull requests** (`e2e-smoke.yml` → `pr-artifact`): `build-all-static-apps.sh`
  then `verify-artifact-e2e.sh`. The previous PR job built a `/soymutdb-next/`
  artifact and ran only `playwright-public.config.ts`; once the public gate moved
  to the standard base-`/` artifact that job no longer matched its own config.
  Building the standard set through the shared script fixed the mismatch and
  widened the PR lane from one gate to the whole sweep.
- **Nightly** (CNB `crontab: 0 2 * * *` and the GitHub schedule): both call
  `scripts/ci-nightly-artifact-gate.sh`, which installs the independent `e2e/`
  package **and Chromium itself** (CNB stages are fresh containers, so an
  earlier stage's `playwright install` does not survive), bootstraps the
  workspace, builds the artifacts and runs the sweep with one retry. The CNB
  nightly job must not export `SMOKE_BASE_URL`: `entity-detail` reads it as a
  deployed-portal override, which would silently make that gate test the live
  site instead of the artifact it just built.

Contract coverage: `scripts/test_ci_job_contracts.py` (71 tests) still passes —
the new scripts are in its shared-script inventory and both workflow bodies are
bare delegations.

The sweep takes ~9.5 minutes (ten gates, ≈572 s measured locally; the sub-path gate alone is ≈192 s because it runs the full public suite against a second artifact). On a memory/pid-constrained host Chromium
occasionally dies while creating a context (`browser.newContext: Target page,
context or browser has been closed`); set `ARTIFACT_E2E_RETRIES=1` to absorb
that launch failure. Assertion failures still fail after the retry.

## Offline gates (artifact served by the repo static servers)

| config | artifact | port | what it pins |
| --- | --- | --- | --- |
| `playwright-public.config.ts` | `apps/web/dist/external` @ `/` | 4173 | route smoke (32 routes × en/zh), search/genes/login/accessibility, wrong-shape API resilience, seed-request submit payload + client-side 200-gene cap, downloads catalogue grouping + preview dialog + download URL-scheme guard, seqfetch genes/region payloads + large-result download + client-side caps, exppattern payload + summary/missing/matrix + interpolated aria, enrichment ORA/GSEA payloads + summary/tags/term table + native form validity, BLAST signed-in submit payload + job history + hits table + JBrowse/gene-search cross-links, portal⇄JBrowse postMessage bridge (init/ready/locus-change/error + no-context state), analyses researcher gate + server list + row→job page + local-record fallback |
| `playwright-internal.config.ts` | `apps/web/dist/internal` @ `/` | 4175 | internal variant policy, `data-app-ready`, route smoke |
| `playwright-admin-production.config.ts` | `apps/admin/dist` | 4174 | admin boots + login testids + split-font preload contract |
| `playwright-admin-shell.config.ts` | `apps/admin/dist` | 4189 | signs in through the form against the mocked auth endpoint and mounts the authenticated shell; every registered console route must also mount the shell (24 paths, session restored via mocked `/auth/refresh`, honest 404 data); **write paths** (`admin-write-paths.spec.ts`): saving the primary navigation PATCHes `expected_version` + the edited `navigation_json`, a 409 surfaces the conflict instead of discarding the edit, and a real pointer drag (past dnd-kit's 4px activation threshold) reorders the document that is saved |
| `playwright-entity-detail.config.ts` | `apps/web/dist/external` @ `/` | 4176 | mutant/gene detail render from mocked API + shareable compare URL |
| `playwright-visual.config.ts` | `apps/web/dist/external` @ `/` | 4177 | 5 routes × 3 viewports geometry/overflow |
| `playwright-web-performance.config.ts` | `apps/web/dist/external` @ `/` | 4178 | initial JS budget, no stale artifact layout |
| `playwright-primer.config.ts` | `apps/web/dist/external` @ `/` | 4173 | paste/genome primer modes against `mockPrimerApis` |
| `playwright-jbrowse-artifact.config.ts` | `apps/jbrowse/dist` @ `/` | 4186 | shell boot + degraded state + split-font serving (React #299 regression) + **linear genome view mount** from a mocked release config with an inline reference sequence |
| `playwright-subpath-artifact.config.ts` | `pages-dist` @ `/soymutdb-next` (built by `scripts/build-pages-artifact.sh`) | 4196 | the **full public suite** re-run against a prefixed mount, plus base-path assertions the root gates cannot see: no root-absolute `/assets/…` request, a deep link keeps the prefix, and `routes.json`/`robots.txt` are served at the prefix naming the site (not the API) origin. Needs `E2E_BASE_PATH=/soymutdb-next`, which the sweep exports for this gate; reported SKIPPED with a reason when `pages-dist/` is absent |

`scripts/verify-artifact-e2e.sh` is the inventory: adding a gate means adding a
config and appending it to that list; `scripts/test_artifact_e2e_gate.py` fails
if the list, the config files, the package.json script, or the fail-closed exit
codes drift.

## Deployed-only gates (skip without env)

| config | needs | run |
| --- | --- | --- |
| `playwright.config.ts` | online site (`SMOKE_BASE_URL`) | nightly/deploy smoke |
| `playwright-production.config.ts` | `PRODUCTION_BASE_URL` (real release data) | production gate |
| `playwright-jbrowse.config.ts` | deployed shell + `/jbrowse-data` | genome-browser E2E |
| `playwright-admin-console.config.ts` | `ADMIN_BASE_URL` + `ADMIN_STORAGE_STATE` | admin console E2E |
| `playwright-portal-embed.config.ts` | `PORTAL_BASE_URL` + embedded JBrowse | portal embed E2E |

## Static-server contracts worth remembering

- The server's `PREFIX` is normalised to `""` for a root mount. Passing a raw
  `/` used to build every mock path as `//api/v1/...` (all 404) — see the
  comment at the top of `e2e/static-server.mjs`.
- A root-baked artifact can be mounted under a sub-path: the server falls back
  to serving its root-absolute assets, while documents stay under the prefix.
- Never fabricate `GET /releases/active` in a page mock: a fake release id
  changes the deployment context and release-scoped reads stop resolving.
  `helpers.mockPrimerApis` deliberately omits it (404) for that reason.

# Anonymous and authenticated BLAST delivery

Task start: 2026-11-03. Base: `d95aff0bf06db3030f8b0e41535ce4108b04cdeb` (PR #28).

## Change necessity and review boundary

The public form previously prevented execution without a researcher session. The requested two access modes require a usable anonymous workflow alongside account-owned jobs. This is a high-impact authorization change: architecture review is required for capability purpose, job binding, expiry, quotas, release isolation, CORS and leakage boundaries.

The existing database catalog, outbox, worker, object storage and parser remain the execution owners. The public API adds access control around the same pipeline. No new queue or storage backend is introduced.

## Target acceptance

- Anonymous users can submit from `/search/blast`, poll their job and retrieve real completed results using an expiring header credential.
- Account users continue to submit and read their owned jobs at `/blast`.
- Public credentials grant no account session, private job access, listing, administration or arbitrary commands.
- Lost public credentials cannot be recovered through a public job listing.
- Anonymous jobs are explicitly marked, limited by peer quota and size, and scoped to published release databases.
- API/client contract and cross-origin preflight are verified.

Implementation and actual validation results are recorded below when available. This slice continues to execute DIAMOND blastp only; NCBI BLAST+ remains the next engine phase.

## Delivered contract

The public API provides `POST /blast/public/jobs` and capability-authorized GET status/results endpoints. Tokens are signed for a distinct BLAST purpose and one job UUID, expire within 24 hours, and are supplied only through `X-Blast-Token`. Anonymous jobs carry an explicit internal marker so deleted-account orphan jobs do not become public. Public requests have a dedicated trusted-peer 5/hour quota and a 10,000-character limit. Redis outages fail closed outside development. Public error diagnostics do not expose worker/index paths. Expired jobs do not return hits/download links; raw-download expiry is capped by the remaining job and capability lifetime.

`/search/blast` now submits, polls and displays paginated results without an account. The capability stays in component memory and is lost when the page is left. Public requests omit account cookies and bearer headers and do not trigger auth refresh. `/blast` keeps its existing account history and researcher submission flow, with links between the two pages. Result views retain the job's release/assembly, and unsupported programs are rejected rather than rewritten.

No database migration, new queue, new storage backend or new runtime dependency is required. API changes and generated TypeScript contracts are committed together. Operational configuration, rollback and deployment checks are in [public BLAST operations](../ops/public-blast.md).

## Verification evidence

Local evidence: Python 3.15.0; disposable PostgreSQL **18.6** on loopback port 55458, newly initialized under ignored `.cache/blast-public-pr/postgres`; Node 26.12.1 and installed pnpm 12.14.0, below/different from the repository's target Node 26.13.0 / pnpm 12.11.2. These local toolchain differences are not asserted to satisfy the pinned-runtime CI gate. No production service or data was used.

| Check | Invocation / scope | Actual result |
|---|---|---|
| Web baseline before anonymous UI | `cd apps/web && node node_modules/vitest/vitest.mjs run` | 508 passed |
| API full | `SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55458/blast_public_test PYTHONPATH=<repo> <api315-python> -m pytest tests -q` in `apps/api` | 2639 passed, 8 skipped; 85.42s |
| New PostgreSQL boundary test | Included in full API run and separately executed by backend implementer | Real persisted anonymous job + outbox; purpose/job/owner/orphan/draft-release refusal |
| Worker BLAST regression | Worker315 pytest: `test_blast_task.py`, `test_blast_protein_fasta.py`, `test_diamond_integration.py` | 104 passed, 7 skipped; 1.33s |
| Web final full | Same Vitest command as baseline | 512 passed across 58 files; 114.63s |
| API-client full | `cd packages/api-client && node ../../apps/web/node_modules/vitest/vitest.mjs run` | 200 passed; 9.06s |
| TypeScript | Web and API-client `tsc --noEmit` | Both passed |
| ESLint | Web and API-client `eslint src`; changed browser test lint | Passed; 2 pre-existing warnings in variant-export files |
| Python lint | Ruff on changed API files/tests | Passed |
| API contract | `SOYMUTDB_API_PYTHON=<api315-python> bash packages/api-client/scripts/check-contract.sh` | Generated types byte-match; handwritten route visibility PASS |
| Architecture | `python scripts/check_architecture.py` | Passed |
| Locale visibility | `node scripts/check_visible_i18n_react.mjs` | Passed |
| Dual-site build | `cd apps/web && node node_modules/tsx/dist/cli.mjs scripts/build-sites.ts` with `GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`, demo mode | External and internal built |
| Artifact isolation | `SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh` | Passed |
| Browser artifact regression | `cd e2e && node node_modules/@playwright/test/cli.js test -c playwright-public.config.ts tests/blast.spec.ts` | 6 passed; 9.7s; desktop and 390px screenshots |
| Diff hygiene | `git diff --check` | Passed |

Set `npm_config_manage_package_manager_versions=false` to use the installed pnpm for local commands: the pinned package-manager engine store was read-only. A missing local `@eslint/js@10.0.1` package was restored to the ignored dependency tree without changing manifests/lockfiles.

Screenshots are generated under ignored `e2e/test-results-public/blast-anonymous-{desktop,mobile}.png`. Browser tests use mocked API responses; real database tests prove API ownership/outbox behavior. Neither is evidence of a live DIAMOND search or production S3/worker readiness. The 7 worker skips are the absent DIAMOND binary's opt-in real searches; this PR does not claim those ran. Eight pre-existing optional API integration cases remain skipped. No production performance benchmark was performed; test durations above are verification timing only.

Independent backend/UI security review found no confirmed Critical/High issue. PyJWT 2.15.1's default future-iat rejection was separately checked. Global private-job ownership, purpose-specific capabilities, positive anonymous markers, release restrictions and download expiry are covered by focused tests. Token revocation/cancellation UI and NCBI BLAST+ engine work remain separate follow-ups.

## Remote CI baseline

PR #28 was merged as authorized while checks were queued. Subsequent checks confirmed frontend build/contract, Linux PostgreSQL API baseline, Windows API baseline, web/admin baseline build, database A/B and MCP transport passed. Its repository-contract jobs failed on pre-existing Node-version assertions and host PostgreSQL-client assumptions; historical ClickHouse fixture jobs failed because their fixture database lacked `releases`; deployment-bundle CI also failed. These are not treated as passing gates. The new PR's own remote checks must be read independently; the local results above do not close those CI defects.

## PR #29 CI correction (2026-11-03)

Remote CI exposed two regressions introduced by this PR despite the local unit/build checks above: the anonymous page's backend-editable `blastPublic.subtitle` was missing from the settings registry, and its new test used an inline `useTranslation` mock that created a new `t` on every render. The correction registers the existing subtitle with administrator/global metadata and a bounded default, and uses the portal's shared `mockTranslation` so assertions exercise real catalog text with stable translation identity. The contract guards are unchanged.

Verified in an isolated worktree based on PR #29 head `de5dc1b632f574d16a84b5a626e09ab6470630c3`:

- `python scripts/check_content_key_contract.py`: **passed**, 71 portal keys / 122 registered content keys.
- `python -m unittest scripts.test_ci_job_contracts.DeliveryArchitectureTests.test_i18n_handling_needs_no_per_render_double -v`: **1 passed**.
- `python -m pytest scripts/test_content_key_contract_guard.py -q`: **5 passed**.
- API venv, `cd apps/api && python -m pytest tests/test_settings_registry.py -q`: **20 passed**.
- `cd apps/web && node node_modules/vitest/vitest.mjs run src/routes/blast.test.tsx src/routes/search/blast.test.tsx`: **19 passed**, 2 files; 18.14s.

These targeted corrections do not claim that the remote CI suite is green. A read-only comparison against actual PR #28 job logs confirmed that worker installation failures (`libbzip2` / `libhdf5.so`), the existing Node-pin/host-client contract failures, historical ClickHouse fixture errors, dependency-governance findings and CycloneDX/pnpm `ls --all` failure were already present on the base. The complete PR #29 API pytest run itself passed **2639 tests, 8 skipped** before worker installation failed.

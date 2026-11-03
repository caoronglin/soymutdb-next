# BLAST verification PR — evidence

Issue: #1. Role assignment requested by the reporter: one validation pass, two
functional completions, two BLAST backends retained, one anonymous and one
authenticated flow, delivered via PR. This document records what was actually
run; it is not a design claim.

## Role interpretation

- **Validation:** the existing BLAST implementation was audited end to end and
  exercised with real binaries and a real PostgreSQL instance (below).
- **Functional completion 1:** made the opt-in real-binary integration tests
  reliable offline, so the five-program acceptance evidence is reproducible
  rather than permanently skipped.
- **Functional completion 2:** completed the external-database research
  deliverable with a first-party verification ledger and aligned the
  architecture/roadmap/ops documents with the implemented state.
- **Two backends retained:** NCBI BLAST+ (five programs) and DIAMOND `blastp`
  remain separately selectable in the API schema, client, both frontends, the
  outbox payload and MCP manifest. No engine silently substitutes for another.
- **Two access modes:** authenticated account jobs on `/blast` and capability-
  authorized anonymous jobs on `/search/blast` both use the same job/outbox/
  worker pipeline. See `docs/ops/public-blast.md`.

## Baseline (before changes)

Environment provisioned locally for this pass: CPython 3.15.2 (uv), PostgreSQL
15 on `127.0.0.1:55432`, official NCBI BLAST+ 2.17.0+ binaries. The repository
requires Python >=3.15; earlier 3.11 tooling reports PEP 695 `def f[T]` and
PEP 758 `except A, B:` as syntax errors, which are false positives here.

| Suite | Command (abridged) | Result |
|---|---|---|
| worker BLAST unit tests | `pytest -q tests/test_ncbi_blast.py tests/test_blast_ncbi_task.py tests/test_blast_index.py ...` | 92 passed, 13 skipped |
| shared job contract | `pytest -q packages/jobs-py/tests/test_blast_search.py test_blast_catalog.py` | 81 passed |
| API BLAST (no PG) | `pytest -q tests/test_blast_*.py` (10 files) | 234 passed, 3 skipped |

Skips were the opt-in real-binary and PostgreSQL integration cases.

## Defect found and fixed

`apps/worker/tests/test_ncbi_blast_real.py` invoked `makeblastdb` directly with
the ambient environment. NCBI's default usage-report DNS/telemetry lookup made
each call take ~31 s, so the tests' 20 s `subprocess` timeout killed them:

```
subprocess.TimeoutExpired: Command '[.../makeblastdb ...]' timed out after 20 seconds
```

`soymutdb_worker.ncbi_blast._env()` already disables `BLAST_USAGE_REPORT` and
local config discovery for real searches; the fixture-only builder calls did
not. The fix passes the same offline environment to both `makeblastdb` calls in
that test file. With `BLAST_USAGE_REPORT=false` the same build completes in
under 1 s. This is a test-infrastructure fix; it does not change engine
semantics, CLI allowlists or resource limits.

## Real integration results (after fix)

```
SOYMUTDB_TEST_NCBI_BIN_DIR=.cache/ncbi/ncbi-blast-2.17.0+/bin
SOYMUTDB_TEST_MAKEBLASTDB_BIN=.../makeblastdb
SOYMUTDB_TEST_BLASTDBCMD_BIN=.../blastdbcmd
SOYMUTDB_WORKER_TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:55432/postgres
SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/postgres
SOYMUTDB_RUN_POSTGRES_INTEGRATION=1
```

| Suite | Result | What it proves |
|---|---|---|
| `test_ncbi_blast_real.py` | 6 passed | Real `makeblastdb` + real searches for blastn/blastp/blastx/tblastn/tblastx, reverse-strand hit and no-hit case |
| `test_blast_index_real.py` | 2 passed | Real immutable nucleotide/protein index build, `blastdbcmd` entry verification, idempotent rebuild |
| `test_blast_ncbi_pipeline.py` | 5 passed | Real index → existing Celery task → PostgreSQL HSP persistence → duplicate delivery skipped |
| API PG integrations | 22 passed | NCBI submission per program, capability read, catalog/release isolation, migrations `0050`/`0051`, public job postgres path |

No mock-only claim is made for the above: the child processes are the official
2.17.0+ executables, and the database is a live PostgreSQL 15 server. Note the
local PG is 15, while CI/production use newer majors; these results are
qualified as "PG 15 locally green", not a PG-version certification.

## CI defects and gate recovery

Three gate defects were blocking every PR build. They were fixed across
several PRs; this section records which fix landed where, so the evidence
here is not read as belonging to this branch alone.

- **`npc:go` pre-empting `verify`** — `f6d5001` put an unnamed `npc:go`
  stage at `main.pull_request[0]` with `role: 代码审查员`, a role absent from
  `.cnb/settings.yml`. The platform resolves roles before the container
  starts, so every build died in ~1 s with
  `Role "代码审查员" not found ... Available: CodeBuddy`; the unnamed block
  also displaced `verify`, breaking four contract tests. Fixed and merged in
  PR #5 (`.cnb.yml` + `.cnb/settings.yml`, plus a guard). PR #5 also replaced
  the `issue.comment@npc` `echo` placeholder with a real `npc:go` job and
  declared `pull_request.comment@npc`, so `@`-mentions actually start an NPC.
- **h5py source build failing** — CPython 3.15 has no manylinux wheel for the
  worker science stack (`scanpy -> anndata -> h5py`); the bare `python:3.15`
  CI image lacks HDF5 headers, so the editable install died with
  `libhdf5.so: cannot open shared object file` before any test ran. PR #6
  added a `Compiler prerequisites` stage and a `system-deps` job body in
  `scripts/ci-job-steps.sh`. This branch keeps an idempotent
  `scripts/install-worker-science-build-deps.sh` called from the shared
  `verify-backend-tests.sh` (which also covers the GitHub mirror), with a
  `test_ci_job_contracts.py` guard pinning the call order and package list
  against `infra/docker/Dockerfile.worker`. Both are idempotent and install
  the same `libhdf5-dev` + `pkg-config` recipe.
- **Visible-i18n and lint defects on the BLAST surface** — the earlier
  revision of this branch fixed the `no-useless-escape` on `\-` in
  `packages/api-client/src/blast.ts` and the hardcoded engine labels in
  `apps/web/src/routes/blast.tsx` / `search/blast.tsx`. Those files have a
  single owner in PR #4, which carries the same fixes. To avoid two PRs
  rewriting the same file, this branch deliberately dropped them; the i18n
  patch was forwarded to PR #4 (`48a2674`). This PR therefore contains no
  frontend or api-client changes.

Both #5 and #6 were merged to `main` before this branch was rebased, so the
`verify` pipeline is the single named PR pipeline again and the
`Compiler prerequisites` stage succeeds (~8 s) before the verification
stages. The backend pass counts above are from the local CPython 3.15.2 /
PostgreSQL 15 / real BLAST+ 2.17.0+ runs, not from CI.

## Engine and access-mode contract checks

- `apps/api/app/schemas/blast.py`: `BlastSubmitProgram` lists all five programs;
  `engine` defaults to `ncbi_blast`; DIAMOND is explicit and constrained to
  `blastp`.
- `packages/jobs-py/src/soymutdb_jobs/blast_search.py`: single validation owner
  for program/database/parameter compatibility; rejects unknown flags.
- `apps/worker/src/soymutdb_worker/ncbi_blast.py`: argument arrays only,
  no `shell=True`, per-child rlimits, binary version/hash provenance.
- `apps/worker/src/soymutdb_worker/tasks/blast.py`: `engine` is read from the
  frozen outbox payload; missing engine means legacy DIAMOND, never an implicit
  reroute.
- `apps/api/app/api/v1/blast.py`: account routes plus `PublicBlastRoute`
  capability routes; private `Cache-Control`/`Vary` on public responses.
- `apps/web/src/routes/blast.tsx` and `apps/web/src/routes/search/blast.tsx`:
  account and anonymous forms both expose engine/program selectors with
  compatibility filtering.

## External research

`docs/research/plant-database-feature-comparison.md` now records HTTP status,
payload size and the exact capabilities present in fetched first-party content
for Ensembl Compara, SoyBase tools, GBIF API docs and live species match,
PlantCARE article, Gramene, Phytozome and the blocked/unavailable sources.
Unverifiable rows remain labelled candidates; no license or ingestion is
claimed. The matrix explicitly separates currently available, legacy,
external and proposed behavior.

## Limitations

- CI does not provision NCBI binaries, so real-binary tests remain opt-in
  `skip` in the default pipeline. This PR makes opt-in runs reliable but does
  not change the CI allowlist.
- No production multi-species/pan-genome FASTA or admin-triggered async index
  rebuild is shipped. Operator-driven catalog registration remains.
- Genome-browser links from protein hits require real protein/transcript/gene
  mapping rows in the searched release; the contract refuses to fabricate loci.
- This PR does not implement Phase 2+ gene center, synteny, expression browser,
  TF/motif/pathway adapters or the no-SQL bulk query builder.

## Recommended next phase

Phase 2 (gene center): compose sequence, annotation, homolog, expression,
variant and phenotype sections on existing gene routes, then add an admin-
triggered index rebuild that reuses `blast_index.build_index` and the existing
outbox/worker ownership model.

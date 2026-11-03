# BLAST database catalog and immutable index preparation

TaskStartSnapshot: base `de5dc1b632f574d16a84b5a626e09ab6470630c3` (PR #29); branch `feat/blast-index-catalog`; started 2026-11-03. This is the next focused BLAST+ preparation slice after the anonymous/account access workflows.

## Change necessity and scope

The current catalog cannot distinguish a DIAMOND index from an NCBI BLAST index or record FASTA/build provenance. Enabling new programs before this distinction exists could route an incompatible index into the existing DIAMOND worker. Add additive catalog metadata and a reusable, verified NCBI index builder first.

This PR owns catalog persistence, searchable-database eligibility and operator-side immutable NCBI index preparation. Existing anonymous/account submission and DIAMOND execution remain the owners of search jobs. The builder does not add a queue, a database registration endpoint or an alternate search pipeline. Five-program execution, a Celery index-build lifecycle and object-store catalog publication remain subsequent slices.

ArchitectureReviewRequired: **yes**. Review migration upgrade/downgrade, legacy-row compatibility, published release/assembly isolation, subprocess/FASTA validation, filesystem traversal/symlink handling, bounded resources, checksums, immutable publication and safe reuse.

## Acceptance boundary

- Preserve legacy DIAMOND catalog rows and historical count/status columns without fabricating readiness or source/license/annotation metadata. Pending rows stay pending and are excluded from execution.
- Distinguish engines, index readiness, sequence subtype, provenance and default selection in PostgreSQL.
- Reject NCBI, building and failed index entries before existing DIAMOND jobs/outbox events are created.
- Never expose local index paths or unrestricted private provenance in public discovery.
- Build protein and nucleotide indexes with real `makeblastdb`; independently validate them with `blastdbcmd` before atomic publication.
- Record source checksum, sequence count, residue count, assembly/release/source/license and binary/index versions in a manifest whose artifact paths are relative and checksummed.
- Reuse only an identical verified build; detect corruption and clean failed staging without overwriting published indexes.
- Verify migration upgrade/downgrade and authorization/release regressions on real PostgreSQL.

Verification results and limitations will be added after execution. This document does not assert NCBI search execution is available.

## Implementation and review decisions

- Migration `0050` adds engine, sequence subtype, source/annotation/index version, FASTA SHA-256, default marker, private provenance and license. It reuses the historical `sequence_count`, `total_length`, `build_status` columns from `0001`, preserving their values, defaults and nullability. Pending remains pending; no migration asserts index readiness. Rollback refuses NCBI/building/failed rows and preserves the three old columns and jobs.
- Public discovery and every database selector (name, ID, both and fallback) require active + ready + DIAMOND + protein + published release. A future NCBI catalog entry cannot reach the current DIAMOND worker.
- Public source attribution has one shared owner in `soymutdb_jobs.blast_catalog`. API and builder both reject credential/query/fragment URLs, filesystem paths and known private authorities. API responses omit private `file_path` and unrestricted provenance JSON.
- The operator builder uses explicit fixed arguments and child resource limits, source snapshot normalization, binary/source hashes, content-addressed identities, streaming artifact hashes, canonical manifests, independent `blastdbcmd` validation, fsync and locked atomic publication. It rejects corrupted reuse and cleans failed staging. Details and CLI examples: [index builder operations](../ops/blast-index-builder.md).
- Independent read-only review found no remaining blocking issue after source URL query/fragment filtering and streaming large-artifact hashing were applied. The real migration-chain test caught the historical column overlap that an ORM-shaped fixture had missed; the migration was fixed at its owner rather than weakening chain coverage. Full-chain tests now seed real `0049` rows and compare original column definitions/counts/defaults across upgrade/downgrade/re-upgrade.

## Executed verification

Local runtime: Python 3.15.0, disposable PostgreSQL 18.6 on loopback 55459, Node 26.12.1 and installed pnpm 12.14.0 (repository targets remain Node 26.13.0/pnpm 12.11.2). The existing venvs contain noneditable shared-package installs, so verification sets `PYTHONPATH=<repo>:<repo>/packages/jobs-py/src` to exercise the new shared source helper. This is not a claim that a previously installed wheel contains the new module; deploy API/worker with the updated shared package together.

Official tool archive: `https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-x64-linux.tar.gz`. Upstream MD5 `bdec166721de3b55f90a3badc83538e8` verified. Locally recorded SHA-256 `3888112d8207831aa47371d93583c601f058f88b5db22dc782438b039a3a411b`. Both tools report 2.17.0+ (July 1 2025 build). Archive/binaries are ignored local artifacts, not committed dependencies. Existing DIAMOND **2.2.8** was found in the local bio-tools environment and explicitly enabled for real search regressions.

| Check | Actual result |
|---|---|
| API full: `cd apps/api && SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55459/catalog_lead_tests PYTHONPATH=<repo>:<repo>/packages/jobs-py/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 <api315-python> -m pytest tests -q -ra` | **2690 passed, 8 skipped**, 105.55s |
| Catalog/BLAST + release ablations + migration on separate `catalog_agent_tests` | **228 passed**, 14.00s |
| Strengthened real full-chain seed/definition roundtrip: `tests/test_variant_exports_migration.py` | **3 passed**, 12.61s |
| Worker full: `cd apps/worker && PYTHONPATH=<repo>:<repo>/packages/jobs-py/src SOYMUTDB_TEST_DIAMOND_BIN=<bio-tools>/diamond SOYMUTDB_REQUIRE_DIAMOND_SMOKE=1 SOYMUTDB_TEST_MAKEBLASTDB_BIN=<tools>/makeblastdb SOYMUTDB_TEST_BLASTDBCMD_BIN=<tools>/blastdbcmd OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 <worker315-python> -m pytest tests -q -ra` | **711 passed, 50 skipped**, 14.45s |
| Index final boundary/real-tool tests: same env, `tests/test_blast_index.py tests/test_blast_index_real.py` | **54 passed, no skips**, 11.16s |
| Shared jobs package: `PYTHONPATH=<repo>:<repo>/packages/jobs-py/src <worker315-python> -m pytest packages/jobs-py/tests -q` | **126 passed**, 0.18s |
| API-client full Vitest + TypeScript + changed-file ESLint | **200 passed**, 10.21s; typecheck/lint passed |
| Generated OpenAPI/TS contract: `SOYMUTDB_API_PYTHON=<api315-python> bash packages/api-client/scripts/check-contract.sh` | Passed, route visibility PASS |
| Ruff for changed Python source/tests | Passed |
| `python scripts/check_architecture.py` | Passed |
| `git diff --check` | Passed |

Real index tests construct both protein and nucleotide indexes, retrieve each known identifier via `blastdbcmd` and compare exact synthetic sequence content including the explicit reverse-complement record. Fixtures are purpose-written CC0 synthetic inputs, not claims about soybean annotation correctness. No NCBI search is performed. Tests cover canonical identity changes, checksum tampering, invalid FASTA, malformed/private attribution, symlink/traversal refusal, concurrency/no-overwrite, source mutation after snapshot, binary identity changes, failed child cleanup, bounded output/time/memory and CLI behavior.

The API's 8 skips are optional historical-driver/native-variant lanes; the worker's 50 skips are unrelated optional PostgreSQL export/import/static-page integrations and the 2-million-row performance tier. No new catalog/migration/ownership/index scenario is skipped. Broader privacy lanes that remain skipped do not establish a deployment/merge privacy gate. Logs are under ignored `.cache/blast-catalog-pr/{api-final,worker-final,index-final,shared,client-final,contract}.log`; agent chain logs under `.cache/blast-catalog-chain-final.log`.

No UI runtime behavior changes in this preparation PR: the client adds optional metadata types, so this PR does not claim another dual-site/browser artifact acceptance run. PR #29's browser/account/anonymous checks and its two CI contract fixes are separate evidence. The worker and API full runs cover both existing access modes. Test timing is verification timing, not a production performance benchmark.

## Remaining boundaries

This is a local POSIX operator tool with a trusted output root/binary installation. Parent FASTA memory scales with the bounded input; child RLIMIT is not a whole-process RAM cap. Default source cap256MiB does not prove whole-genome-scale ingestion. No asynchronous index-build queue, automatic catalog registration/status updates, object-store upload/publication, NCBI five-program execution, expanded query UI or real production deployment is delivered here. Those remain explicit subsequent tasks on the existing pipeline. Remote CI must be inspected independently; prior baseline failures are not closed by local tests.

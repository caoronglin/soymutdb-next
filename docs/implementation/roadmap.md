# Incremental implementation roadmap

## Phase 0: baseline and audit (complete)

- Audited the existing BLAST API, service, model, worker, frontend, MCP manifest and tests.
- Confirmed release-scoped database discovery, transactional outbox, idempotent worker writes and authenticated researcher job ownership.
- Recorded the test baseline on Python 3.15 (see [`blast-verification-pr.md`](blast-verification-pr.md)).
- Completed a first-party external-database research pass; see [`../research/plant-database-feature-comparison.md`](../research/plant-database-feature-comparison.md). Unverifiable sources remain labelled candidates.

## Phase 1: BLAST+ (execution repaired; see status below)

- NCBI BLAST+ executes all five standard programs against real 2.17.0+ binaries.
- DIAMOND `blastp` is retained as an explicitly selected backend; both engines remain available in the API, client, frontend and MCP contracts.
- Immutable `makeblastdb`/`blastdbcmd` index catalog with additive migrations `0050`/`0051`.
- Program-specific parameter validation shared by API and worker; argument-array-only execution with resource caps.
- Two access modes: authenticated account jobs (`/blast`) and capability-authorized anonymous jobs (`/search/blast`), both over the same outbox/worker pipeline.
- Real nucleotide and protein integration searches, index construction, PostgreSQL HSP persistence, duplicate-delivery idempotency, cancellation, quota and release-isolation tests.
- External research report distinguishes verified observations from candidates; no dataset ingestion or license claims are made.

## Phase 2: gene center (next)

Compose sequence, annotation, homolog, expression, variant, phenotype and publication sections on the existing gene routes. Preserve assembly switching and evidence labels.

## Phase 3: comparative genomics

Import orthology/family snapshots with method metadata, add alignments and phylogenetic artifacts, then add JBrowse-backed synteny and conserved-block views.

## Phase 4: expression and phenotype

Expose study/sample metadata, units, tissue/stage/treatment filters, QTL/GWAS links and existing chart abstractions.

## Phase 5: licensed resources

Add PlantTFDB, PlantCARE, PlantCyc and optional GBIF adapters only after source terms, checksums and refresh owners are recorded.

## Phase 6: query/download polish

Extend the existing asynchronous download service with a no-SQL query builder, provenance manifests, cursor pagination, accessibility and performance gates.

Status (0056): provenance manifests and a whitelisted query builder are
implemented. `download_files` and `variant_exports` carry nullable
`sha256`/`license`/`generated_at`/`source_ref`; the worker records the digest
of the exact uploaded bytes; `GET /variants/export/{id}/manifest` is the
owner-scoped citable record, and `POST /exports/query` submits whitelisted
filters through the existing outbox/export pipeline. A legacy artifact with
no checksum returns `sha256: null` with `sha256_state: not_recorded`.
Filters with no backing query capability (gene_list/species/biotype/GO/KEGG/
expression threshold/homolog species) and formats with no artifact builder
(FASTA/GFF3/GTF) are refused explicitly, not silently dropped or claimed.

### Phase 1 status: repaired but incomplete

The NCBI execution slice landed unreachable: `ncbi_blast.py` did not parse
(Python-2 `except A, B:`), and the worker whitelisted `blastp` for every engine,
so four of the five advertised programs were refused. Both are fixed and the
five programs now pass real-binary searches — see
[runtime repair evidence](blast-ncbi-runtime-repair-pr.md).

Entry-point parity (branch `feat/blast-access-parity`, verified by the gates
listed below; nothing here is claimed on the strength of a mocked response
alone):

- Program vocabulary: `tasks/blast.py` holds `ENGINE_PROGRAMS`, the per-engine
  sets (`diamond` = `blastp`, `ncbi_blast` = all five), and keeps the historical
  `ALLOWED_PROGRAMS` union for vocabulary probes. The DIAMOND-only set stays
  addressable as `DIAMOND_PROGRAMS`, so it can no longer be misread as the
  platform's program list.
- Worker split: `apps/worker/src/soymutdb_worker/ncbi_blast.py` runs all five
  programs with fixed argv, resource limits and provenance; `tasks/blast.py`
  keeps DIAMOND as an explicit `blastp` backend.
- Access parity: the anonymous route surfaced validation failures through
  `Alert title=`, which AntD 6 does not render, so every client-side rejection
  was silent. Fixed; the signed-in route now shares the same FASTA rule.
- Raw-result download: the anonymous page offered the presigned artifact, the
  signed-in page did not. Both now offer it as tab-separated aligner output
  (`outfmt 6`), and neither renders a link when the job has no stored artifact.

Phase 1 items that were listed here as open have since landed; the list is
rewritten rather than deleted so a reader can tell what changed:

| Item | State | Where |
| --- | --- | --- |
| Asynchronous `makeblastdb` build/publication in the worker, with catalog build states | done | `apps/worker/src/soymutdb_worker/tasks/blast_index.py`, migration `0052` |
| Admin enable/disable control for an index | **still open** | no HTTP route toggles `blast_databases.is_active`; only the worker's publish path writes it |
| Protein-hit → transcript/gene resolution before genome-browser links | done | `apps/worker/src/soymutdb_worker/blast_genome_resolution.py`, `BlastService.resolve_genome_target`, `routes/blast.tsx` |
| Five-program UI wiring on `/blast` | done | `apps/web/src/routes/blast.tsx` (program selector filtered by engine, engine selector disabling DIAMOND for non-`blastp`) |
| Cancellation, retry and download-expiry coverage on the NCBI path | done | `apps/worker/tests/test_blast_cancel_retry_expiry.py::test_ncbi_jobs_are_guarded_before_the_engine_runs`, `apps/api/tests/test_blast_cancel_retry.py` |

Two caveats on that table, both of which the repository has already been wrong
about once:

- the resolution path is scoped in the *relation query*, not after it. A
  transcript id and an alias are strings that v4 and v5 can both carry, so
  collecting candidates first and filtering by assembly later leaves the
  contract standing on one downstream condition. It is now joined and filtered
  inside each relation query, and
  `test_blast_genome_resolution.py::test_a_relation_of_another_assembly_is_never_a_candidate`
  fails if that scoping is removed;
- the NCBI coverage above is the *guard* (cancelled and past-deadline jobs never
  reach `get_ncbi_db_path` or the aligner). It does not assert a real NCBI
  binary produced a result; that remains the opt-in real-binary suite's job.

Verification environment for the numbers this document reports: Python 3.15.2
via `uv`, no PostgreSQL server and no NCBI BLAST+/DIAMOND binaries in the
sandbox. `apps/api` therefore runs against its fakes and reports
`2469 passed, 25 skipped, 0 failed` with 389 `DockerException` errors from the
testcontainers fixtures; the real-binary and PostgreSQL integration suites stay
opt-in and are the ones CI must run.

## Current PR boundary

## Delivery notes

Earlier slices were delivered as separate commits on `main`: anonymous
capability authorization, catalog/index preparation, and NCBI execution. This
PR closes the verification gap: it makes the opt-in real-binary tests reliable
offline, aligns the architecture/roadmap documents with the implemented state,
records a first-party research ledger, and reports actual pass counts. It does
not complete the four Phase 1 items listed above, and does not replace the
existing delivery pipeline or add a second job queue/storage backend.

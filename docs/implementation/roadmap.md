# Incremental implementation roadmap

## Phase 0: baseline and audit (current)

- Audited the existing BLAST API, service, model, worker, frontend, MCP manifest and tests.
- Confirmed release-scoped database discovery, transactional outbox, idempotent worker writes and authenticated researcher job ownership.
- Confirmed current engine is DIAMOND `blastp`; NCBI BLAST+ is not yet implemented.
- Preserved public form/database discovery while making the submit affordance reflect the server capability contract.

## Phase 1: BLAST+

Add the immutable database catalog fields and migrations; build indexes asynchronously with `makeblastdb`; add validated all-program schemas; implement NCBI execution/parsing and explicit DIAMOND selection; add real nucleotide/protein integration fixtures; add cancellation, retry, release-isolation and download-expiry tests.

## Phase 2: gene center

Compose sequence, annotation, homolog, expression, variant, phenotype and publication sections on the existing gene routes. Preserve assembly switching and evidence labels.

## Phase 3: comparative genomics

Import orthology/family snapshots with method metadata, add alignments and phylogenetic artifacts, then add JBrowse-backed synteny and conserved-block views.

## Phase 4: expression and phenotype

Expose study/sample metadata, units, tissue/stage/treatment filters, QTL/GWAS links and existing chart abstractions.

## Phase 5: licensed resources

Add PlantTFDB, PlantCARE, PlantCyc and optional GBIF adapters only after source terms, checksums and refresh owners are recorded.

## Phase 6: query/download polish

Extend the existing asynchronous download service with a no-SQL query builder, provenance manifests, cursor pagination, accessibility and performance gates.

## Phase 1 progress record (branch `feat/blast-access-parity`)

Verified by inspection and by the gates listed below; nothing here is claimed
on the strength of a mocked response alone.

- Worker split: `apps/worker/src/soymutdb_worker/ncbi_blast.py` runs all five
  programs with fixed argv, resource limits and provenance; `tasks/blast.py`
  keeps DIAMOND as an explicit `blastp` backend. Both modules did not parse at
  all before this slice (`except OSError, UnicodeError:` / `except ValueError,
  OSError:`), so no worker test could import them; that is fixed and the
  DIAMOND-only program set is renamed `DIAMOND_PROGRAMS` so it is no longer
  readable as the platform's program list.
- Access parity: the anonymous route surfaced validation failures through
  `Alert title=`, which AntD 6 does not render, so every client-side rejection
  was silent. Fixed; the signed-in route now shares the same FASTA rule.
- Raw-result download: the anonymous page offered the presigned artifact, the
  signed-in page did not. Both now offer it as tab-separated aligner output
  (`outfmt 6`), and neither renders a link when the job has no stored artifact.
- Not done: `makeblastdb` lifecycle inside Celery, catalog build states,
  object-store index publication, real NCBI integration search in CI, and the
  admin controls for index enable/disable. The DIAMOND SQL/worker assertions and
  the API suite were not executed in this environment (no PostgreSQL, no NCBI
  BLAST+ binaries, Python 3.11 only); the TypeScript gates were.

## Current PR boundary

The follow-up access-mode slice adds anonymous submission/status/results using expiring per-job credentials and the existing outbox/worker, alongside account-owned jobs. See [implementation evidence](blast-anonymous-pr.md). The next preparation slice adds explicit catalog metadata and an operator-only immutable NCBI index builder; see [catalog/index preparation evidence](blast-index-catalog-pr.md). NCBI search execution, asynchronous index lifecycle and object-store publication remain pending. Real nucleotide/protein index construction does not establish five-program search acceptance.

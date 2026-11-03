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

## Phase 1 status: repaired but incomplete

The NCBI execution slice landed unreachable: `ncbi_blast.py` did not parse
(Python-2 `except A, B:`), and the worker whitelisted `blastp` for every engine,
so four of the five advertised programs were refused. Both are fixed and the
five programs now pass real-binary searches — see
[runtime repair evidence](blast-ncbi-runtime-repair-pr.md).

Still open in Phase 1:

- asynchronous `makeblastdb` build/publication workflow in the worker;
- protein-hit → transcript/gene resolution before genome-browser links;
- five-program UI wiring against the existing `/blast` page;
- cancellation, retry and download-expiry coverage for NCBI jobs.

## Current PR boundary

The follow-up access-mode slice adds anonymous submission/status/results using expiring per-job credentials and the existing outbox/worker, alongside account-owned jobs. See [implementation evidence](blast-anonymous-pr.md). The next preparation slice adds explicit catalog metadata and an operator-only immutable NCBI index builder; see [catalog/index preparation evidence](blast-index-catalog-pr.md). NCBI search execution, asynchronous index lifecycle and object-store publication remain pending. Real nucleotide/protein index construction does not establish five-program search acceptance.

# Incremental implementation roadmap

## Phase 0: baseline and audit (complete)

- Audited the existing BLAST API, service, model, worker, frontend, MCP manifest and tests.
- Confirmed release-scoped database discovery, transactional outbox, idempotent worker writes and authenticated researcher job ownership.
- Recorded the test baseline on Python 3.15 (see [`blast-verification-pr.md`](blast-verification-pr.md)).
- Completed a first-party external-database research pass; see [`../research/plant-database-feature-comparison.md`](../research/plant-database-feature-comparison.md). Unverifiable sources remain labelled candidates.

## Phase 1: BLAST+ (implemented, verified in this PR)

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

## Delivery notes

Earlier slices were delivered as separate commits on `main`: anonymous
capability authorization, catalog/index preparation, and NCBI execution. This
PR closes the verification gap: it makes the opt-in real-binary tests reliable
offline, aligns the architecture/roadmap documents with the implemented state,
records a first-party research ledger, and reports actual pass counts. It does
not replace the existing delivery pipeline or add a second job queue/storage
backend.

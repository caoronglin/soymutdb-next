# NCBI BLAST+ execution alongside DIAMOND

TaskStartSnapshot: base `cf51ef471abb37673af6a59e11e5066767012afc` (PR #37); branch `feat/blast-ncbi-execution`; started 2026-11-03.

Change Necessity: the preceding catalog/index preparation PR deliberately did not enable NCBI search. Implement the five programs on the existing service/outbox/worker, keep DIAMOND explicit, and preserve anonymous/account access and release provenance.

ArchitectureReviewRequired: yes. Review query/program/database compatibility, shared validation, fixed process arguments/resource isolation, frozen verified index identity/provenance, job ownership/expiry, multi-query HSP identity, migration reversibility, engine-specific parameter semantics and browser coordinate behavior.

Acceptance requires real nucleotide/protein/translated searches, exact known and reverse-strand hits, negative incompatible combinations, DIAMOND regressions, PostgreSQL persistence and privacy boundaries, generated client contracts, both UI workflows and honest deployment limitations. This record does not assert those checks are complete.

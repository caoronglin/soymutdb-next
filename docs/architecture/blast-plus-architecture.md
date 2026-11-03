# NCBI BLAST+ architecture

This document is the target contract for the next BLAST phase. The current deployment executes DIAMOND `blastp` only; this distinction is deliberate and is not hidden from users.

## Database catalog

`blast_databases` must identify species, assembly, annotation version, release, sequence type (`genome`, `cds`, `transcript`, `protein`, `repeat_masked`, `pan_genome`, `family_consensus`, `custom`), source, sequence count, total length, checksum, build status, index version, active/default state, provenance and license. Indexes are immutable objects published atomically after validation. Raw FASTA and indexes remain in configured object storage; clients receive no filesystem paths.

## Programs and engines

NCBI BLAST+ is the semantic default for `blastn`, `blastp`, `blastx`, `tblastn` and `tblastx`, with explicit compatibility checks between query/database type. DIAMOND remains an optional high-performance backend for compatible protein searches and must be selected explicitly in job provenance. The worker uses argument arrays and a fixed whitelist; arbitrary command-line flags and `shell=True` are forbidden.

## Job lifecycle

The API validates FASTA, program-specific parameters, release and database compatibility, then writes the job and transactional outbox event in one transaction. Celery performs execution, parses tabular output into normalized HSP rows, uploads raw output, and performs idempotent status/result writes. Resource caps cover CPU, memory, wall time, output size and per-user concurrency. Database construction uses `makeblastdb`, validation uses `blastdbcmd`, and publication is atomic with failed-build cleanup.

## Biological correctness

Amino-acid coordinates from `blastp` are never treated as genomic coordinates. Gene/browser links are created only after an exact protein/transcript/gene lookup in the job's release and assembly. Result downloads include checksum, expiry and provenance. Unsupported program/database pairs fail validation before a worker is queued.

## Catalog/index preparation slice

The additive catalog migration and operator-only immutable NCBI index builder implement the preparation layer described in [index operations](../ops/blast-index-builder.md). Catalogs distinguish engine/readiness and retain biological provenance; current API discovery/submission admits ready active DIAMOND protein indexes only. NCBI indexes can be built and validated with explicit metadata but are not registered or executed automatically. Five-program dispatch, asynchronous catalog build state and object-store publication remain pending; the existing DIAMOND worker is unchanged.

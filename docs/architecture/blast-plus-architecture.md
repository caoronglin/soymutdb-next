# NCBI BLAST+ architecture

This document describes the **implemented** BLAST contract. NCBI BLAST+ is the
semantic default for all five standard programs; DIAMOND `blastp` remains an
explicitly selected high-performance backend. The distinction is visible in the
API schema, the frontend selector, the outbox payload and the stored job
provenance — a job never silently switches engine.

## Database catalog

`blast_databases` identifies species, assembly, annotation version, release,
sequence type (`genome`, `cds`, `transcript`, `protein`, `repeat_masked`,
`pan_genome`, `family_consensus`, `custom`), source, sequence count, total
length, checksum, build status, index version (a 64-hex immutable identity),
active/default state, provenance and license. Indexes are immutable objects
published atomically after validation by `blastdbcmd`; see
[`docs/ops/blast-index-builder.md`](../ops/blast-index-builder.md). Raw FASTA
and indexes remain in configured object storage; clients receive no filesystem
paths. Migrations `0050` (catalog) and `0051` (per-query HSP ids) are additive.

## Programs and engines

| Program | Query | Database | Engine |
|---|---|---|---|
| blastn | nucleotide | nucleotide | NCBI BLAST+ |
| blastp | protein | protein | NCBI BLAST+ or DIAMOND |
| blastx | nucleotide, translated | protein | NCBI BLAST+ |
| tblastn | protein | nucleotide, translated | NCBI BLAST+ |
| tblastx | nucleotide, translated | nucleotide, translated | NCBI BLAST+ |

Compatibility is owned by `packages/jobs-py/src/soymutdb_jobs/blast_search.py`
and re-checked by the API (`schemas/blast.py`, `services/blast_service.py`), the
worker (`tasks/blast.py`) and the runner (`ncbi_blast.py`). DIAMOND accepts
`blastp` only; `perc_identity`, `dust` and translated programs are rejected for
it. Both runners use subprocess argument arrays and a fixed whitelist;
arbitrary command-line flags and `shell=True` are forbidden.

## Access modes (two retained flows)

- **Account jobs** (`/blast`): authenticated researcher submission, owned job
  history, listing and results. `POST /api/v1/blast/jobs` requires a session.
- **Anonymous jobs** (`/search/blast`): `POST /api/v1/blast/public/jobs` returns
  a signed, purpose-specific capability bound to one job, expiring within 24 h.
  `GET /public/jobs/{id}` and `/results` require `X-Blast-Token`; responses carry
  `Cache-Control: private, no-store` and `Vary: X-Blast-Token`. There is no
  public job listing. Both flows use the same job/outbox/worker pipeline. See
  [`docs/ops/public-blast.md`](../ops/public-blast.md).

The signed capability cannot authenticate an account: its `type`/`purpose` and
subject namespace are distinct from access/refresh tokens.

## Job lifecycle

The API validates FASTA, program-specific parameters, release and database
compatibility, then writes the job and transactional outbox event in one
transaction. Celery performs execution, parses tabular output into normalized
HSP rows, uploads raw output, and performs idempotent status/result writes.
Resource caps cover CPU, memory, wall time, output size and per-user
concurrency. Database construction uses `makeblastdb`, validation uses
`blastdbcmd`, and publication is atomic with failed-build cleanup, driven by a
persisted catalog state machine (`pending → building → validating → publishing →
ready / failed`). Only `ready` indexes are searchable.

The outbox payload freezes `engine`, `database_type`, `index_identity`,
`fasta_sha256`, `release_key`, `assembly` and `assembly_id` at submission. The
worker re-verifies the immutable index manifest against those values before it
touches a binary, so a job from release A can never execute against a release-B
index. Cancellation and expiry are re-checked by the worker before launching a
process; retries are explicit, owner-scoped, and reuse frozen
index/release/assembly provenance. Download URLs never outlive the job deadline.

## Biological correctness

Amino-acid coordinates from `blastp`/`blastx`/`tblastn` are never treated as
genomic coordinates. Gene/browser links are created only after an explicit,
assembly-scoped protein/transcript/alias → gene resolution in the job's release.
Unresolved and ambiguous subjects are persisted as
`genome_resolution.status = "unresolved"` with a machine-readable reason; no
suffix stripping, fuzzy matching or coordinate coincidence is used. Result
downloads include checksum, expiry and provenance. Unsupported program/database
pairs fail validation before a worker is queued. A BLAST hit is a similarity
candidate, never an orthology assertion.

## Verification evidence (this PR)

Real NCBI BLAST+ 2.17.0+ binaries were used to build nucleotide and protein
indexes and to execute all five programs against synthetic CC0 fixtures.
`test_blast_ncbi_pipeline.py` proves real index → real task → PostgreSQL HSP
persistence and duplicate-delivery idempotency. See
[`docs/implementation/blast-verification-pr.md`](../implementation/blast-verification-pr.md)
for commands, pass counts and environment limits.

The additive catalog migration and the worker-owned immutable NCBI index
builder implement the preparation layer described in
[index operations](../ops/blast-index-builder.md). The asynchronous catalog
build lifecycle, per-hit genome resolution and cancelled/expired/retried job
handling are implemented in this slice; the DIAMOND worker path is unchanged.

## Remaining limitations

- No production multi-species/pan-genome FASTA is bundled; release-scoped
  catalog rows must be provisioned by operators.
- DIAMOND `blastp` remains the only DIAMOND program. Custom researcher-uploaded
  FASTA databases are catalog metadata, not an implemented ingestion workflow.
- Index construction runs inside Celery on the worker's local immutable volume
  (`BLAST_INDEX_ROOT`), not through object storage; see
  [index operations](../ops/blast-index-builder.md) for the rationale.

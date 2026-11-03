# Preparing immutable NCBI BLAST+ indexes

The operator tool prepares and verifies NCBI indexes. Production builds are
driven asynchronously by the worker (see [Asynchronous build lifecycle](#asynchronous-build-lifecycle));
the CLI remains an operator/verification tool. NCBI BLAST+ is the default search
engine for all five programs; DIAMOND `blastp` remains an explicitly selected
backend. Only **published** catalog rows are searchable; building and failed
entries are excluded from search discovery and submission. Do not assign an NCBI
prefix to a DIAMOND catalog row, or a DIAMOND index to an NCBI row.

## Storage decision: worker-local indexes, one path only

Indexes live on the worker's local POSIX volume at
``SOYMUTDB_BLAST_INDEX_ROOT`` (default ``/data/blast/ncbi-indexes``). They are
**never** uploaded to or downloaded from MinIO/object storage. The reviewed
source FASTA is read from the existing object store under ``blast-sources/``,
but that is the only object-store interaction in this workflow. There is no
second path: a deployment either mounts the index volume on its ``blast`` queue
worker or cannot serve NCBI search. Rationale: a BLAST database is a directory
of several large binary files that ``makeblastdb``/``blastdbcmd`` open by
relative prefix; round-tripping it through object storage adds a download,
a checksum re-verification and a writable cache for no benefit, while the
content-addressed manifest already proves immutability on the local volume.
Do not introduce a second index transport without removing this one.

The ``blast_databases.file_path`` column is deliberately empty for published
NCBI rows: no local filesystem path is stored in PostgreSQL or exposed to any
client. The worker derives ``<index_root>/<index_identity>/db`` from the
verified build record and operator configuration only.

## Prerequisites and trust boundary

Install the existing worker package and shared `soymutdb_jobs` package in the same environment; no new Python dependency is needed. Provide operator-controlled `makeblastdb` and `blastdbcmd` executables. Validation used official NCBI BLAST+ **2.17.0+** on Linux. Output format is explicitly **BLAST database version 4**, avoiding version-5 LMDB's large virtual-address reservation under the child memory cap. This does not establish compatibility with every NCBI version.

The output root must already exist on a local POSIX filesystem with `flock`, directory fsync and atomic same-filesystem rename support. Keep it and its ancestors writable only by the operator. Source, binary and artifact symlinks and `..` traversal are rejected. Hostile concurrent mutation by another process with the same filesystem privileges is outside this tool's trust boundary. This tool is unsuitable for user-selected paths or an HTTP handler accepting arbitrary filesystem paths.

Use explicit assembly/release, annotation/source version and a reviewed license identifier. `source_url` is public attribution, never a presigned download URL: credentials, query/fragment, local paths and known private authorities are rejected using the same shared validator as API discovery. No URL is fetched and no DNS lookup is performed. This metadata check is not an HTTP fetch/SSRF policy. Manifests must be reviewed before public distribution; license and other metadata are operator-supplied assertions.

## Build and verify

The following paths and biological metadata are examples. Replace them with the actual FASTA and its reviewed source/release; keep the two binary paths pinned to the tested installation.

```bash
mkdir -p /data/blast/ncbi-indexes
python -m soymutdb_worker.blast_index build \
  --source /data/references/Wm82.a4.v1.protein.fa \
  --output-root /data/blast/ncbi-indexes \
  --db-type prot \
  --assembly-id Wm82 --assembly-version a4.v1 --release-id 2026-reviewed \
  --annotation-version a4.v1 --source-version a4.v1 \
  --source-url https://www.soybase.org/ --license CC-BY-4.0 \
  --makeblastdb-bin /opt/ncbi-blast/bin/makeblastdb \
  --blastdbcmd-bin /opt/ncbi-blast/bin/blastdbcmd
```

Use `--db-type nucl` for nucleotide FASTA. Input requires explicit, nonempty, unique FASTA identifiers. Protein validation uses the existing shared protein FASTA contract, including terminal-stop normalization. Nucleotide input supports IUPAC letters and normalizes case/whitespace. Source bytes and normalized bytes receive separate SHA-256 hashes; counts distinguish source protein residues from normalized indexed letters. The tool does not infer genes, organism identity, coordinate mappings or cross-version equivalence.

Successful stdout is one JSON object with `index_identity`, relative `index_prefix`, `manifest`, and `reused`. Failures return nonzero with a fixed JSON error, without raw sequences, child stderr or local paths. CLI syntax/unknown-option errors are handled by argparse. Binary defaults can also be set by `SOYMUTDB_MAKEBLASTDB_BIN` and `SOYMUTDB_BLASTDBCMD_BIN`.

```bash
python -m soymutdb_worker.blast_index verify \
  --output-root /data/blast/ncbi-indexes \
  --index-identity '<64-character index identity returned by build>' \
  --blastdbcmd-bin /opt/ncbi-blast/bin/blastdbcmd
```

Build occurs in a sibling `.build-*` staging directory. Fixed argument arrays invoke `makeblastdb`; `blastdbcmd -info` and explicit sequence lengths independently check database type, sequence count and total indexed letters. The builder hashes every index artifact, writes a canonical manifest, fsyncs the files/directory, then publishes with a locked atomic rename. The identity includes build options, source hashes, metadata, and both binary hashes/versions. A changed source, metadata or binary creates a new identity. Reuse verifies the exact manifest, complete artifact inventory/checksums and database contents. Corruption is rejected; an existing index is never repaired or overwritten implicitly. Binary provenance must match during verification.

The manifest contains relative artifact names and no source/index filesystem path. Index files and manifest remain operator artifacts; no new API exposes them. Publication does **not** upload index objects: the verified immutable directory
stays on the worker's local volume. PostgreSQL remains authoritative for
catalog/visibility/workflow state; the worker advances the shared build state
machine and binds one content-addressed identity to one catalog row.

## Resource limits and recovery

| Limit | Default | Scope |
|---|---:|---|
| Source FASTA bytes | 256 MiB; configurable up to 1 GiB | Source read/parser input bound |
| Wall time | 300 seconds per binary invocation | Every build/version/validation call |
| Virtual memory | 2 GiB per child | `RLIMIT_AS`; not a parent-process RAM cap |
| CPU time | 300 seconds per child | `RLIMIT_CPU`, follows wall setting |
| Threads | 1 | Fixed tool environment |
| Captured stdout/stderr | 1 MiB each | Polling checks; excessive output rejected |
| Total index artifacts | 4 GiB | Aggregate check plus per-file child limit |

FASTA parsing holds bounded source/normalized copies in parent memory. Parent RSS scales with FASTA size; use an external process/container memory limit when required. Index/binary hashing uses 1 MiB chunks. Per-call wall limits are not a single whole-build deadline. NCBI usage reporting and local configuration lookup are disabled in the child environment; secrets and ambient environment variables are not forwarded. Failed live children are terminated and reaped, and failed staging is removed. Hard process/machine crashes may leave `.build-*` or `.verify-*` staging; remove such directories only after checking that no builder owns them. Never remove a published identity to repair a live job implicitly.

The current source ceiling and in-memory parser are not a validated whole-soybean-genome ingestion claim. Large datasets require an explicit streaming/partitioning design and workload verification. Index publication is worker-local only (see above). All five NCBI programs have been verified against small synthetic fixtures (see `docs/implementation/blast-verification-pr.md`); this does not claim production-scale throughput, automatic object-store publication or a bundled multi-species dataset.

## Migration and rollback

Migration `0050` adds explicit engine/provenance metadata and readiness constraints. It reuses the historical `sequence_count`, `total_length` and `build_status` columns, preserving their values and defaults. Existing rows gain `engine=diamond` and `is_default=false`; legacy `build_status=pending` remains pending and is excluded from search. Before rollout, inspect the actual catalog statuses. An operator must verify an existing DIAMOND index before explicitly promoting its catalog status to ready; migration never fabricates readiness. Newly inserted databases inherit pending until explicitly verified. Only known protein rows are backfilled with `sequence_type=protein`; unknown nucleotide subtype, source, annotation and license remain NULL. Active default entries are unique per assembly/engine/database type. Counts and FASTA checksums have database constraints.

Public discovery emits only explicit safe metadata and runnable published-release rows. Local `file_path` and arbitrary private `provenance` JSON stay private. Existing configured database selection remains first; fallback uses the default assembly and eligible catalog defaults deterministically.

Migration 0050's downgrade refuses any non-DIAMOND, building or failed row; migration 0052's downgrade additionally refuses validating/published rows and any build record. Legacy pending and ready remain representable by the old schema. It preserves the three historical columns. This guard exists to prevent an old binary from treating an incompatible index as a ready DIAMOND database. Back up the catalog, quiesce writers, and reconcile those rows and dependent jobs before downgrade. Removing the additive metadata loses that metadata; preserve a backup. Do not delete active indexes or jobs merely to force rollback.


## Asynchronous build lifecycle

An administrator requests a build through ``POST /api/v1/blast/index-builds``.
That HTTP handler only inserts a ``blast_index_builds`` row, a pending catalog
row and one transactional-outbox event in a single transaction. It never
invokes ``makeblastdb``. The outbox dispatcher forwards
``soymutdb_worker.tasks.blast_index.build_index`` to the dedicated ``blast``
queue; the worker alone reads the reviewed FASTA, builds into a private staging
directory, verifies and publishes.

State machine (one owner: ``soymutdb_jobs.blast_catalog``):

```
pending -> building -> validating -> published
    \-> failed            \-> failed       (terminal, with sanitized reason)
```

Only ``published`` (and the legacy ``ready`` spelling for existing DIAMOND
rows) is selectable by search. Successful publication also sets the catalog
row's ``is_active`` flag, so a newly built index enters discovery without a
separate operator step. ``failed`` is terminal: retry means a **new** build
request with a **new** catalog row and a **new** content-addressed identity;
nothing is rebuilt in place. A redelivered outbox event while a build
is ``building``/``validating`` is skipped, so two builders can never publish the
same identity. Publication is a guarded conditional UPDATE shared with the
catalog row in one transaction.

Failures clear staging and record a sanitized reason; child stderr, local paths
and query sequences never reach PostgreSQL. Publication is the commit point:
the builder materializes the ``<identity>`` directory on the local volume
before the catalog row is updated, so any failure between materialization and
a committed publication (rejected catalog UPDATE, failed validation, lost
``validating`` transition) rolls that directory back together with staging.
Only a directory this attempt created (``reused=false``) is removed; a reused
directory may belong to another build and is left alone. Cleanup is strict: if
removing the materialized index fails, the task raises instead of recording a
clean failure while a half-built artifact stays on disk. A redelivery while a
build is ``building``/``validating`` never starts a second builder. If the
original attempt's claim lease has expired, the redelivery closes the row as
``failed`` with an explicit reason, so an administrator can submit a new
immutable build instead of a permanently stuck row. Hard process crashes may
leave a ``.blast-build-*`` staging directory in ``/tmp``; remove such
directories only after checking no builder owns them. Never delete a published
identity to "repair" a live job.

Environment (worker, operator-controlled; never accepted from a client):

| Variable | Default | Meaning |
|---|---|---|
| ``SOYMUTDB_BLAST_INDEX_ROOT`` | ``/data/blast/ncbi-indexes`` | Immutable index volume root |
| ``SOYMUTDB_MAKEBLASTDB_BIN`` | ``makeblastdb`` | Pinned NCBI binary |
| ``SOYMUTDB_BLASTDBCMD_BIN`` | ``blastdbcmd`` | Pinned validation binary |
| ``SOYMUTDB_BLAST_BUILD_MAX_SOURCE_BYTES`` | ``268435456`` | Source FASTA ceiling |
| ``SOYMUTDB_BLAST_BUILD_CLAIM_LEASE_SECONDS`` | ``3600`` | After this, a redelivery closes a lost claim as ``failed`` |

## Genome targets for protein hits

``blastp``/``blastx``/``tblastn`` subject coordinates are **residue** positions,
never genomic bases. A JBrowse target is produced only by
``GET /blast/jobs/{job_id}/hits/{subject_id}/genome-target`` (and its anonymous
capability variant), which resolves the subject ID through an explicit
assembly- and release-scoped gene accession, gene alias or transcript ID. An
unmapped or ambiguous subject returns ``status=unresolved`` with a reason and
**no locus**. Alignment coordinates are never read to build a location.

# Preparing immutable NCBI BLAST+ indexes

The operator tool prepares and verifies NCBI indexes. It does **not** register databases, enqueue Celery jobs or enable NCBI search. The search API still accepts DIAMOND `blastp` only. NCBI, nucleotide, building and failed catalog entries are excluded from current search discovery and submission. Do not assign an NCBI prefix to a DIAMOND catalog row.

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

The manifest contains relative artifact names and no source/index filesystem path. Index files and manifest remain operator artifacts; no new API exposes them. A later publication workflow must upload immutable objects to the existing object store and reconcile a verified manifest into PostgreSQL. PostgreSQL remains authoritative for catalog/visibility/workflow state.

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

The current source ceiling and in-memory parser are not a validated whole-soybean-genome ingestion claim. Large datasets require an explicit streaming/partitioning design and workload verification. This PR does not claim production throughput, object-store publication or all-five-program search readiness.

## Migration and rollback

Migration `0050` adds explicit engine/provenance metadata and readiness constraints. It reuses the historical `sequence_count`, `total_length` and `build_status` columns, preserving their values and defaults. Existing rows gain `engine=diamond` and `is_default=false`; legacy `build_status=pending` remains pending and is excluded from search. Before rollout, inspect the actual catalog statuses. An operator must verify an existing DIAMOND index before explicitly promoting its catalog status to ready; migration never fabricates readiness. Newly inserted databases inherit pending until explicitly verified. Only known protein rows are backfilled with `sequence_type=protein`; unknown nucleotide subtype, source, annotation and license remain NULL. Active default entries are unique per assembly/engine/database type. Counts and FASTA checksums have database constraints.

Public discovery emits only explicit safe metadata and runnable published-release rows. Local `file_path` and arbitrary private `provenance` JSON stay private. Existing configured database selection remains first; fallback uses the default assembly and eligible catalog defaults deterministically.

Downgrade refuses any non-DIAMOND, building or failed row; legacy pending and ready remain representable by the old schema. It preserves the three historical columns. This guard exists to prevent an old binary from treating an incompatible index as a ready DIAMOND database. Back up the catalog, quiesce writers, and reconcile those rows and dependent jobs before downgrade. Removing the additive metadata loses that metadata; preserve a backup. Do not delete active indexes or jobs merely to force rollback.

# SoyMutDB Worker

Celery worker application for SoyMutDB — handles asynchronous bioinformatics
tasks including BLAST searches, data export, VCF/GFF3 ingestion, statistics
computation, and cleanup.

## Architecture

```
apps/worker/
├── src/soymutdb_worker/
│   ├── main.py          # Celery app config (7 queues, beat schedule)
│   ├── utils/s3.py      # S3 streaming, multipart upload, presigned URLs
│   └── tasks/
│       ├── blast.py     # BLAST search (subprocess, no shell, param whitelist)
│       ├── export.py    # Variant export (vcf/tsv/csv/json/bed, gzip, S3)
│       ├── ingest.py    # VCF/GFF3 ingestion (cyvcf2, idempotent, SnpEff ANN)
│       ├── stats.py     # Statistics (release stats, density, gene burden)
│       └── cleanup.py   # Cleanup (expired BLAST results, temp files)
├── pyproject.toml
└── Dockerfile
```

## Queues

| Queue     | Tasks                          |
|-----------|--------------------------------|
| ingest    | VCF/GFF3/mutant-line ingestion |
| blast     | BLAST searches                 |
| export    | Variant export                 |
| stats     | Statistics computation         |
| cleanup   | Cleanup tasks                  |
| default   | Misc / un-routed tasks         |
| priority  | High-priority tasks            |

## Key Design Decisions

- **Python 3.13** for bioinformatics library compatibility (cyvcf2, pysam).
- **Idempotent ingestion**: variant IDs are deterministic SHA-256 hashes of
  `release_id + file_key + chromosome + position + ref + alt`, not in-memory
  counters.
- **No shell execution**: BLAST runs via `subprocess.run` with argument lists,
  never `shell=True`.
- **Parameter whitelisting**: BLAST program and parameters are validated
  against whitelists before execution.
- **Resource limits**: BLAST subprocesses have CPU, memory, and time limits.
- **Parameterised queries**: all ClickHouse queries use `%(name)s` bindings.

## Running

```bash
# Install dependencies
uv pip install -e .

# Start worker
celery -A soymutdb_worker.main worker --loglevel=info

# Start beat scheduler
celery -A soymutdb_worker.main beat --loglevel=info
```

## Docker

```bash
docker build -t soymutdb-worker .
docker run soymutdb-worker
```

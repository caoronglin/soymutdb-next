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
└── pyproject.toml      # image definition: infra/docker/Dockerfile.worker
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

- **Python 3.15** (pinned in `pyproject.toml` and the image tag), matching the
  API service and `packages/jobs-py` so the shared job contract cannot be
  resolved by two different interpreters.
- **Idempotent ingestion**: variant IDs are deterministic SHA-256 hashes of
  `release_id + file_key + chromosome + position + ref + alt`, not in-memory
  counters.
- **No shell execution**: BLAST runs via `subprocess.run` with argument lists,
  never `shell=True`.
- **Parameter whitelisting**: BLAST program and parameters are validated
  against whitelists before execution.
- **Resource limits**: BLAST subprocesses have CPU, memory, and time limits.
- **Parameterised queries**: PostgreSQL stores variant facts and analytics; the explicit legacy HTTP backfill uses typed ClickHouse parameters.

## Running

The workspace is managed by the locked project (`uv.lock`), not by an ad-hoc
`pip install`. Rebuilding that graph outside the lockfile is how a machine ends
up running different Celery/psycopg/pysam versions than the image does.

```bash
# From apps/worker: resolve the locked dependency set into .venv
uv sync --frozen

# Start worker
uv run celery -A soymutdb_worker.main:celery_app worker --loglevel=info

# Start beat scheduler
uv run celery -A soymutdb_worker.main:celery_app beat --loglevel=info
```

Both commands name the app as `soymutdb_worker.main:celery_app`, which is
exactly what `docker-compose.yml` and `infra/docker/Dockerfile.worker` pass to
`celery -A`. The image puts the source roots on `PYTHONPATH`
(`/app/packages/jobs-py/src:/app/apps/worker/src`) instead of installing the
project into `/opt/venv`, so the same import works in both places.

## Docker

```bash
# Root-context build (the Dockerfile COPYs apps/worker and packages/jobs-py)
docker build -f infra/docker/Dockerfile.worker -t soymutdb-worker .

# Or bring it up with its dependencies from the repository root
docker compose --profile core up -d worker-default
```

`docker build -t soymutdb-worker .` without `-f` looks for a `Dockerfile` in
`apps/worker/`, which does not exist — the image definition lives in
`infra/docker/Dockerfile.worker` and its build context is the repository root.

## Python 3.15 与历史引擎验收

默认服务和 `.[dev]` 使用 Python 3.15，事实与统计均访问 PostgreSQL。
`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1` 和显式测试数据库启用真实 PostgreSQL 测试；
`SOYMUTDB_RUN_2M_IMPORT_PERF=1` 启用两百万行验收；
`SOYMUTDB_TEST_DIAMOND_BIN` 指向真实 DIAMOND 二进制。

chdb 的 Python 扩展目前只附带到 3.14 的动态 shim，不能作为 3.15 dev 依赖。
五个历史引擎测试模块由 `scripts/verify-legacy-worker-tests.sh` 在既有 Python 3.14
`clickhouse-migration` 强制 CI 通道执行。该脚本声明自己的测试依赖，要求真实 PostgreSQL；
原生服务不安装历史引擎，不将历史兼容性测试的缺失算作通过。

当前本机原生 657 tests / 历史 33 tests 及镜像验证边界见
[全栈验收](../../docs/dev/fullstack-validation-20261015.md)。

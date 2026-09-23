# Mamba PostgreSQL Validation Environment

This workspace can run PostgreSQL-backed API validation without Docker/Testcontainers. It keeps Mamba packages and database data inside ignored workspace-local directories.

## Components

- PostgreSQL runtime: `.mamba-root/envs/postgres16` (PostgreSQL 16)
- Mamba root/package cache: `.mamba-root/`
- PostgreSQL data and logs: `.validation/postgres16` and `.validation/postgres16.log`
- Application test interpreter: the repository-pinned 3.14 virtualenvs — `apps/api/.venv` (api[dev] + worker[dev], the layout `scripts/verify-backend-tests.sh` expects) and `apps/worker/.venv` (worker[dev]). The historical `soymutdb-test` mamba interpreter is Python 3.13 and predates the 3.14 toolchain pin; do not use it for the gates.
- Runtime migration database: `soymutdb_validation`
- Isolated pytest fixture database: `soymutdb_testfixtures`

The migration database must not be used for pytest fixtures: the fixture intentionally creates and drops metadata, while the migration database verifies Alembic upgrades.

## Bootstrap PostgreSQL

```bash
cd /mnt/data02/T25ronglin/code/web
mkdir -p .mamba-root/pkgs .mamba-root/envs .validation
MAMBA_ROOT_PREFIX=$PWD/.mamba-root CONDA_PKGS_DIRS=$PWD/.mamba-root/pkgs \
  /mnt/data02/T25ronglin/.miniforge3/bin/mamba create \
  -p $PWD/.mamba-root/envs/postgres16 --override-channels -c conda-forge \
  postgresql=16 -y

PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/initdb -D $PWD/.validation/postgres16 \
  --username=soymutdb --auth=trust --encoding=UTF8 --locale=C
```

Start PostgreSQL within the validation command that uses it. The harness shell may terminate background children after a command returns.

```bash
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/postgres -D $PWD/.validation/postgres16 -p 55432 \
  -c listen_addresses=127.0.0.1 \
  -c shared_preload_libraries=pg_stat_statements &
PG_PID=$!
trap 'kill $PG_PID 2>/dev/null || true' EXIT
sleep 1
```

## Migrate and verify runtime schema

```bash
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_validation || true
$PG_BIN/psql -p 55432 -h 127.0.0.1 -U soymutdb -d soymutdb_validation \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements;'

cd apps/api
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_validation' \
  /mnt/data02/T25ronglin/.miniforge3/envs/soymutdb-test/bin/python -m alembic upgrade head
```

Verify the expected state:

```bash
$PG_BIN/psql -p 55432 -h 127.0.0.1 -U soymutdb -d soymutdb_validation \
  -c 'SELECT version_num FROM alembic_version;' \
  -c 'SHOW shared_preload_libraries;' \
  -c "SELECT extname FROM pg_extension WHERE extname = 'pg_stat_statements';"
```

## Run isolated PostgreSQL pytest fixtures

The API test harness accepts `SOYMUTDB_TEST_DATABASE_URL`. When it is set, it bypasses Testcontainers but preserves the create/seed/drop schema lifecycle. Use a fresh fixture database for every run.

```bash
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_testfixtures
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_testfixtures

SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  /mnt/data02/T25ronglin/.miniforge3/envs/soymutdb-test/bin/python -m pytest \
  apps/api/tests/test_page_definition_public.py \
  apps/api/tests/test_page_template_database_integration.py \
  apps/api/tests/test_static_page_migration_database_integration.py \
  apps/api/tests/test_search_database_integration.py \
  apps/api/tests/test_conftest_database_url.py -q
```

`db_session` uses an outer transaction and savepoint mode so application-level `commit()` calls do not leak state into following tests.

## Full local gates without Docker

Every gate the delivery pipeline runs is reachable here; only the container
(image) and browser layers need more than this environment. Each database role
is exercised against the same cluster: `soymutdb_testfixtures` is
created/dropped by the fixtures (keep it empty before a run) and
`soymutdb_validation` carries the migrated runtime schema.

```bash
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin

# 1. Backend gate: architecture guard + API pytest + worker pytest
#    (real PostgreSQL fixtures + embedded ClickHouse via chdb)
$PG_BIN/dropdb -p 55432 -h 127.0.0.1 -U soymutdb --if-exists soymutdb_testfixtures
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_testfixtures
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  bash scripts/verify-backend-tests.sh

# 2. Runtime smoke: Alembic + real uvicorn + health + public API chain
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_validation' \
  bash scripts/acceptance.sh --profile runtime

# 3. Acceptance layers
bash scripts/acceptance.sh --profile contracts
GOMAXPROCS=2 bash scripts/build-static-apps.sh   # base=/ build for the static layer
bash scripts/acceptance.sh --profile static
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  bash scripts/acceptance.sh --profile backend
```

Builds in constrained sandboxes must cap the JS/Rust thread pools
(`GOMAXPROCS=2 RAYON_NUM_THREADS=1`; esbuild/tailwind-oxide otherwise abort with
EAGAIN) and run turbo task graphs with `--concurrency=1`.

The dual-site artifacts build and verify locally too:

```bash
CI= VITE_DEPLOYMENT_MODE=demo \
  VITE_API_BASE_URL=https://api.soymutdb.test \
  VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  SOYMUTDB_INTERNAL_SITE_URL=https://internal.soymutdb.invalid \
  GOMAXPROCS=2 pnpm --filter @soymutdb/web build:sites
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel 'noindex, nofollow, noarchive'
```

For the local browser suite use `e2e/README.md`'s dedicated build command
(base `/soymutdb-next/`, same-origin mocked API) with
`playwright-public.config.ts`; the default e2e config targets the deployed
demo site and needs network access.

## Scope and limits

This environment replaces local PostgreSQL/Testcontainers needs only. It does not provide Redis, MinIO, ClickHouse, a browser server, or packaged desktop WebView coverage. Keep production deployment validation and browser performance evidence separate.

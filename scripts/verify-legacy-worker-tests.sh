#!/usr/bin/env bash
# Historical engine acceptance: runs only in the Python 3.14 migration lane.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_PYTHON="${SOYMUTDB_LEGACY_TEST_PYTHON:-${CLICKHOUSE_MIGRATION_PYTHON:-python3}}"
"${LEGACY_PYTHON}" -c 'import sys; assert sys.version_info[:2] == (3, 14), "legacy engine acceptance requires Python 3.14"'
if [[ "${SOYMUTDB_LEGACY_TEST_INSTALL:-1}" == 1 ]]; then
  "${LEGACY_PYTHON}" -m pip install --disable-pip-version-check \
    -r "${REPO_ROOT}/scripts/legacy-worker-test-requirements.txt"
fi
export SOYMUTDB_PG_READY_PYTHON="${LEGACY_PYTHON}"
PG_ENV="$(bash "${REPO_ROOT}/scripts/with-postgres-service.sh" --print-exports)"
while IFS='=' read -r key value; do
  [[ -n "${key}" ]] && export "${key}=${value}"
done <<< "${PG_ENV}"
export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1
export SOYMUTDB_RUN_LEGACY_CHDB_TESTS=1
export PYTHONPATH="${REPO_ROOT}/apps/worker/src:${REPO_ROOT}/packages/jobs-py/src:${REPO_ROOT}/packages/import-protocol/src:${REPO_ROOT}/apps/api:${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${REPO_ROOT}/apps/worker"
"${LEGACY_PYTHON}" -m pytest -q \
  tests/test_clickhouse_engine.py tests/test_clickhouse_production_ddl.py \
  tests/test_variant_finalize.py tests/test_legacy_clickhouse_migration.py \
  tests/test_vcf_import.py

#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — backend verification (single source for CI and local runs)
# =============================================================================
# Owns the ordered, blocking backend gates:
#   import-architecture guard → API pytest → worker analysis deps →
#   worker pytest (real PostgreSQL integration required).
#
# The integration flag is mandatory: a missing Docker/PostgreSQL must fail this
# script instead of silently skipping the privacy/identity/assembly matrix.
#
# The database comes from scripts/with-postgres-service.sh, which is also what
# makes this gate portable: on CNB the stage must declare `services: [docker]`
# and the script starts a disposable PostgreSQL through the dind daemon; on a
# developer machine or the GitHub runner an existing SOYMUTDB_TEST_DATABASE_URL
# is used as-is, and Testcontainers remains the fallback when neither applies.
#
# Requirements: apps/api/.venv with `pip install -e "apps/api[dev]"` and
#               `pip install -e packages/jobs-py`.
# Usage: bash scripts/verify-backend-tests.sh
# Env:   SOYMUTDB_TEST_DATABASE_URL  optional explicit test PostgreSQL
#        SOYMUTDB_RUN_POSTGRES_INTEGRATION must stay "1"
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VENV_PYTHON="${SOYMUTDB_API_PYTHON:-${REPO_ROOT}/apps/api/.venv/bin/python}"
[[ -x "${VENV_PYTHON}" ]] || {
  echo "missing API virtualenv python: ${VENV_PYTHON}" >&2
  exit 1
}

step() { printf '\n==> %s\n' "$*"; }

# The suite's PostgreSQL backend is resolved ONCE, before any test runs, so a
# missing prerequisite is a single clear failure at the top of the job instead
# of 116 per-test docker stack traces. The resolver is fail-closed: it exits
# non-zero rather than letting the privacy/identity/assembly matrix skip green.
step "Resolve the disposable PostgreSQL test backend"
# A child process cannot export into this shell, so the resolver prints
# `KEY=VALUE` lines that are re-exported here. This is deliberately not
# `source`-based: a CNB stage script is run with `sh` (dash), where `source`
# does not exist. Exits non-zero when no database is available, so a missing
# prerequisite fails here instead of skipping the identity matrix.
PG_ENV="$("${REPO_ROOT}/scripts/with-postgres-service.sh" --print-exports)"
while IFS='=' read -r key value; do
  [[ -n "${key}" ]] || continue
  export "${key}=${value}"
done <<< "${PG_ENV}"
[[ -n "${SOYMUTDB_TEST_DATABASE_URL:-}" ]] || {
  echo "the PostgreSQL resolver returned no SOYMUTDB_TEST_DATABASE_URL" >&2
  exit 1
}
export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1

step "Backend import-direction and cycle guard"
"${VENV_PYTHON}" scripts/check_architecture.py --self-test
"${VENV_PYTHON}" scripts/check_architecture.py

step "API pytest (full tree)"
(
  cd apps/api
  PYTHONPATH="${REPO_ROOT}" "${VENV_PYTHON}" -m pytest tests -q
)

step "Worker analysis dependencies"
"${VENV_PYTHON}" -m pip install --quiet -e apps/worker
"${VENV_PYTHON}" -c "import scanpy, anndata, leidenalg, igraph, matplotlib; print('analysis deps OK:', scanpy.__version__)"

step "Worker pytest (PostgreSQL integration required)"
export PYTHONPATH="${REPO_ROOT}"
export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1
"${VENV_PYTHON}" -m pytest apps/worker/tests -q

printf '\nbackend verification passed\n'

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

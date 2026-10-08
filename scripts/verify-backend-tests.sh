#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — backend verification (single source for CI and local runs)
# =============================================================================
# Owns the ordered, blocking backend gates:
#   import-architecture guard → shared job contract pytest → API pytest →
#   worker analysis deps → worker pytest (real PostgreSQL integration required).
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
#               editable workspace distributions (the shared bootstrap
#               scripts/install_python_workspace.py owns that install plan).
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
# The resolver runs in a child process, so it cannot export into this shell.
# Two consumption paths exist and BOTH must work:
#
#   * `--print-exports` returns `KEY=VALUE` lines this shell re-exports.
#     `source` is deliberately not used at the call site: a CNB stage script is
#     executed with `sh` (dash), where `source` does not exist.
#   * `--ensure` additionally writes the same lines to $SOYMUTDB_PG_ENV_FILE for
#     callers that prefer a file. This script is the contract its own test
#     suite pins ("The gate consumes the resolver's output"), so it owns
#     keeping that file load-bearing: a remediation step that exports through
#     `--ensure` and is then ignored here would report success while the suite
#     still ran against Testcontainers.
#
# Exits non-zero when no database is available, so a missing prerequisite fails
# here instead of skipping the identity matrix.
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

step "Shared job contract pytest"
# packages/jobs-py is the canonical owner of the job payloads, the status
# machine and the protein-FASTA submission contract. Both the API and the
# worker validate against it, so its own tests belong to this gate; without
# this step a change to the shared owner would be unexercised here.
PYTHONPATH="${REPO_ROOT}" "${VENV_PYTHON}" -m pytest packages/jobs-py/tests -q

step "API pytest (full tree)"
(
  cd apps/api
  PYTHONPATH="${REPO_ROOT}" "${VENV_PYTHON}" -m pytest tests -q
)

step "Worker test package marker (cross-module imports must resolve)"
# Cheap and it must fail before the expensive worker install: a collection error
# aborts the whole worker run, so a broken import here would hide every other
# worker test. Catches files that are present-but-untracked too.
"${VENV_PYTHON}" scripts/check_worker_test_package.py

step "Worker analysis dependencies"
# Install the worker dev extra too: the import finalize/staging protocol is
# accepted against a real embedded ClickHouse (`chdb`), which lives in the
# worker's dev extra and runs in this shared venv. The shared bootstrap
# installs the editable workspace distributions (packages/jobs-py,
# packages/import-protocol) first, because pip cannot fetch the import protocol
# from PyPI.
VENV_DIR="$(dirname "$(dirname "${VENV_PYTHON}")")"
"${VENV_PYTHON}" scripts/install_python_workspace.py \
  --venv "${VENV_DIR}" \
  "apps/worker[dev]"
"${VENV_PYTHON}" -c "import scanpy, anndata, leidenalg, igraph, matplotlib; print('analysis deps OK:', scanpy.__version__)"

step "Worker pytest (PostgreSQL integration required)"
export PYTHONPATH="${REPO_ROOT}"
export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1
"${VENV_PYTHON}" -m pytest apps/worker/tests -q

printf '\nbackend verification passed\n'

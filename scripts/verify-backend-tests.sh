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
#               artifacts/wheels/soymutdb_bio_core-*-cp315-*.whl MUST already
#               exist: it is built once by the `bio-core` job
#               (scripts/verify-bio-core.sh). This gate only INSTALLS it; a
#               missing wheel is a hard failure, never a skip.
#               The worker science stack needs system HDF5 headers on Python
#               3.15; scripts/install-worker-science-build-deps.sh provisions
#               them before the worker editable install.
# Usage: bash scripts/verify-backend-tests.sh
# Env:   SOYMUTDB_TEST_DATABASE_URL  optional explicit test PostgreSQL
#        SOYMUTDB_RUN_POSTGRES_INTEGRATION must stay "1"
#        HDF5_PKGCONFIG_NAME          defaults to hdf5-serial for h5py
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

step "Retired ClickHouse lane import-boundary guard"
# The retired service is documented as a migration/test surface only. This gate
# proves the Python import graph agrees; the Compose side is covered by
# scripts/test_native_compose_cutover_contracts.py.
"${VENV_PYTHON}" scripts/check_retired_lane_boundaries.py --self-test
"${VENV_PYTHON}" scripts/check_retired_lane_boundaries.py

step "Deprecated-API ratchet"
# apps/api blanket-ignores DeprecationWarning, so this ratchet is the only
# thing that notices a newly deprecated upstream API.
"${VENV_PYTHON}" scripts/check_deprecated_api_usage.py --self-test
"${VENV_PYTHON}" scripts/check_deprecated_api_usage.py

step "Install the Rust bio-core wheel into the API test venv"
# The /tools/sequence/* and /tools/intervals/overlap endpoints are backed by a
# private compiled extension. Their API tests (and the wheel contract tests)
# must run against the SAME artifact the release images ship, not against a
# source-tree import or a Python look-alike.
#
# The wheel is built ONCE by the `bio-core` job (scripts/verify-bio-core.sh),
# which is the only stage with a Rust toolchain and a C linker. This `api-tests`
# stage is a bare python:3.15: it has no cargo, no curl to bootstrap rustup, no
# cc. Building here would fail on the first CI run for a reason unrelated to
# this change, and an uncached native build (bio/noodles/rust-lapper/bio-seq,
# thin LTO, codegen-units=1) would add minutes to every PR push.
#
# So this gate CONSUMES the wheel the producer left under /workspace, and is
# fail-closed: spec §13.5 requires "install, don't just build", and the sequence
# tools are specified to fail closed with 503, so the gate cannot quietly pass
# without the engine present. A missing or ambiguous wheel fails here — it can
# never skip.
BIO_CORE_WHEEL_DIR="${SOYMUTDB_BIO_CORE_WHEEL_DIR:-${REPO_ROOT}/artifacts/wheels}"
shopt -s nullglob
BIO_CORE_WHEELS=( "${BIO_CORE_WHEEL_DIR}"/soymutdb_bio_core-*-cp315-*.whl )
shopt -u nullglob
if [[ ${#BIO_CORE_WHEELS[@]} -ne 1 || ! -f "${BIO_CORE_WHEELS[0]:-}" ]]; then
  echo "expected exactly one cp315 bio-core wheel in ${BIO_CORE_WHEEL_DIR}, found ${#BIO_CORE_WHEELS[@]}" >&2
  echo "the bio-core job (scripts/verify-bio-core.sh) must build it before this gate runs" >&2
  echo "a sequence tool without its engine fails closed with 503, so this cannot be a skip" >&2
  exit 1
fi
BIO_CORE_WHEEL="${BIO_CORE_WHEELS[0]}"
echo "bio-core wheel: ${BIO_CORE_WHEEL}"
"${VENV_PYTHON}" -m pip install --quiet --force-reinstall --no-deps "${BIO_CORE_WHEEL}"
"${VENV_PYTHON}" -c "import soymutdb_bio_core as c; print('bio-core wheel:', c.capabilities()['engine_version'])"

step "Shared job contract pytest"
# packages/jobs-py is the canonical owner of the job payloads, the status
# machine and the protein-FASTA submission contract. Both the API and the
# worker validate against it, so its own tests belong to this gate; without
# this step a change to the shared owner would be unexercised here.
PYTHONPATH="${REPO_ROOT}" "${VENV_PYTHON}" -m pytest packages/jobs-py/tests -q

step "Rust bio-core wheel contract (pytest against the installed artifact)"
PYTHONPATH="${REPO_ROOT}" "${VENV_PYTHON}" -m pytest \
  "${REPO_ROOT}/packages/bio-core/python_tests" -q

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
# Install the native worker dev extra. Historical embedded ClickHouse tests
# run in the mandatory Python 3.14 clickhouse-migration lane. The shared bootstrap
# installs the editable workspace distributions (packages/jobs-py,
# packages/import-protocol) first, because pip cannot fetch the import protocol
# from PyPI.
#
# Python 3.15 has no h5py wheel: importing the worker's scanpy/anndata stack
# forces a source build that needs system HDF5 headers. The bare `python:3.15`
# CI image lacks them (real CNB build cnb-7cn-1k6gvafcf failed with
# "libhdf5.so: cannot open shared object file"). Provision the same recipe as
# infra/docker/Dockerfile.worker BEFORE the editable install, and point h5py
# at Debian/Ubuntu's serial pkg-config flavour. Both CI providers reach this
# through this one gate, so the system prerequisites cannot drift.
export HDF5_PKGCONFIG_NAME="${HDF5_PKGCONFIG_NAME:-hdf5-serial}"
bash "${REPO_ROOT}/scripts/install-worker-science-build-deps.sh"
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

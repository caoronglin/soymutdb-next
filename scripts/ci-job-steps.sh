#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — canonical CI job step library
# =============================================================================
# Purpose
#   The delivery pipeline used to be written twice: once for GitHub Actions and
#   once (implicitly) nowhere. Every job body now lives here exactly once and is
#   invoked as `<shared-dir>/ci-job-steps.sh <job>`. The GitHub workflows and
#   the CNB pipelines both call the same functions, so a behaviour change cannot
#   drift between the two providers.
#
# Contract (read this before adding a job)
#   * Functions are pure w.r.t. the repository: they read/write only inside the
#     checkout plus the caller-provided artifact/output directories.
#   * Everything is driven by environment variables so the same function runs on
#     a GitHub runner, a CNB docker runner, or a developer machine.
#   * Steps that the CI provider must expose as separate, retryable units stay
#     provider-native: GitHub renders ordered `steps:` with upload/download
#     actions, CNB renders stage `script` blocks. This library owns the job
#     BODIES; the provider configs own the sequencing.
#   * No secrets are read or printed here. Credentials arrive through the
#     environment or through the provider's injected CNB_* variables.
#
# Usage
#   bash scripts/ci-job-steps.sh list
#   bash scripts/ci-job-steps.sh run <job>
#     run is the real implementation: `run <job>` forwards to `<job>_run`.
#
#   `list` / `run` are the complete interface. An earlier revision also
#   advertised `emit github|cnb`, which delegated to a generator script that was
#   never committed; the command was removed rather than left as a declaration
#   that could not run. The pipeline definitions are maintained directly in
#   .cnb.yml and the GitHub workflows, and scripts/test_ci_job_contracts.py
#   asserts that both only delegate here.
#
# Verification
#   scripts/test_ci_job_contracts.py asserts the documented behaviours of the
#   verify/image/contracts jobs without needing either CI provider.
# =============================================================================
set -euo pipefail

SHARED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SHARED_DIR
REPO_ROOT="$(cd "${SHARED_DIR}/.." && pwd)"
export REPO_ROOT

# --- shared configuration ----------------------------------------------------
# Versions are duplicated by design: the scheduler jobs (frontend/api/contracts)
# cannot `source` a checked-out script until after the checkout step. Keeping one
# copy here plus one in .cnb.yml + one in ci.yml is guarded by
# scripts/test_ci_job_contracts.py, which fails when the three disagree.
NODE_VERSION="${SOYMUTDB_CI_NODE_VERSION:-26.13.0}"
PNPM_VERSION="${SOYMUTDB_CI_PNPM_VERSION:-12.11.2}"
PYTHON_VERSION="${SOYMUTDB_CI_PYTHON_VERSION:-3.15}"
UV_VERSION="${SOYMUTDB_CI_UV_VERSION:-0.13.1}"
export NODE_VERSION PNPM_VERSION PYTHON_VERSION UV_VERSION

# --- container lifecycle ------------------------------------------------------
# Every CNB stage runs in its own fresh container, so nothing a previous stage
# did to the filesystem survives into this one. `corepack enable` in a "setup"
# stage does NOT make pnpm available here, and node_modules is not carried over
# either. The observable failure is:
#
#   scripts/ci-job-steps.sh: line 89: pnpm: command not found        (exit 127)
#
# So each job body that needs the JS toolchain bootstraps it itself, through
# scripts/setup-workspace.sh. That is idempotent and store-linked, so the cost is
# a link pass rather than a download pass. Only the pipeline's declared
# `docker.volumes` (the pnpm store) cross the container boundary; turbo's cache
# simply lives under the always-shared /workspace.
ensure_workspace() {
  bash "${REPO_ROOT}/scripts/setup-workspace.sh"
}

ensure_pnpm() {
  bash "${REPO_ROOT}/scripts/setup-workspace.sh" --enable-only
}

# Demo build origins. The offline verification build must never need a live API.
export SOYMUTDB_CI_DEMO_MODE="${SOYMUTDB_CI_DEMO_MODE:-demo}"
export SOYMUTDB_CI_DEMO_API_URL="${SOYMUTDB_CI_DEMO_API_URL:-https://api.soymutdb.test}"
export SOYMUTDB_CI_DEMO_JBROWSE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL:-https://jbrowse.soymutdb.test}"

log() { printf '[ci-job-steps] %s\n' "$*" >&2; }

# `pnpm deps:graphs|deps:audit` shell out to scripts/dependency_governance.py,
# which imports PyYAML AND drives `uv`/`uvx` for the Deptry/license analyzers.
# The GitHub mirror installs both explicitly
# (`python -m pip install --quiet PyYAML==6.0.3 uv==0.13.1`), but the CNB
# governance stage ran in `node:26.13.0`, whose only Python is the bare
# interpreter from the base image (for node-gyp, with no pip) -- so the job
# died before any analyzer ran:
#
#   $ python3 scripts/dependency_governance.py graphs --output ...
#   ModuleNotFoundError: No module named 'yaml'
#
# Installing them here rather than in the pipeline keeps both providers on the
# same bytes and the same pins, and keeps `scripts/` the single source of truth.
# `UV_VERSION` is the same pin the Dockerfiles and `check-toolchain-pins.py`
# enforce, so the analyzers cannot run on a different uv than production.
GOVERNANCE_PYYAML_VERSION="${SOYMUTDB_CI_PYYAML_VERSION:-${SOYMUTDB_CI_GOVERNANCE_PYYAML_VERSION:-6.0.3}}"

# The contracts layer runs pytest, and the `python:3.15` stage image ships no
# test runner. CNB build cnb-66s-1k4i8rfii (2026-10-10) failed the smoke-contracts
# stage with "pytest is required for the contracts smoke layer" — the job existed
# and was wired into both providers, but had never actually executed, so its
# prerequisites were never exercised. Every other contract import is either
# stdlib or vendored in scripts/ (compose_loader.py), so pytest is the whole gap.
# Matches the floor in apps/api/pyproject.toml ("pytest>=8.0.0").
CONTRACTS_PYTEST_VERSION="${SOYMUTDB_CI_PYTEST_VERSION:-9.1.1}"

# PyYAML is the second requirement, and it is not obvious: `compose_loader` is
# vendored under scripts/, so the compose and Dockerfile contracts import it as
# if it were a third-party package, and it in turn imports yaml. The contracts
# layer therefore needs PyYAML even though the only pytest targets are repo
# files. Both pins are enforced together by
# scripts/test_ci_job_contracts.py::test_contracts_job_provisions_every_import_it_needs,
# which reads the layer's import graph instead of trusting this comment.

# Debian-based `node:*` images ship a bare `python3` (for node-gyp) without the
# `pip` module. A bare `python3 -m pip` therefore fails there, so bootstrap pip
# with `ensurepip` before giving up: the failure this whole function exists to
# fix must not be replaced by "No module named pip".
ensure_governance_pip() {
  local interpreter="$1"
  "${interpreter}" -m pip --version >/dev/null 2>&1 && return 0
  log "pip is unavailable for ${interpreter}; bootstrapping it with ensurepip"
  "${interpreter}" -m ensurepip --upgrade >/dev/null 2>&1 && return 0
  log "cannot bootstrap pip; the governance gate needs PyYAML and uv"
  return 1
}

governance_pip_install() {
  local interpreter="$1"
  shift
  PIP_NO_CACHE_DIR=1 PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 \
    "${interpreter}" -m pip install --quiet --break-system-packages "$@"
}

ensure_contracts_python() {
  local interpreter
  interpreter="$(command -v python3 || true)"
  [[ -n "${interpreter}" ]] || {
    log "the contracts stage image must provide python3"
    return 1
  }
  if ! interpreter_matches_pin "${interpreter}"; then
    log "cannot run the contract suites: ${interpreter} is $("${interpreter}" -V 2>&1), not ${PYTHON_VERSION}"
    return 1
  fi

  local -a required=(
    "pytest==${CONTRACTS_PYTEST_VERSION}"
    "PyYAML==${GOVERNANCE_PYYAML_VERSION}"
  )
  local -a missing=()
  local spec
  for spec in "${required[@]}"; do
    case "${spec}" in
      pytest*) "${interpreter}" -m pytest --version >/dev/null 2>&1 || missing+=("${spec}") ;;
      *) "${interpreter}" -c "import yaml" >/dev/null 2>&1 || missing+=("${spec}") ;;
    esac
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    ensure_governance_pip "${interpreter}" || return 1
    log "installing ${missing[*]} for the contract suites"
    governance_pip_install "${interpreter}" "${missing[@]}" || return 1
  fi

  # Verified, not assumed: scripts/smoke.sh checks this itself and would
  # otherwise fail with a bare "pytest is required", which reads as a missing
  # test dependency rather than a stage that never provisioned one. PyYAML
  # fails later and further away -- as a collection error naming an unrelated
  # contract file -- which is why it is checked here too.
  "${interpreter}" -m pytest --version >/dev/null 2>&1 || {
    log "pytest is still not runnable by ${interpreter}; the contracts gate cannot run"
    return 1
  }
  "${interpreter}" -c "import yaml" >/dev/null 2>&1 || {
    log "PyYAML is still not importable by ${interpreter}; the compose contracts cannot run"
    return 1
  }
}

ensure_governance_python() {
  local interpreter
  interpreter="$(command -v python3 || true)"
  [[ -n "${interpreter}" ]] || {
    log "the governance stage image must provide python3 for the dependency graphs"
    log "it runs scripts/dependency_governance.py and every Python analyzer"
    return 1
  }

  # Fail closed on an interpreter the repository never declared: the analyzers
  # resolve dependencies against the pinned Python, so running them under a
  # stray 3.11 would report findings for a toolchain nothing ships.
  if ! interpreter_matches_pin "${interpreter}"; then
    log "cannot run dependency governance: ${interpreter} is $("${interpreter}" -V 2>&1), not ${PYTHON_VERSION}"
    return 1
  fi

  # Idempotent and quiet when already satisfied, so a warm container pays
  # nothing and a developer machine is not disturbed.
  if ! "${interpreter}" -c 'import yaml' >/dev/null 2>&1; then
    ensure_governance_pip "${interpreter}" || return 1
    log "installing PyYAML==${GOVERNANCE_PYYAML_VERSION} for the dependency graphs"
    governance_pip_install "${interpreter}" "PyYAML==${GOVERNANCE_PYYAML_VERSION}" || return 1
  fi

  "${interpreter}" -c 'import yaml' >/dev/null 2>&1 || {
    log "PyYAML is still not importable by ${interpreter}"
    return 1
  }

  # The audit policy drives `uvx`; without it every analyzer is reported
  # unavailable, which the fail-closed gate counts as a failure anyway. Install
  # the pinned uv now so the gate produces evidence instead of a toolchain error.
  if ! command -v uv >/dev/null 2>&1; then
    ensure_governance_pip "${interpreter}" || return 1
    log "installing uv==${UV_VERSION} for the governance analyzers"
    governance_pip_install "${interpreter}" "uv==${UV_VERSION}" || return 1
  fi

  if ! command -v uv >/dev/null 2>&1; then
    log "uv is unavailable; the Deptry/license analyzers cannot run"
    log "the governance gate is fail-closed, so this is an error, not a skip"
    return 1
  fi
}

# -----------------------------------------------------------------------------
# Job catalog
# -----------------------------------------------------------------------------
JOBS=(
  frontend
  system-deps
  api-tests
  smoke-contracts
  dependency-governance
  compose-acceptance
  clickhouse-migration
  db-ab
  mcp-e2e
  image-build
  release
)

list_jobs() {
  printf '%s\n' "${JOBS[@]}"
}

# -----------------------------------------------------------------------------
# system-deps — the compiler prerequisites a later stage's pip install needs
# -----------------------------------------------------------------------------
# CPython 3.15 publishes no manylinux wheels for the worker's science stack
# (h5py, cyvcf2, pyarrow, leidenalg, ...), so every `pip install apps/worker[dev]`
# compiles sdists. The worker *image* provides build-essential + libhdf5-dev
# (deploy/docker/Dockerfile.worker); the `api-tests` stage is a bare
# `python:3.15` and provides neither, so real build cnb-8sk-1k6gv3vju-002 failed
# inside the gate that PRs must pass:
#
#   Loading library to get build settings and version: libhdf5.so
#   error: libhdf5.so: cannot open shared object file: No such file or directory
#   ERROR: Failed building wheel for h5py
#
# The step is a no-op where the headers already exist (the GitHub mirror
# installs them through apt as root in its own job; a developer machine usually
# has them), and it never installs anything at run time. Package names are the
# Debian families the Dockerfile pins, so drift shows up as a failing PR rather
# than a mystery wheel-build error.
system_deps_run() {
  if pkg-config --exists hdf5-serial 2>/dev/null; then
    log "HDF5 development files are already present; nothing to install"
    return 0
  fi

  local sudo_prefix=""
  if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_prefix="sudo"
    else
      log "cannot install HDF5 development files: not root and no sudo"
      return 1
    fi
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    log "cannot install HDF5 development files: apt-get is unavailable"
    return 1
  fi

  log "installing build-essential + libhdf5-dev for the CPython ${PYTHON_VERSION} sdist builds"
  ${sudo_prefix} apt-get update
  ${sudo_prefix} env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential libhdf5-dev pkg-config
}

# -----------------------------------------------------------------------------
# frontend — install, build, budgets, unit tests, lint, typecheck, contracts
# -----------------------------------------------------------------------------
frontend_install() {
  # This container has no node_modules and no pnpm shim yet: a previous stage's
  # `corepack enable` died with its container. Bootstrap here rather than
  # assuming state, and let setup-workspace.sh own the registry/store config.
  ensure_workspace
}

# The frontend gate ends with the OpenAPI client contract, which exports the
# backend schema and therefore needs a Python interpreter with the API's
# dependencies. In a fresh CNB container that venv does not exist, and the gate
# died with:
#
#   scripts/check-contract.sh: line 18: /workspace/apps/api/.venv/bin/python:
#   No such file or directory
#   [ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL] @soymutdb/api-client@2.0.0
#   check:contract: `bash scripts/check-contract.sh`
#
# The GitHub mirror escapes this because `actions/setup-python` puts a system
# `python3` on PATH and the workflow prepares the venv by hand; CNB runs the
# gate in `node:26.13.0`, which has no Python at all. Bootstrap the venv exactly
# where check-contract.sh already looks for it, from the same closed dependency
# set the API job installs, so no gate is skipped and the contract is still
# checked on every provider.
SOYMUTDB_CI_VENV_PYTHON="${SOYMUTDB_CI_VENV_PYTHON:-python3}"

# Accept the interpreter only when it is the PINNED major.minor. The image
# provides it today, but `command -v python3` succeeding is not the same claim:
# a rebuilt or re-tagged image could put 3.11 on PATH, the venv would be
# created, and the contract gate would run against a backend the repository
# never declared — the failure mode this whole gate exists to catch.
interpreter_matches_pin() {
  local interpreter="$1"
  "${interpreter}" -c "import sys; sys.exit(
    0 if sys.version_info[:2] == tuple(int(p) for p in '${PYTHON_VERSION}'.split('.')[:2])
    else 1
  )"
}

ensure_api_venv() {
  local venv="${REPO_ROOT}/apps/api/.venv"
  # Idempotent: the backend job may have already created it, and a warm stage
  # should not reinstall. Only the generated venv python is authoritative.
  if [[ -x "${venv}/bin/python" ]]; then
    echo "[ci-job-steps] API virtualenv already present: ${venv}" >&2
    return 0
  fi

  if ! command -v "${SOYMUTDB_CI_VENV_PYTHON}" >/dev/null 2>&1; then
    log "cannot prepare ${venv}: ${SOYMUTDB_CI_VENV_PYTHON} is not on PATH"
    log "the stage image must provide Python ${PYTHON_VERSION} for the OpenAPI contract gate"
    return 1
  fi

  if ! interpreter_matches_pin "${SOYMUTDB_CI_VENV_PYTHON}"; then
    log "cannot prepare ${venv}: ${SOYMUTDB_CI_VENV_PYTHON} is $("${SOYMUTDB_CI_VENV_PYTHON}" -V 2>&1), not ${PYTHON_VERSION}"
    log "the OpenAPI export must run on the pinned interpreter"
    return 1
  fi

  log "creating API virtualenv for the OpenAPI contract gate ($("${SOYMUTDB_CI_VENV_PYTHON}" -V 2>&1))"
  # Mirror api_install through the same shared plan. The contract exports
  # app.main's OpenAPI document, so the API and its local workspace
  # dependencies must be importable; no [dev] extra is installed because the
  # gate imports the app instead of running the test tree.
  "${SOYMUTDB_CI_VENV_PYTHON}" "${REPO_ROOT}/scripts/install_python_workspace.py" \
    --venv "${venv}" \
    --upgrade-pip \
    --expect-version "${PYTHON_VERSION}" \
    apps/api
}

frontend_build_demo() {
  VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}" \
  VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
  VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}" \
    pnpm build
}

frontend_run() {
  frontend_install
  ensure_api_venv
  # Phase C framework-neutral seam guard (plan.md §7): fail before the
  # expensive artifact build if a neutral package (shared/api-client/query-keys)
  # starts importing a UI framework. Stdlib-only, so it runs on the venv
  # interpreter this gate already provisions (the node CI image has no system
  # python). Both CNB and GitHub reach this via the shared job body.
  "${REPO_ROOT}/apps/api/.venv/bin/python" \
    "${REPO_ROOT}/scripts/check_framework_neutral_packages.py"
  bash "${REPO_ROOT}/scripts/verify-frontend-artifacts.sh"
  # Dual-site boundary (AGENTS.md): build the internal variant from the same
  # commit and prove it cannot leak into the external artifact. GitHub runs
  # the same script as its own frontend step; CNB reaches it here. The frontend
  # gate above already built both variants, so this only re-runs the isolation
  # assertions instead of rebuilding them.
  SOYMUTDB_SITE_VARIANTS_PREBUILT=1 \
    bash "${REPO_ROOT}/scripts/verify-site-variant-artifacts.sh"
}

# -----------------------------------------------------------------------------
# api-tests — Python venv, architecture guard, pytest, worker pytest
# -----------------------------------------------------------------------------
# The venv interpreter, not whatever `python` happens to be on PATH. The stage
# image is pinned to PYTHON_VERSION, so accepting a stray interpreter would let
# the suite run against a backend the repository never declared.
api_install() {
  local interpreter="${SOYMUTDB_CI_VENV_PYTHON}"
  local venv="${REPO_ROOT}/apps/api/.venv"

  if ! command -v "${interpreter}" >/dev/null 2>&1; then
    log "cannot build ${venv}: ${interpreter} is not on PATH"
    log "the api-tests stage image must provide Python ${PYTHON_VERSION}"
    return 1
  fi

  if ! interpreter_matches_pin "${interpreter}"; then
    log "cannot build ${venv}: ${interpreter} is $("${interpreter}" -V 2>&1), not ${PYTHON_VERSION}"
    return 1
  fi

  # One shared install plan (shared distributions -> apps/api[dev]) so GitHub,
  # CNB, and local runs cannot drift on the editable-install order. The
  # bootstrap resolves the venv path against the repository root, so this
  # container's cwd cannot move the venv away from where check-contract.sh
  # looks for it.
  "${interpreter}" "${REPO_ROOT}/scripts/install_python_workspace.py" \
    --venv "${venv}" \
    --recreate \
    --upgrade-pip \
    --expect-version "${PYTHON_VERSION}" \
    "apps/api[dev]"
}

# The job name in the catalog is `api-tests`, so the dispatcher resolves
# `api_tests_run`. This function used to be called `api_run`, which meant the
# documented command died before any test ran:
#
#   $ bash scripts/ci-job-steps.sh run api-tests
#   unknown job: api-tests
#
# The contract tests pinned the string `run api-tests`, so they passed while the
# step itself exited 2. Name it after the job.
api_tests_run() {
  api_install
  bash "${REPO_ROOT}/scripts/verify-backend-tests.sh"
}

# -----------------------------------------------------------------------------
# dependency-governance — graphs + fail-closed audits
# -----------------------------------------------------------------------------
# Knip loads the Umi app config to resolve the Vitest project graph, and that
# config validates deployment origins at import time: an unset VITE_API_BASE_URL throws
#
#   Error: API origin is required for production deployment
#     at requireDeploymentOrigin (apps/web/src/lib/deployment.ts:87)
#     at /workspace/apps/web/config/config.ts
#
# before Knip analyses a single file. The gate then dies with a bare Node stack
# trace and `knip: failed (analyzer_exit_nonzero)`, which reads as an unused-code
# finding but is a missing environment variable. The values mirror
# `frontend_build_demo` (and the GitHub mirror's dependency-governance job): the
# demo fixture origins the offline verification build already uses.
dependency_governance_env() {
  export VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}"
  export VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}"
  export VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}"
}

# -----------------------------------------------------------------------------
# smoke-contracts — repo contract suites (the gate that had no CI coverage)
# -----------------------------------------------------------------------------
smoke_contracts_run() {
  # scripts/test_ci_job_contracts.py asserts, among other things, that every
  # shared script is executable and strict. It runs only under
  # `smoke.sh --profile contracts`, and no CI job invoked that profile, so a
  # commit that dropped the exec bit from scripts/smoke.sh or
  # scripts/check-production-artifact.sh passed every pipeline and reached main.
  # This job is the coverage that made that class of regression shippable.
  #
  # The contracts layer is plain pytest under scripts/; it needs no workspace
  # install, no API venv and no service, which is why it can run as its own cheap
  # stage instead of being appended to a heavier job.
  ensure_contracts_python
  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts
}

dependency_governance_step() {
  # `pnpm deps:*` needs an installed workspace, and this is a different container
  # from the frontend job: bootstrap instead of assuming.
  ensure_workspace
  ensure_governance_python
  dependency_governance_env

  # e2e/ is intentionally outside the pnpm workspace, but Knip 5 discovers
  # its Playwright config via package.json and imports it to analyze entrypoints.
  # Without the independent npm lock installation, Knip exits 2 before any
  # code-quality findings can be generated (Cannot find '@playwright/test').
  # Install exactly the locked independent dependencies rather than ignoring
  # the whole workspace or disabling the analysis.
  local rc=0
  npm ci --prefix "${REPO_ROOT}/e2e" --ignore-scripts \
    --registry=https://registry.npmjs.org/ || rc=$?
  # Separate npm package does not belong to root pnpm audit; security-scan it
  # explicitly, with high/critical vulnerabilities remaining a hard failure.
  if [[ "${rc}" -eq 0 ]]; then
    npm audit --prefix "${REPO_ROOT}/e2e" --audit-level=high \
      --registry=https://registry.npmjs.org/ || rc=$?
  fi
  pnpm deps:graphs || rc=$?
  # Always attempt the full audit set so a failed graph does not hide Knip,
  # Deptry, cycle, duplicate, license, or vulnerability evidence.
  UV_CACHE_DIR="${UV_CACHE_DIR:-${TMPDIR:-/tmp}/soymutdb-governance-uv-cache}" \
    pnpm deps:audit || rc=$?
  return "${rc}"
}

dependency_governance_run() {
  dependency_governance_step
}

# -----------------------------------------------------------------------------
# compose-acceptance — production Compose profile validation (Docker required)
# -----------------------------------------------------------------------------
compose_acceptance_run() {
  # `docker compose config` interpolates the WHOLE file before it selects the
  # services a profile enables, so every `${VAR:?}` must resolve even though this
  # gate never starts anything. CI has release credentials, not deployment
  # secrets, so fill validation-only placeholders (an explicitly provided value
  # still wins). Missing them aborted the image build before a single image was
  # built:
  #   error while interpolating x-app-env.SOYMUTDB_REDIS_URL:
  #     required variable REDIS_PASSWORD is missing a value
  # scripts/test_ci_job_contracts.py asserts this list covers every `${VAR:?}`
  # in docker-compose.yml, so a new required variable cannot silently break the
  # image build again.
  local placeholders=(
    "API_IMAGE_REF=soymutdb-validation/api:local"
    "WORKER_IMAGE_REF=soymutdb-validation/worker:local"
    "MIGRATE_IMAGE_REF=soymutdb-validation/migrate:local"
    "MIGRATE_CLICKHOUSE_IMAGE_REF=soymutdb-validation/migrate-clickhouse:local"
    "JBROWSE_IMAGE_REF=soymutdb-validation/jbrowse:local"
    "MCP_IMAGE_REF=soymutdb-validation/mcp-server:local"
    "POSTGRES_PASSWORD=ci-validation"
    "CLICKHOUSE_PASSWORD=ci-validation"
    "REDIS_PASSWORD=ci-validation"
    "MINIO_ROOT_USER=ci-validation"
    "MINIO_ROOT_PASSWORD=ci-validation"
    "GRAFANA_PASSWORD=ci-validation"
    "SOYMUTDB_MCP_API_TOKEN=ci-validation"
  )
  local entry name
  for entry in "${placeholders[@]}"; do
    name="${entry%%=*}"
    if [[ -z "${!name:-}" ]]; then
      export "${entry}"
    fi
  done
  local profile_sets=(
    "core"
    "core,jbrowse"
    "core,blast"
    "core,analyses"
    "core,mcp"
    "core,cloudflare-tunnel"
  )
  local profile_set
  for profile_set in "${profile_sets[@]}"; do
    COMPOSE_PROFILES="${profile_set}" docker compose -f docker-compose.yml config --quiet
  done
}

# -----------------------------------------------------------------------------
# db-ab — W6 harness reproducibility gate (explicitly NOT a performance gate)
#
# The body lives in a checked-in script so CNB and the GitHub mirror execute
# identical bytes; see scripts/verify-db-ab-harness.sh for why the timings this
# produces must never be quoted as a result.
# -----------------------------------------------------------------------------
db_ab_run() {
  api_install
  bash "${REPO_ROOT}/scripts/verify-db-ab-harness.sh"
}

# -----------------------------------------------------------------------------
# clickhouse-migration — real ClickHouse legacy fixture migration + idempotence
# -----------------------------------------------------------------------------
clickhouse_migration_run() {
  local container="soymutdb-ci-clickhouse"
  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker run -d --name "${container}" -p 8123:8123 \
    -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
    -e CLICKHOUSE_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-ci-ch-password}" \
    "${SOYMUTDB_CLICKHOUSE_CI_IMAGE:-clickhouse/clickhouse-server:24.8-alpine}" >/dev/null

  local attempt
  for attempt in $(seq 1 60); do
    if curl --fail --silent \
      -u "default:${SOYMUTDB_CLICKHOUSE_PASSWORD:-ci-ch-password}" \
      http://127.0.0.1:8123/ping >/dev/null; then
      break
    fi
    sleep 2
  done
  curl --fail --silent -u "default:${SOYMUTDB_CLICKHOUSE_PASSWORD:-ci-ch-password}" \
    http://127.0.0.1:8123/ping >/dev/null || {
    docker logs "${container}" >&2 || true
    return 1
  }

  export SOYMUTDB_CLICKHOUSE_HOST=127.0.0.1
  export SOYMUTDB_CLICKHOUSE_PORT=8123
  export SOYMUTDB_CLICKHOUSE_USER=default
  export SOYMUTDB_CLICKHOUSE_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-ci-ch-password}"
  export SOYMUTDB_CLICKHOUSE_DATABASE=soymutdb
  export CLICKHOUSE_MIGRATION_PYTHON="${CLICKHOUSE_MIGRATION_PYTHON:-python}"

  # This job is the CI counterpart of infra/docker/Dockerfile.migrate-clickhouse,
  # and both are pinned to Python 3.14 on purpose while every native service
  # moved to 3.15: clickhouse-connect's newest release (1.10) declares
  # `requires-python >=3.10,<3.15`, so no 3.15 interpreter can install the
  # driver this gate asserts with. Assert the major.minor here instead of
  # trusting the stage image, because the failure that guard prevents is quiet:
  # pip only reports that no matching distribution exists, which reads like a
  # flaky index rather than a runtime that has to be moved back.
  CLICKHOUSE_MIGRATION_PYTHON_VERSION="${SOYMUTDB_CLICKHOUSE_MIGRATION_PYTHON_VERSION:-3.14}"
  if ! "${CLICKHOUSE_MIGRATION_PYTHON}" -c "import sys; sys.exit(
    0 if sys.version_info[:2] == tuple(int(p) for p in '${CLICKHOUSE_MIGRATION_PYTHON_VERSION}'.split('.')[:2])
    else 1
  )"; then
    echo "[ci-job-steps] clickhouse-migration needs Python ${CLICKHOUSE_MIGRATION_PYTHON_VERSION} on CLICKHOUSE_MIGRATION_PYTHON (${CLICKHOUSE_MIGRATION_PYTHON}): clickhouse-connect publishes no 3.15 release." >&2
    echo "[ci-job-steps] Pin the stage image (and infra/docker/Dockerfile.migrate-clickhouse) back to that version, or set SOYMUTDB_CLICKHOUSE_MIGRATION_PYTHON_VERSION once the driver ships 3.15 wheels." >&2
    return 1
  fi

  # The migration script and its assertions import `clickhouse_connect`, but the
  # job image (python:3.14) does not ship it. Provision it in this SHARED body
  # so CNB and GitHub get the same dependency: the GitHub job used to
  # `pip install` it inline while CNB did not, which is exactly how CNB reached
  # "clickhouse-connect is required for ClickHouse migration" while GitHub
  # passed.
  if ! "${CLICKHOUSE_MIGRATION_PYTHON}" -c "import clickhouse_connect" >/dev/null 2>&1; then
    "${CLICKHOUSE_MIGRATION_PYTHON}" -m pip install --quiet --disable-pip-version-check \
      "clickhouse-connect>=0.8.0"
  fi

  bash "${REPO_ROOT}/deploy/scripts/migrate-ch-fixture.sh"
  bash "${REPO_ROOT}/deploy/scripts/migrate-clickhouse.sh"
  python "${REPO_ROOT}/scripts/assert-clickhouse-migration.py"
  bash "${REPO_ROOT}/deploy/scripts/migrate-clickhouse.sh"
  python "${REPO_ROOT}/scripts/assert-clickhouse-migration.py" --idempotent
  # chdb's Python shims stop at 3.14. Preserve the real historical finalize
  # and VCF contracts here, independently of the native Python 3.15 backend.
  bash "${REPO_ROOT}/scripts/verify-legacy-worker-tests.sh"
}

# -----------------------------------------------------------------------------
# mcp-e2e — authenticated transport through the nginx reverse proxy
# -----------------------------------------------------------------------------
mcp_e2e_run() {
  bash "${REPO_ROOT}/scripts/mcp-transport-smoke.sh"
}

# -----------------------------------------------------------------------------
# image-build / release — see scripts/build-release-image.sh and
# scripts/release-contract.golden.sh (single-sourced instead of duplicated here)
# -----------------------------------------------------------------------------
image_build_run() {
  bash "${REPO_ROOT}/scripts/build-release-image.sh"
}

release_run() {
  bash "${REPO_ROOT}/scripts/release-contract.golden.sh"
}

# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------
usage() {
  cat <<'USAGE'
Usage: bash scripts/ci-job-steps.sh <command> [job]

Commands:
  list                     Print the canonical job names, one per line.
  run <job>                Execute a job locally / in CI.

Jobs: see `list`.
USAGE
}

main() {
  local command="${1:-}"
  case "${command}" in
    list) list_jobs ;;
    run)
      local job="${2:-}"
      [[ -n "${job}" ]] || { usage >&2; exit 2; }
      local function_name="${job//-/_}_run"
      declare -F "${function_name}" >/dev/null || {
        echo "unknown job: ${job}" >&2
        exit 2
      }
      log "run ${job}"
      "${function_name}"
      ;;
    -h|--help|"") usage ;;
    *) echo "unknown command: ${command}" >&2; usage >&2; exit 2 ;;
  esac
}

main "$@"

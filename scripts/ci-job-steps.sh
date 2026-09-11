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
NODE_VERSION="${SOYMUTDB_CI_NODE_VERSION:-24.19.0}"
PNPM_VERSION="${SOYMUTDB_CI_PNPM_VERSION:-11.21.0}"
PYTHON_VERSION="${SOYMUTDB_CI_PYTHON_VERSION:-3.14}"
UV_VERSION="${SOYMUTDB_CI_UV_VERSION:-0.11.33}"
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

# -----------------------------------------------------------------------------
# Job catalog
# -----------------------------------------------------------------------------
JOBS=(
  frontend
  api-tests
  dependency-governance
  compose-acceptance
  clickhouse-migration
  mcp-e2e
  image-build
  release
)

list_jobs() {
  printf '%s\n' "${JOBS[@]}"
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

frontend_build_demo() {
  VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}" \
  VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
  VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}" \
    pnpm build
}

frontend_run() {
  frontend_install
  bash "${REPO_ROOT}/scripts/verify-frontend-artifacts.sh"
}

# -----------------------------------------------------------------------------
# api-tests — Python venv, architecture guard, pytest, worker pytest
# -----------------------------------------------------------------------------
api_install() {
  python -m venv apps/api/.venv
  apps/api/.venv/bin/pip install --upgrade pip
  apps/api/.venv/bin/pip install --quiet -e packages/jobs-py
  apps/api/.venv/bin/pip install -e "apps/api[dev]"
}

api_run() {
  api_install
  bash "${REPO_ROOT}/scripts/verify-backend-tests.sh"
}

# -----------------------------------------------------------------------------
# dependency-governance — graphs + fail-closed audits
# -----------------------------------------------------------------------------
dependency_governance_step() {
  # `pnpm deps:*` needs an installed workspace, and this is a different container
  # from the frontend job: bootstrap instead of assuming.
  ensure_workspace

  local rc=0
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
# clickhouse-migration — real ClickHouse legacy fixture migration + idempotence
# -----------------------------------------------------------------------------
clickhouse_migration_run() {
  local container="soymutdb-ci-clickhouse"
  docker rm -f "${container}" >/dev/null 2>&1 || true
  docker run -d --name "${container}" -p 8123:8123 \
    -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
    -e CLICKHOUSE_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-ci-ch-password}" \
    clickhouse/clickhouse-server:24.8-alpine >/dev/null

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

  bash "${REPO_ROOT}/deploy/scripts/migrate-ch-fixture.sh"
  bash "${REPO_ROOT}/deploy/scripts/migrate-clickhouse.sh"
  python "${REPO_ROOT}/scripts/assert-clickhouse-migration.py"
  bash "${REPO_ROOT}/deploy/scripts/migrate-clickhouse.sh"
  python "${REPO_ROOT}/scripts/assert-clickhouse-migration.py" --idempotent
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

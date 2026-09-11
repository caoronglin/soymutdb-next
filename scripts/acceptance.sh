#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — CNB acceptance entry point (环境验收)
# =============================================================================
# One command that answers "is this commit acceptable, and which layer did not
# pass?". It is a thin, honest dispatcher over the layers that already exist:
#
#   contracts  dependency-free delivery/deployment contracts   -> scripts/smoke.sh
#   static     built static tree health + byte checksums       -> scripts/smoke.sh
#   runtime    migrations + real uvicorn + health + search     -> scripts/smoke.sh
#   e2e        browser smoke of the built site                 -> scripts/smoke.sh
#   images     build + runtime smoke + Trivy + SBOM            -> scripts/smoke.sh
#   backend    API + worker pytest with PostgreSQL required    -> verify-backend-tests.sh
#   manifest   compute the acceptance digest and write evidence
#
# Why a separate entry point
#   `scripts/smoke.sh` is a developer tool: it runs whatever is POSSIBLE locally
#   and reports the rest SKIPPED. Acceptance on CNB must be the opposite posture
#   for the layers that are declared required — a required layer whose
#   prerequisite is missing is a FAILURE, not a skip, because on the platform
#   the prerequisite is a property of the pipeline definition and can be fixed
#   there. This script keeps that distinction explicit instead of weakening the
#   smoke entry point (or duplicating it).
#
# Usage
#   bash scripts/acceptance.sh --profile contracts
#   bash scripts/acceptance.sh --profile static --static-dir pages-dist
#   bash scripts/acceptance.sh --profile runtime      # needs SOYMUTDB_DATABASE_URL
#   bash scripts/acceptance.sh --profile full
#   bash scripts/acceptance.sh --list
#
# Profiles
#   contracts  default; no external prerequisites
#   static     needs a built tree (apps/web/dist or --static-dir)
#   runtime    needs SOYMUTDB_DATABASE_URL pointing at a DISPOSABLE PostgreSQL
#   e2e        needs e2e/node_modules + Playwright browsers
#   images     needs a Docker daemon
#   backend    needs apps/api/.venv and a disposable PostgreSQL
#   full       contracts + backend + static + runtime (the "full acceptance")
#
# Environment
#   SOYMUTDB_ACCEPTANCE_DIR      evidence output directory (default artifacts/acceptance)
#   SOYMUTDB_ACCEPTANCE_PYTHON   interpreter for python layers (default python3)
#   SOYMUTDB_ACCEPTANCE_MODE     image-vs-preview classification (default: auto)
#
# Exit codes
#   0  every requested layer passed
#   1  at least one requested layer failed, or a required prerequisite is absent
#   2  usage error
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PROFILE="contracts"
STATIC_DIR=""
PYTHON_BIN="${SOYMUTDB_ACCEPTANCE_PYTHON:-python3}"
EVIDENCE_DIR="${SOYMUTDB_ACCEPTANCE_DIR:-${REPO_ROOT}/artifacts/acceptance}"

usage() {
  sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) [[ $# -ge 2 ]] || { echo "--profile requires a value" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    --static-dir) [[ $# -ge 2 ]] || { echo "--static-dir requires a value" >&2; exit 2; }; STATIC_DIR="$2"; shift 2 ;;
    --list) printf '%s\n' contracts static runtime e2e images backend full; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "${PROFILE}" in
  contracts|static|runtime|e2e|images|backend|full) ;;
  *) echo "unknown profile: ${PROFILE}" >&2; exit 2 ;;
esac

PASSED=()
FAILED=()
BLOCKED=()

log() { printf '[acceptance] %s\n' "$*" >&2; }

run_layer() {
  local name="$1"; shift
  printf '\n\033[1m== acceptance layer: %s\033[0m\n' "${name}"
  if "$@"; then
    PASSED+=("${name}")
  else
    FAILED+=("${name}")
    printf '\033[31mlayer %s FAILED\033[0m\n' "${name}" >&2
  fi
}

# A required layer whose prerequisite is absent is a BLOCKED acceptance, never a
# pass. This is the deliberate difference from scripts/smoke.sh's SKIPPED.
block_layer() {
  local name="$1" reason="$2"
  printf '\n\033[1m== acceptance layer: %s\033[0m\n' "${name}"
  printf '\033[31mBLOCKED: %s\033[0m\n' "${reason}" >&2
  BLOCKED+=("${name} (${reason})")
}

have() { command -v "$1" >/dev/null 2>&1; }

# -----------------------------------------------------------------------------
# Layers that delegate to scripts/smoke.sh
# -----------------------------------------------------------------------------
acceptance_smoke() {
  local profile="$1"
  if [[ -n "${STATIC_DIR}" ]]; then
    bash scripts/smoke.sh --profile "${profile}" --static-dir "${STATIC_DIR}"
  else
    bash scripts/smoke.sh --profile "${profile}"
  fi
}

acceptance_contracts() { acceptance_smoke contracts; }
acceptance_static() { acceptance_smoke static; }
acceptance_runtime() { acceptance_smoke runtime; }
acceptance_e2e() { acceptance_smoke e2e; }
acceptance_images() { acceptance_smoke images; }

acceptance_backend() {
  bash scripts/verify-backend-tests.sh
}

# -----------------------------------------------------------------------------
# Acceptance digest
# -----------------------------------------------------------------------------
# The evidence bundle answers "what exactly was accepted?". The digest is
# computed over the manifest with the digest line excluded, so the value is
# reproducible from the file it describes instead of having to be trusted.
write_digest() {
  mkdir -p "${EVIDENCE_DIR}"
  local manifest="${EVIDENCE_DIR}/acceptance-manifest.txt"
  {
    printf 'repository=%s\n' "${CNB_REPO_SLUG:-unknown}"
    printf 'commit=%s\n' "${CNB_COMMIT:-$(git rev-parse HEAD)}"
    printf 'branch=%s\n' "${CNB_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
    printf 'event=%s\n' "${CNB_EVENT:-local}"
    printf 'build=%s\n' "${CNB_BUILD_ID:-local}"
    printf 'pipeline=%s\n' "${CNB_PIPELINE_KEY:-local}"
    printf 'profile=%s\n' "${PROFILE}"
    printf 'passed=%s\n' "${PASSED[*]:-none}"
    printf 'failed=%s\n' "${FAILED[*]:-none}"
    printf 'blocked=%s\n' "${BLOCKED[*]:-none}"
    # Which package manager produced the artifact, read from the manifest the
    # workspace declares, rather than by probing PATH. Probing would mean this
    # script shells out to a package manager it deliberately never installs:
    # its layers delegate, and the contract that keeps every pnpm entry point
    # bootstrapping its own container is checked statically (see
    # scripts/test_ci_job_contracts.py, test_scripts_that_run_pnpm_bootstrap_*).
    printf 'package_manager=%s\n' "${SOYMUTDB_PACKAGE_MANAGER:-$(node -e 'process.stdout.write(require("./package.json").packageManager)' 2>/dev/null || echo unknown)}"
    printf 'node=%s\n' "$(node --version 2>/dev/null || echo unavailable)"
    printf 'python=%s\n' "$("${PYTHON_BIN}" --version 2>&1 || echo unavailable)"
    if [[ -f apps/web/dist/index.html ]]; then
      printf 'web_artifact_digest=sha256:%s\n' \
        "$(find apps/web/dist -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1)"
    fi
  } >"${manifest}.raw"

  # Digest of the manifest without its own digest line.
  local digest
  digest="$(sha256sum "${manifest}.raw" | cut -d ' ' -f 1)"
  printf 'digest=sha256:%s\n' "${digest}" >"${manifest}"
  cat "${manifest}.raw" >>"${manifest}"
  rm -f "${manifest}.raw"
  log "acceptance manifest: ${manifest}"
}

# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------
if [[ "${PROFILE}" == "full" ]]; then
  run_layer contracts acceptance_contracts

  if [[ -x apps/api/.venv/bin/python && -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
    run_layer backend acceptance_backend
  else
    block_layer backend "requires apps/api/.venv and SOYMUTDB_DATABASE_URL (disposable PostgreSQL)"
  fi

  if [[ -d apps/web/dist || -n "${STATIC_DIR}" ]]; then
    run_layer static acceptance_static
  else
    block_layer static "no built tree at apps/web/dist (build it with the build-pages-artifact job, or the ci:verify script)"
  fi

  if [[ -x apps/api/.venv/bin/python && -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
    run_layer runtime acceptance_runtime
  else
    block_layer runtime "requires apps/api/.venv and SOYMUTDB_DATABASE_URL (disposable PostgreSQL)"
  fi
else
  case "${PROFILE}" in
    contracts)
      run_layer contracts acceptance_contracts
      ;;
    static)
      if [[ -d apps/web/dist || -n "${STATIC_DIR}" ]]; then
        run_layer static acceptance_static
      else
        block_layer static "no built tree at apps/web/dist (build it with the build-pages-artifact job, or the ci:verify script)"
      fi
      ;;
    runtime)
      if [[ -x apps/api/.venv/bin/python && -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
        run_layer runtime acceptance_runtime
      else
        block_layer runtime "requires apps/api/.venv and SOYMUTDB_DATABASE_URL (disposable PostgreSQL)"
      fi
      ;;
    e2e)
      if [[ -d e2e/node_modules ]]; then
        run_layer e2e acceptance_e2e
      else
        block_layer e2e "requires 'npm ci' inside e2e/ and Playwright browsers"
      fi
      ;;
    images)
      if have docker && docker info >/dev/null 2>&1; then
        run_layer images acceptance_images
      else
        block_layer images "requires a reachable Docker daemon"
      fi
      ;;
    backend)
      if [[ -x apps/api/.venv/bin/python ]]; then
        run_layer backend acceptance_backend
      else
        block_layer backend "requires apps/api/.venv (pip install -e 'apps/api[dev]')"
      fi
      ;;
  esac
fi

write_digest

printf '\n\033[1m== acceptance summary\033[0m\n'
printf 'profile: %s\n' "${PROFILE}"
printf 'passed:  %d%s\n' "${#PASSED[@]}" "${PASSED:+ [${PASSED[*]}]}"
printf 'failed:  %d%s\n' "${#FAILED[@]}" "${FAILED:+ [${FAILED[*]}]}"
printf 'blocked: %d%s\n' "${#BLOCKED[@]}" "${BLOCKED:+ [${BLOCKED[*]}]}"

if [[ "${#FAILED[@]}" -gt 0 || "${#BLOCKED[@]}" -gt 0 ]]; then
  printf '\n\033[31mACCEPTANCE FAIL\033[0m\n' >&2
  exit 1
fi

printf '\n\033[32mACCEPTANCE PASS\033[0m\n'

#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — workspace bootstrap shared by every CNB stage
# =============================================================================
# This script exists because of a real platform failure, not for tidiness.
#
# A CNB stage script is executed with `sh`, which on Debian/Ubuntu is dash. dash
# rejects both `set -o pipefail` and `set -u`-style bashisms used elsewhere, and
# `set -euo pipefail` therefore aborts the stage immediately:
#
#   sh: 1: set: Illegal option -o pipefail      (exit 2)
#
# Keeping the bootstrap in a checked-in script with a bash shebang means:
#   * the shell is chosen by the shebang, never by the platform default;
#   * `scripts/test_ci_job_contracts.py` can lint the shell of every config
#     script block, instead of the failure only showing up on a real build;
#   * both providers (CNB stage blocks, GitHub steps) call one implementation.
#
# Idempotent: safe to run in every stage of every job.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PNPM_VERSION="${SOYMUTDB_CI_PNPM_VERSION:-11.21.0}"
PNPM_STORE_DIR="${SOYMUTDB_CI_PNPM_STORE_DIR:-/cache/pnpm-store}"
# The repo .npmrc pins a mirror; CI must use the registry the lockfile was
# resolved against.
NPM_REGISTRY="${SOYMUTDB_CI_NPM_REGISTRY:-https://registry.npmjs.org/}"

log() { printf '[setup-workspace] %s\n' "$*" >&2; }

# A missing volume mount would silently de-cache the build: the store would land
# in the container layer and be discarded with it.
if ! mkdir -p "${PNPM_STORE_DIR}" 2>/dev/null; then
  log "cannot create ${PNPM_STORE_DIR}; falling back to the default store"
  PNPM_STORE_DIR=""
fi

corepack enable
corepack prepare "pnpm@${PNPM_VERSION}" --activate

if [[ -n "${PNPM_STORE_DIR}" ]]; then
  pnpm config set store-dir "${PNPM_STORE_DIR}"
else
  log "pnpm store cache is NOT persistent for this job"
fi
pnpm config set registry "${NPM_REGISTRY}"

log "node $(node --version) / pnpm $(pnpm --version)"
pnpm install --frozen-lockfile

log "workspace ready"

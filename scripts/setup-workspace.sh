#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — workspace bootstrap, run at the start of EVERY stage that needs it
# =============================================================================
# Why a script
#   A CNB stage `script` is executed with `sh`; on the platform base images that
#   is dash, which rejects `set -o pipefail` at run time:
#
#     sh: 1: set: Illegal option -o pipefail      (exit 2)
#
#   `sh -n` accepts that body, and so does the CNB validator, so the only place
#   the failure appears is a real build. Putting the bootstrap behind a bash
#   shebang makes the interpreter explicit, and lets
#   scripts/test_ci_job_contracts.py statically lint every stage body.
#
# Why it runs in every stage (this is the important part)
#   Each CNB stage runs in its OWN fresh container. Two consequences that are
#   easy to get wrong:
#
#     * `corepack enable` in a "Setup workspace" stage does NOT make `pnpm`
#       available to the next stage. It writes a shim into the container's
#       filesystem, which is discarded when that stage's container exits:
#
#         bash scripts/ci-job-steps.sh run frontend
#         scripts/ci-job-steps.sh: line 89: pnpm: command not found   (exit 127)
#
#     * The checkout does not carry the install either. Only the paths
#       declared as pipeline `docker.volumes` survive between containers (here:
#       the pnpm store; turbo's cache rides along inside the always-shared
#       /workspace), so `node_modules` must be materialised per stage.
#
#   `pnpm install --frozen-lockfile` is therefore idempotent and cheap when the
#   store volume is warm: it links from the store rather than re-downloading.
#   Every npm-dependent stage calls this script, and no stage relies on state
#   left behind by another.
#
# Usage
#   bash scripts/setup-workspace.sh          # enable pnpm + install workspace
#   bash scripts/setup-workspace.sh --enable-only
#                                            # only make pnpm available
#
# Environment
#   SOYMUTDB_CI_PNPM_VERSION     pnpm version to activate (default from below)
#   SOYMUTDB_CI_PNPM_STORE_DIR   persistent store path (default /cache/pnpm-store)
#   SOYMUTDB_CI_NPM_REGISTRY     registry to install from
#   SOYMUTDB_CI_SKIP_INSTALL     1 to enable pnpm without installing
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PNPM_VERSION="${SOYMUTDB_CI_PNPM_VERSION:-11.21.0}"
PNPM_STORE_DIR="${SOYMUTDB_CI_PNPM_STORE_DIR:-/cache/pnpm-store}"
# The repo .npmrc pins a mirror; CI must use the registry the lockfile was
# resolved against.
NPM_REGISTRY="${SOYMUTDB_CI_NPM_REGISTRY:-https://registry.npmjs.org/}"

ENABLE_ONLY=0
for argument in "$@"; do
  case "${argument}" in
    --enable-only) ENABLE_ONLY=1 ;;
    *) echo "unknown argument: ${argument}" >&2; exit 2 ;;
  esac
done
if [[ "${SOYMUTDB_CI_SKIP_INSTALL:-0}" == "1" ]]; then
  ENABLE_ONLY=1
fi

log() { printf '[setup-workspace] %s\n' "$*" >&2; }

# -----------------------------------------------------------------------------
# 1. Make pnpm available in THIS container
# -----------------------------------------------------------------------------
# corepack ships the package manager shim; the version is pinned so a stage can
# never resolve a different pnpm than package.json declares.
corepack enable
corepack prepare "pnpm@${PNPM_VERSION}" --activate

# Verify rather than assume. The failure mode this replaces was a bare
# `pnpm: command not found` three stages later, which reads as a script bug
# instead of a container-lifecycle bug.
command -v pnpm >/dev/null 2>&1 || {
  log "corepack did not put pnpm on PATH; the stage cannot build"
  exit 1
}

# -----------------------------------------------------------------------------
# 2. Point pnpm at the persistent store
# -----------------------------------------------------------------------------
# A missing volume mount would silently de-cache the build: the store would land
# in the container layer and be discarded when the stage exits.
if mkdir -p "${PNPM_STORE_DIR}" 2>/dev/null; then
  pnpm config set store-dir "${PNPM_STORE_DIR}"
else
  log "cannot create ${PNPM_STORE_DIR}; falling back to the default store"
  log "pnpm store cache is NOT persistent for this job"
fi
pnpm config set registry "${NPM_REGISTRY}"

log "node $(node --version) / pnpm $(pnpm --version)"

# -----------------------------------------------------------------------------
# 3. Materialise node_modules for this container
# -----------------------------------------------------------------------------
if [[ "${ENABLE_ONLY}" == "1" ]]; then
  log "pnpm enabled (install skipped)"
  exit 0
fi

# Idempotent and store-linked: a cold container with a warm store is a link pass,
# not a download pass.
pnpm install --frozen-lockfile

log "workspace ready"

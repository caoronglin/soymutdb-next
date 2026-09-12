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

# The logger is defined before the first `log` call site, not after it: step 0
# runs before the function used to be declared, so an unset `log` aborted every
# stage with `line 122: log: command not found` (exit 127).
log() { printf '[setup-workspace] %s\n' "$*" >&2; }

# -----------------------------------------------------------------------------
# 0. Make sure the Compose interpolation variables exist
# -----------------------------------------------------------------------------
# `docker compose` interpolates each file BEFORE it merges them, so a single
# required variable can abort every compose invocation -- even one that only
# names `postgres`. `docker-compose.yml` is the production topology and is
# deliberately fail-fast, which is how the cloud-development preview died:
#
#   [start-cloud-dev] starting the data layer (postgres clickhouse redis minio)
#   error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
#     required variable MINIO_ROOT_USER is missing a value:
#     MINIO_ROOT_USER is required                            (compose exit 1)
#   Pipeline prepare error: Preview launch script execution failed
#
# The FIX for that is in `docker-compose.dev.yml`, not here: the overlay
# satisfies every reference the four data-layer services need, via
# `x-app-env: !reset` and the redis healthcheck override. See
# `docs/ops/cnb-startup-acceptance.md` §2.2.2 and
# `scripts/test_development_compose_contract.py`.
#
# The defaults below are for the OTHER callers of this workspace, and for the
# operator who starts services by hand from the same shell afterwards. They are
# a convenience, not the fix, and the distinction matters:
#
#   `start-cloud-dev.sh` runs this script as a CHILD PROCESS
#   (`bash scripts/setup-workspace.sh`), so an `export` here never reaches the
#   data-layer `docker compose` call in the parent. A preview that relied on
#   these exports would still fail exactly as the log above shows -- which is
#   why the contract test asserts on the overlay rather than on this block.
#
# Rules:
#   * only set when unset, so a caller-provided value -- the GitHub mirror
#     passes ci-compose-* secrets, an operator passes real ones -- stays
#     authoritative;
#   * these are loopback-only development credentials, and the production
#     topology never loads this overlay, so defaulting them cannot reach a
#     release.
#
# `start-cloud-dev.sh` applies the same defaults inside the process that runs
# `docker compose`, and adds `--env-file /dev/null` so a leftover `.env` cannot
# change the data layer behind the operator's back.
if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  : "${POSTGRES_PASSWORD:=soymutdb_dev_password}"
  : "${CLICKHOUSE_PASSWORD:=soymutdb_dev_password}"
  : "${REDIS_PASSWORD:=soymutdb_dev_password}"
  : "${MINIO_ROOT_USER:=soymutdb_dev}"
  : "${MINIO_ROOT_PASSWORD:=soymutdb_dev_password}"
  export POSTGRES_PASSWORD CLICKHOUSE_PASSWORD REDIS_PASSWORD
  export MINIO_ROOT_USER MINIO_ROOT_PASSWORD
  log "compose interpolation variables defaulted for the development data layer"
fi

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

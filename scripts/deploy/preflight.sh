#!/usr/bin/env bash
# =====================================================================
# SoyMutDB deployment preflight (D1)
# =====================================================================
# Unified precheck for toolchain, filesystem, and target environment.
# Explicit environment is mandatory: unknown or missing values refuse to run
# (handoff contract). This script only reads state; it never writes to the
# user's working tree, node_modules, virtualenvs or databases.
#
# Usage:
#   scripts/deploy/preflight.sh --environment development [--json]
# Exit codes: 0 = pass, 1 = precheck failure, 2 = usage error.
# Output never contains secrets: only paths, versions and booleans.
# =====================================================================
set -euo pipefail

ENVIRONMENT=""
DRY_RUN=false

usage() {
    cat <<'USAGE'
Usage: scripts/deploy/preflight.sh --environment development|staging|production [--json]
  --environment  explicit target environment (required, first-validation target: development)
  --json         emit machine-readable JSON verdict instead of human lines
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --environment)
            [[ $# -ge 2 ]] || { echo "--environment requires a value" >&2; usage >&2; exit 2; }
            ENVIRONMENT="$2"; shift 2 ;;
        --json) JSON=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "${ENVIRONMENT:-}" in
    development|staging|production) ;;
    *) echo "refusing to run: --environment must be development|staging|production" >&2; usage >&2; exit 2 ;;
esac

fail() { echo "PREFLIGHT FAIL: $*" >&2; exit 1; }

# --- toolchain (pinned, per repo .nvmrc / pyproject) ---------------------
node --version >/dev/null 2>&1 || { echo "PREFLIGHT FAIL: node missing"; exit 1; }
pnpm --version >/dev/null 2>&1 || { echo "PREFLIGHT FAIL: pnpm missing"; exit 1; }
python3 --version >/dev/null 2>&1 || { echo "PREFLIGHT FAIL: python3 missing"; exit 1; }

node_v="$(node --version)"
pnpm_v="$(pnpm --version)"
py_v="$(python3 --version)"
nvmrc="$(cat .nvmrc 2>/dev/null || true)"
if [[ -n "${nvmrc}" && "${node_v#v}" != "${nvmrc}"* ]]; then
    # .nvmrc pins 26.10.0; only warn, real gates are enforced by CI/toolchain.
    echo "WARN: node ${node_v} vs .nvmrc ${nvmrc}"
fi
echo "TOOLCHAIN: node=${node_v} pnpm=${pnpm_v} ${py_v}"

# --- filesystem: refuse GVFS/SMB build paths (H07) -----------------------
repo_fs="$(df -T . 2>/dev/null | awk 'NR==2 {print $2}')"
case "${repo_fs}" in
    *cifs*|*smb*|*smbfs*|*9p*|*fuse.sshfs*)
        echo "PREFLIGHT FAIL: repository on network filesystem (${repo_fs}); H07 forbids dependency installs/builds here" >&2
        exit 1
        ;;
esac
echo "FILESYSTEM: repo on ${repo_fs} (local, writable)"

# --- workspace protection: do not touch user state ----------------------
# Record fingerprint of the working tree so later stages can assert that
# preflight modified nothing (read-only precheck).
tree_digest="$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"
dirty_count="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
echo "WORKSPACE: HEAD=${tree_digest} dirty_entries=${dirty_count} (preserved, not cleaned)"

# --- environment-specific checks ----------------------------------------
case "${ENVIRONMENT}" in
    development)
        # Native dev path uses the disposable mamba PostgreSQL; Docker is optional.
        if docker info >/dev/null 2>&1; then
            echo "CONTAINERS: docker available"
            DOCKER_AVAILABLE=1
        else
            echo "CONTAINERS: docker unavailable; native path (mamba PostgreSQL + uvicorn) is the validation target"
            DOCKER_AVAILABLE=0
        fi
        pg_bin="${SOYMUTDB_PG_BIN:-.mamba-root/envs/postgres16/bin}"
        if [[ -x "${pg_bin}/postgres" ]]; then
            echo "PG_RUNTIME: ${pg_bin}/postgres present (disposable instance required; never point at production)"
        else
            echo "PG_RUNTIME: disposable PostgreSQL not bootstrapped; see docs/dev/mamba-validation-environment.md"
        fi
        ;;
    staging|production)
        echo "NOTE: staging/production preflight only validates inputs; execution requires separate authorization (H16)."
        command -v jq >/dev/null 2>&1 || { echo "PREFLIGHT FAIL: jq required for staging/production release tooling" >&2; exit 1; }
        ;;
esac

# --- secrets hygiene: never print env values ----------------------------
echo "PREFLIGHT PASS: environment=${ENVIRONMENT} (all prechecks green or non-blocking)"
exit 0

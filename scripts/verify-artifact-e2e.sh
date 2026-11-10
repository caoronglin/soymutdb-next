#!/usr/bin/env bash
# =============================================================================
# Run every OFFLINE browser-artifact gate in one pass.
# =============================================================================
# The repository has many Playwright configs but only two were CI-wired, and
# the unwired ones rotted silently (admin-production asserted English copy for a
# Chinese-first console; entity-detail pointed at a dist root that no longer
# exists; primer served an artifact with no index.html). This script is the
# single entry point for the offline gates so a full sweep is one command and a
# new gate cannot be added without appearing in the inventory list below.
#
# It assumes the artifacts are already built (CI builds them first):
#   pnpm --filter @soymutdb/web build:sites && pnpm --filter @soymutdb/admin build
#   pnpm --filter @soymutdb/jbrowse build
#
# Usage:
#   bash scripts/verify-artifact-e2e.sh                 # every gate, sequential
#   bash scripts/verify-artifact-e2e.sh --build         # build artifacts first
#   bash scripts/verify-artifact-e2e.sh public visual   # subset
#   ARTIFACT_E2E_LOG_DIR=.cache/artifact-e2e bash scripts/verify-artifact-e2e.sh
#
# Environment:
#   PLAYWRIGHT_BROWSERS_PATH  browser cache (default $HOME/.cache/ms-playwright)
#   ARTIFACT_E2E_LOG_DIR      per-gate logs (default .cache/artifact-e2e)
#   ARTIFACT_E2E_RETRIES      Playwright --retries (default 0; set 1 on a
#                             memory-constrained host where Chromium's context
#                             launch occasionally dies — assertion failures still
#                             fail after the retry)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
export PLAYWRIGHT_BROWSERS_PATH
LOG_DIR="${ARTIFACT_E2E_LOG_DIR:-.cache/artifact-e2e}"
mkdir -p "${LOG_DIR}"

PLAYWRIGHT="${REPO_ROOT}/e2e/node_modules/.bin/playwright"
if [[ ! -x "${PLAYWRIGHT}" ]]; then
  echo "error: ${PLAYWRIGHT} is missing; run 'pnpm install' in e2e/" >&2
  exit 2
fi
if [[ ! -d "${PLAYWRIGHT_BROWSERS_PATH}" ]]; then
  echo "error: no Playwright browsers at ${PLAYWRIGHT_BROWSERS_PATH}" >&2
  echo "       run: cd e2e && ./node_modules/.bin/playwright install chromium" >&2
  exit 2
fi

# Every config below serves a built artifact and needs no deployment. Add a new
# offline gate here so the sweep and its documentation cannot drift apart.
build_first=0
if [[ "${1:-}" == "--build" ]]; then
  build_first=1
  shift
fi

# `subpath-artifact` serves the gh-pages-shaped tree from `build-pages-artifact.sh`
# (mounted under /soymutdb-next) instead of the base-`/` trees the other gates
# use. It runs last because producing that tree rebuilds apps/web/dist with a
# different base; see the prerequisite note where it is skipped.
GATES=(public internal admin-production admin-shell entity-detail visual web-performance primer jbrowse-artifact subpath-artifact)

if (($# > 0)); then
  GATES=("$@")
fi

if ((build_first)); then
  bash "${REPO_ROOT}/scripts/build-all-static-apps.sh"
fi

missing_artifact=0
require_artifact() {
  if [[ ! -f "$1" ]]; then
    echo "error: missing artifact $1 (build it before running this gate set)" >&2
    missing_artifact=1
  fi
}
require_artifact "apps/web/dist/external/index.html"
require_artifact "apps/web/dist/internal/index.html"
require_artifact "apps/admin/dist/index.html"
require_artifact "apps/jbrowse/dist/index.html"
if ((missing_artifact)); then
  exit 2
fi

# The sub-path gate needs `scripts/build-pages-artifact.sh` to have run: that
# script rebuilds `apps/web/dist` with the mount prefix, so it cannot be folded
# into the sweep without clobbering the artifacts the nine root-base gates just
# used. A missing tree is reported SKIPPED with the reason (never counted as a
# pass), and the gate is excluded from the run.
subpath_ready=0
if [[ -f "pages-dist/index.html" ]]; then
  subpath_ready=1
fi

declare -a RESULTS=()
declare -a FAILED=()
declare -a RETRIES=()
if [[ -n "${ARTIFACT_E2E_RETRIES:-}" ]]; then
  RETRIES=(--retries "${ARTIFACT_E2E_RETRIES}")
fi
started_at=$(date +%s)

for gate in "${GATES[@]}"; do
  config="playwright-${gate}.config.ts"
  if [[ ! -f "e2e/${config}" ]]; then
    echo "error: unknown gate '${gate}' (e2e/${config} does not exist)" >&2
    exit 2
  fi
  if [[ "${gate}" == "subpath-artifact" && "${subpath_ready}" -eq 0 ]]; then
    echo "==> [${gate}] SKIPPED: pages-dist/ is absent" >&2
    echo "    run: bash scripts/build-pages-artifact.sh   (rebuilds apps/web/dist with the mount prefix)" >&2
    RESULTS+=("$(printf '%-16s SKIPPED    → pages-dist/ absent; run scripts/build-pages-artifact.sh' "${gate}")")
    continue
  fi
  log="${LOG_DIR}/${gate}.log"
  echo "==> [${gate}] ${log}"
  gate_started=$(date +%s)
  # The sub-path gate mounts the artifact under /soymutdb-next, so its specs must
  # compose URLs with that prefix: `E2E_BASE_PATH` is what `helpers.ts` reads to
  # build `${BASE}` and to make `gotoReady` prefix-aware. Without it the specs
  # navigate to the origin root, the prefixed server 404s, and the gate fails for
  # a reason that has nothing to do with the artifact.
  gate_env=()
  if [[ "${gate}" == "subpath-artifact" ]]; then
    gate_env=(env E2E_BASE_PATH=/soymutdb-next)
  fi
  if (cd e2e && "${gate_env[@]}" "${PLAYWRIGHT}" test -c "${config}" "${RETRIES[@]}" >"../${log}" 2>&1); then
    status="pass"
    RESULTS+=("$(printf '%-16s pass %4ss' "${gate}" "$(( $(date +%s) - gate_started ))")")
  else
    status="FAIL"
    FAILED+=("${gate}")
    RESULTS+=("$(printf '%-16s FAIL %4ss  → %s' "${gate}" "$(( $(date +%s) - gate_started ))" "${log}")")
    echo "--- ${gate} failed; last lines of ${log} ---" >&2
    tail -n 25 "${log}" >&2
  fi
done

echo
echo "artifact E2E summary (${#GATES[@]} gates, $(( $(date +%s) - started_at ))s):"
for line in "${RESULTS[@]}"; do
  echo "  ${line}"
done

if ((${#FAILED[@]} > 0)); then
  echo
  echo "artifact E2E FAILED: ${FAILED[*]}" >&2
  exit 1
fi
echo
echo "artifact E2E passed"

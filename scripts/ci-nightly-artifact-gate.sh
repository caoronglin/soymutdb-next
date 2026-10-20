#!/usr/bin/env bash
# =============================================================================
# CI entry point: build the static artifacts and run every offline browser gate.
# =============================================================================
# Both providers call this one script from their nightly/PR lane, so the two
# pipelines execute identical bytes (`.cnb.yml` is authoritative; the GitHub
# workflow mirrors it). It owns the workspace install because each CNB stage is
# a fresh container.
#
# Prerequisites: node + npm on PATH. This script installs the independent e2e
# package and Chromium itself: CNB stages are fresh containers, so nothing
# installed by an earlier stage (browser binaries, --with-deps system libraries,
# node_modules outside /workspace) survives into this one.
#
# Usage: bash scripts/ci-nightly-artifact-gate.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "==> e2e browser suite install (independent npm package)"
(
  cd e2e
  npm ci
  ./node_modules/.bin/playwright install --with-deps chromium
)

echo "==> workspace bootstrap (pnpm + frozen-lockfile install)"
bash scripts/setup-workspace.sh

echo "==> build static artifacts"
bash scripts/build-all-static-apps.sh

# One retry absorbs the runner's occasional Chromium context-launch failure;
# assertion failures still fail after the retry.
echo "==> offline artifact browser gates"
ARTIFACT_E2E_RETRIES="${ARTIFACT_E2E_RETRIES:-1}" bash scripts/verify-artifact-e2e.sh

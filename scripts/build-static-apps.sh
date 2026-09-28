#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — build the React portal and admin static applications
# =============================================================================
# Shared by the baseline validation job and by any caller that needs the two
# static bundles without the full verification gate set (i18n, budgets,
# contracts) owned by scripts/verify-frontend-artifacts.sh.
#
# The offline demo fixture is used deliberately: a generic build must never
# require a live release API. The strict production build path
# (VITE_DEPLOYMENT_MODE=production) is documented in docs/ops/production-build.md
# and gated by scripts/check-production-artifact.sh without --allow-demo.
#
# Usage: bash scripts/build-static-apps.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

export VITE_DEPLOYMENT_MODE="${VITE_DEPLOYMENT_MODE:-demo}"
export VITE_BASE_URL="${VITE_BASE_URL:-/}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-https://api.soymutdb.test}"
export VITE_JBROWSE_BASE_URL="${VITE_JBROWSE_BASE_URL:-https://jbrowse.soymutdb.test}"

# This script stands in for the container build path (it produces the tree the
# Dockerfile.web/admin stages consume), so it opts into .gz siblings for nginx
# gzip_static. The published Pages/gh-pages path is scripts/build-sites.ts,
# which leaves this unset.
export SOYMUTDB_EMIT_GZ="${SOYMUTDB_EMIT_GZ:-1}"

pnpm build:web
pnpm build:admin

test -s apps/web/dist/external/index.html
test -s apps/web/dist/internal/index.html
test -s apps/admin/dist/index.html
printf 'static applications built (web, admin)\n'

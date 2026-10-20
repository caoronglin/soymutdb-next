#!/usr/bin/env bash
# =============================================================================
# Build every static application artifact the offline browser gates consume.
# =============================================================================
# The artifact-E2E sweep (scripts/verify-artifact-e2e.sh) needs FOUR built trees:
#   apps/web/dist/{external,internal}/index.html
#   apps/admin/dist/index.html
#   apps/jbrowse/dist/index.html
# `scripts/build-static-apps.sh` builds the first three; the genome browser is a
# separate build. Both providers call THIS script so the two never drift, and
# the browser gates never run against a half-built tree.
#
# Demo deployment mode is deliberate: a generic build must never require a live
# release API. The strict production build path is documented in
# docs/ops/production-build.md.
#
# Usage: bash scripts/build-all-static-apps.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

export VITE_DEPLOYMENT_MODE="${VITE_DEPLOYMENT_MODE:-demo}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-https://api.soymutdb.test}"
export VITE_JBROWSE_BASE_URL="${VITE_JBROWSE_BASE_URL:-https://jbrowse.soymutdb.test}"
export SOYMUTDB_PORTAL_ORIGIN="${SOYMUTDB_PORTAL_ORIGIN:-https://portal.soymutdb.test}"
export SOYMUTDB_ADMIN_ORIGIN="${SOYMUTDB_ADMIN_ORIGIN:-https://admin.soymutdb.test}"
export SOYMUTDB_SITE_URL="${SOYMUTDB_SITE_URL:-https://api.soymutdb.test}"

echo "==> portal (external + internal) and admin artifact"
bash scripts/build-static-apps.sh

echo "==> genome browser artifact"
pnpm --filter @soymutdb/jbrowse build

for artifact in \
  apps/web/dist/external/index.html \
  apps/web/dist/internal/index.html \
  apps/admin/dist/index.html \
  apps/jbrowse/dist/index.html; do
  if [[ ! -s "${artifact}" ]]; then
    echo "error: ${artifact} was not produced" >&2
    exit 1
  fi
done
echo "all static artifacts built (web external/internal, admin, jbrowse)"

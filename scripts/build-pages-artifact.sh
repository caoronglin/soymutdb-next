#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — build the checksummed static Pages artifact
# =============================================================================
# Produces `pages-dist/` from source in one place so the CNB verify pipeline and
# the GitHub mirror workflow cannot produce different bytes for the same commit.
#
# Layout (matches the published site):
#   pages-dist/                    <- apps/web/dist
#   pages-dist/soymutdb-jbrowse/   <- apps/jbrowse/dist
#   pages-dist/404.html            <- copy of index.html for SPA fallbacks
#   pages-dist/.nojekyll           <- required to keep underscore paths
#   pages-dist/SHA256SUMS          <- self-verifying manifest
#
# Publication must consume these exact bytes; it must never rebuild.
#
# Usage: bash scripts/build-pages-artifact.sh
# Env:   PAGES_BASE_PATH   deployment base path (default /$SOYMUTDB_SITE_SLUG/)
#        SOYMUTDB_SITE_SLUG  repository/deployment slug (default soymutdb)
#        PAGES_OUTPUT_DIR  output directory (default pages-dist)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SOYMUTDB_SITE_SLUG="${SOYMUTDB_SITE_SLUG:-soymutdb}"
PAGES_BASE_PATH="${PAGES_BASE_PATH:-/${SOYMUTDB_SITE_SLUG}/}"
PAGES_OUTPUT_DIR="${PAGES_OUTPUT_DIR:-pages-dist}"
SITE_ORIGIN="${SOYMUTDB_SITE_ORIGIN:-https://${SOYMUTDB_SITE_SLUG}.github.io}"

export VITE_DEPLOYMENT_MODE=demo
export VITE_BASE_URL="${PAGES_BASE_PATH}"
export VITE_API_BASE_URL="${SOYMUTDB_SITE_API_URL:-${SITE_ORIGIN}${PAGES_BASE_PATH}api/v1}"
export VITE_CDN_ENABLED=false
export VITE_JBROWSE_BASE_URL="${SOYMUTDB_SITE_JBROWSE_URL:-${SITE_ORIGIN}${PAGES_BASE_PATH}soymutdb-jbrowse/}"
export VITE_JBROWSE_URL="${VITE_JBROWSE_BASE_URL}"
export SOYMUTDB_SITE_URL="${SITE_ORIGIN}"

echo "1) build web application"
pnpm --filter @soymutdb/web build

echo "2) build JBrowse application"
VITE_BASE_URL="${PAGES_BASE_PATH}soymutdb-jbrowse/" \
  VITE_JBROWSE_DATA_URL="${PAGES_BASE_PATH}jbrowse-data" \
  pnpm --filter @soymutdb/jbrowse build

echo "3) assemble ${PAGES_OUTPUT_DIR}"
rm -rf "${PAGES_OUTPUT_DIR}"
mkdir -p "${PAGES_OUTPUT_DIR}/soymutdb-jbrowse"
cp -r apps/web/dist/. "${PAGES_OUTPUT_DIR}/"
cp -r apps/jbrowse/dist/. "${PAGES_OUTPUT_DIR}/soymutdb-jbrowse/"
cp "${PAGES_OUTPUT_DIR}/index.html" "${PAGES_OUTPUT_DIR}/404.html"
touch "${PAGES_OUTPUT_DIR}/.nojekyll"

# Hidden files are part of the published tree (.nojekyll), so the manifest must
# cover them and the verifier must accept hidden inputs.
(
  cd "${PAGES_OUTPUT_DIR}"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
test -f "${PAGES_OUTPUT_DIR}/SHA256SUMS"

echo "pages artifact ready at ${PAGES_OUTPUT_DIR}"

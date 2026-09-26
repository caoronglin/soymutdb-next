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

# This script runs `pnpm --filter ... build`, and CI gives it a fresh container
# with no node_modules and no pnpm shim. Bootstrap here rather than depending on
# a sibling stage: see scripts/ci-job-steps.sh, "container lifecycle".
bash "${REPO_ROOT}/scripts/setup-workspace.sh"

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

# A core-only deployment may publish without the JBrowse sub-app. Normalize the
# flag once so the portal build (which hides JBrowse UI) and the artifact layout
# (which may omit the sub-app) can never disagree.
JBROWSE_ENABLED="${SOYMUTDB_JBROWSE_ENABLED:-1}"
case "${JBROWSE_ENABLED}" in
  0|[Ff]alse|[Oo]ff|[Nn]o) JBROWSE_ENABLED=0 ;;
  *) JBROWSE_ENABLED=1 ;;
esac
export VITE_JBROWSE_ENABLED="${JBROWSE_ENABLED}"

echo "1) build web application"
pnpm --filter @soymutdb/web build

if [[ "${JBROWSE_ENABLED}" == "1" ]]; then
  echo "2) build JBrowse application"
  # The JBrowse `_headers` injector needs the API origin, the data origin, and the
  # portal/admin origins that are allowed to embed the app. Without them the
  # rewritten CSP would be same-origin only and every API call and embed on the
  # published site would be blocked by the app's own policy.
  VITE_BASE_URL="${PAGES_BASE_PATH}soymutdb-jbrowse/" \
    VITE_JBROWSE_DATA_URL="${PAGES_BASE_PATH}jbrowse-data" \
    SOYMUTDB_PORTAL_ORIGIN="${SOYMUTDB_PORTAL_ORIGIN:-${SITE_ORIGIN}}" \
    SOYMUTDB_ADMIN_ORIGIN="${SOYMUTDB_ADMIN_ORIGIN:-${SITE_ORIGIN}${PAGES_BASE_PATH}admin/}" \
    pnpm --filter @soymutdb/jbrowse build
else
  echo "2) skipping JBrowse (SOYMUTDB_JBROWSE_ENABLED=0): core-only artifact"
fi

echo "3) assemble ${PAGES_OUTPUT_DIR}"
rm -rf "${PAGES_OUTPUT_DIR}"
mkdir -p "${PAGES_OUTPUT_DIR}"
cp -r apps/web/dist/. "${PAGES_OUTPUT_DIR}/"
if [[ "${JBROWSE_ENABLED}" == "1" ]]; then
  mkdir -p "${PAGES_OUTPUT_DIR}/soymutdb-jbrowse"
  cp -r apps/jbrowse/dist/. "${PAGES_OUTPUT_DIR}/soymutdb-jbrowse/"
else
  # An explicit marker distinguishes a deliberate core-only tree from a broken
  # one; hidden files are covered by SHA256SUMS.
  : > "${PAGES_OUTPUT_DIR}/.no-jbrowse"
fi
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

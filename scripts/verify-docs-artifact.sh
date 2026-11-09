#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — verify the dumi component-docs artifact
# =============================================================================
# apps/docs is developer documentation, not a site variant. It must build, and
# the emitted tree must stay free of portal origins and internal identifiers.
# The app deliberately has no `build` script, so `pnpm build` / turbo never
# publish it alongside the portal, admin, or JBrowse artifacts.
#
# Usage:
#   bash scripts/verify-docs-artifact.sh             # build, then verify
#   bash scripts/verify-docs-artifact.sh --no-build  # verify existing dist
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${ROOT}/apps/docs/dist"

log() { printf '[verify-docs-artifact] %s\n' "$*" >&2; }

if [[ "${1:-}" != "--no-build" ]]; then
  log "Build docs"
  (cd "${ROOT}" && pnpm docs:build)
fi

log "Verify required pages"
for page in \
  index.html \
  guide/index.html \
  design-tokens/index.html \
  motion/index.html \
  components/provider/index.html \
  components/chart-canvas/index.html \
  components/genome-view/index.html \
  components/motion-policy/index.html; do
  [[ -f "${DIST}/${page}" ]] || {
    echo "missing docs page: ${page}" >&2
    exit 1
  }
done

log "Verify no portal origins or internal identifiers leaked"
leaks="$(grep -rInE ':8001|:8002|100\.66\.114\.71|internal_id|legacy-clickhouse' "${DIST}" || true)"
if [[ -n "${leaks}" ]]; then
  printf '%s\n' "${leaks}" >&2
  echo "docs artifact must not reference site origins or internal identifiers" >&2
  exit 1
fi

log "Verify docs app stays out of the production build graph"
node -e '
const pkg = require(process.argv[1]);
if (pkg.scripts && pkg.scripts.build) {
  console.error("apps/docs must not define a build script; turbo would publish it");
  process.exit(1);
}
' "${ROOT}/apps/docs/package.json"

log "OK component docs artifact"
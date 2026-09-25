#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — local preview of the portal, the admin console and the API
# =============================================================================
# Serves the three behind ONE origin, because the portal's CSP requires an
# absolute API origin and a browser that is not on this host cannot reach
# 127.0.0.1. One origin also means a single tunnel exposes a complete demo.
#
#   :PORT/            portal   (apps/web/dist)  + /api/v1
#   :ADMIN_PORT/      console  (apps/admin/dist) + /api/v1
#
# Separate ports, not a subpath: the portal and the console are separate
# deployments with separate origins, caches and CSP, and a preview that mounts
# one under the other is a preview of a different topology.
#
# Prerequisites
#   * a PostgreSQL with the schema migrated and (for data) a published release;
#     `SOYMUTDB_DATABASE_URL` is required.
#   * the workspace installed (`pnpm install`).
#
# Usage
#   SOYMUTDB_DATABASE_URL=postgresql+asyncpg://... bash scripts/dev-local-preview.sh
#   SOYMUTDB_PREVIEW_ORIGIN=https://abc.trycloudflare.com ... # build for a tunnel
#
# Env
#   SOYMUTDB_DATABASE_URL    required; the database the API reads
#   SOYMUTDB_JWT_SECRET      required; >= 32 chars
#   SOYMUTDB_PREVIEW_PORT    origin port               (default 8090)
#   SOYMUTDB_PREVIEW_API_PORT API port                (default 8000)
#   SOYMUTDB_PREVIEW_ORIGIN  portal origin the browser uses (default http://localhost:$PORT)
#   SOYMUTDB_PREVIEW_ADMIN_PORT  console port          (default 8091)
#   SOYMUTDB_PREVIEW_ADMIN_ORIGIN console origin (default http://localhost:$ADMIN_PORT)
#   SOYMUTDB_PREVIEW_SKIP_BUILD 1 to reuse the existing dist trees
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

: "${SOYMUTDB_DATABASE_URL:?SOYMUTDB_DATABASE_URL is required (the API has no default database)}"
: "${SOYMUTDB_JWT_SECRET:?SOYMUTDB_JWT_SECRET is required (>= 32 characters)}"

PORT="${SOYMUTDB_PREVIEW_PORT:-8090}"
ADMIN_PORT="${SOYMUTDB_PREVIEW_ADMIN_PORT:-8091}"
API_PORT="${SOYMUTDB_PREVIEW_API_PORT:-8000}"
PORTAL_ORIGIN="${SOYMUTDB_PREVIEW_ORIGIN:-http://localhost:${PORT}}"
ADMIN_ORIGIN="${SOYMUTDB_PREVIEW_ADMIN_ORIGIN:-http://localhost:${ADMIN_PORT}}"
LOG_DIR="${SOYMUTDB_PREVIEW_LOG_DIR:-.dev-logs}"
mkdir -p "${LOG_DIR}"

log() { printf '[preview] %s\n' "$*" >&2; }

# The API reads these; the portal bakes the origin into its CSP and API base.
export SOYMUTDB_APP_ENV=dev
export SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=false
# Each app proxies the API on its own origin, so this list only matters for a
# browser that reaches the API directly.
export SOYMUTDB_CORS_ORIGINS="${PORTAL_ORIGIN},${ADMIN_ORIGIN}"

log "starting the API on 127.0.0.1:${API_PORT}"
(
  cd apps/api
  set -a; set +u
  # shellcheck disable=SC1091
  nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}" \
    > "${REPO_ROOT}/${LOG_DIR}/api.log" 2>&1 &
)
API_PID=$!
trap 'kill ${API_PID} 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null || {
  log "the API did not become healthy; see ${LOG_DIR}/api.log"
  exit 1
}

if [[ "${SOYMUTDB_PREVIEW_SKIP_BUILD:-0}" != "1" ]]; then
  # The API origin is absolute by contract, so the origin the browser will use is
  # part of the build, not a runtime value.
  log "building the portal for ${PORTAL_ORIGIN} and the console for ${ADMIN_ORIGIN}"
  ( cd apps/web && VITE_DEPLOYMENT_MODE=demo VITE_SITE_VARIANT=external \
      VITE_BASE_URL=/ VITE_API_BASE_URL="${PORTAL_ORIGIN}/api/v1" \
      VITE_JBROWSE_BASE_URL="${PORTAL_ORIGIN}/jbrowse/" SOYMUTDB_SITE_URL="${PORTAL_ORIGIN}" \
      pnpm build > "${REPO_ROOT}/${LOG_DIR}/web-build.log" 2>&1 )
  ( cd apps/admin && VITE_BASE_URL=/ VITE_API_BASE_URL="${ADMIN_ORIGIN}/api/v1" \
      pnpm build > "${REPO_ROOT}/${LOG_DIR}/admin-build.log" 2>&1 )
fi

log "serving the console on ${ADMIN_ORIGIN}"
node scripts/dev/local-preview-server.mjs --app admin --port "${ADMIN_PORT}" \
  > "${REPO_ROOT}/${LOG_DIR}/admin-server.log" 2>&1 &
ADMIN_PID=$!
trap 'kill ${API_PID} ${ADMIN_PID} 2>/dev/null || true' EXIT

log "serving the portal on ${PORTAL_ORIGIN}"
exec node scripts/dev/local-preview-server.mjs --app portal --port "${PORT}"

#!/usr/bin/env bash
# =====================================================================
# SoyMutDB development smoke (D4, native path)
# =====================================================================
# Exercises the deployment contract without Docker:
#   1. run Alembic migrations on a disposable development PostgreSQL;
#   2. start the real uvicorn application against it;
#   3. assert /health/live, /health/ready (PG-only ready, optional deps reported);
#   4. exercise a real API request chain (release context + search endpoint).
#
# Usage: scripts/deploy/smoke.sh --environment development
# Requires: disposable PostgreSQL reachable via SOYMUTDB_DATABASE_URL
# (see docs/dev/mamba-validation-environment.md). NEVER point at production.
# Exit 0 = smoke passed. No secrets printed; URLs below use trust-auth dev creds.
# =====================================================================
set -euo pipefail

ENVIRONMENT=""
DB_URL="${SOYMUTDB_DATABASE_URL:-postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_validation}"
API_HOST="${SOYMUTDB_SMOKE_HOST:-127.0.0.1}"
API_PORT="${SOYMUTDB_SMOKE_PORT:-8765}"
API_PID=""
trap '[[ -n "${API_PID}" ]] && kill "${API_PID}" 2>/dev/null || true' EXIT

while [[ $# -gt 0 ]]; do
    case "$1" in
        --environment) [[ $# -ge 2 ]] || { echo "--environment requires a value" >&2; exit 2; }; ENVIRONMENT="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[[ "${ENVIRONMENT}" == "development" ]] || {
    echo "refusing: smoke targets the disposable development environment only (H16)" >&2
    exit 2
}

API_ROOT="apps/api"
PY="${API_ROOT}/.venv/bin/python"
echo "1) migrations: alembic upgrade head on disposable development PostgreSQL"
(
    cd "${API_ROOT}"
    SOYMUTDB_DATABASE_URL="${DB_URL}" .venv/bin/python -m alembic -c alembic.ini upgrade head
)
echo "   migrations OK"

echo "2) start uvicorn (real application)"
SOYMUTDB_DATABASE_URL="${DB_URL}" \
SOYMUTDB_APP_ENV=dev \
SOYMUTDB_DEPLOYMENT_MODE=baseline \
SOYMUTDB_JWT_SECRET="dev-smoke-secret-not-for-production" \
SOYMUTDB_CORS_ORIGINS="http://localhost:4173" \
  "${API_ROOT}/.venv/bin/python" -m uvicorn app.main:app \
  --host "${API_HOST}" --port "${API_PORT}" \
  > /tmp/soymutdb-smoke-api.log 2>&1 &
API_PID=$!

for _ in $(seq 1 30); do
    if curl -sf "http://${API_HOST}:${API_PORT}/api/v1/health/live" >/dev/null 2>&1; then break; fi
    sleep 1
done

echo "3) health checks (real HTTP)"
live="$(curl -sf "http://${API_HOST}:${API_PORT}/api/v1/health/live")"
echo "   live: ${live}"
ready="$(curl -sf "http://${API_HOST}:${API_PORT}/api/v1/health/ready")"
echo "   ready: ${ready}"
echo "${ready}" | grep -q '"postgres"' || { echo "SMOKE FAIL: ready payload missing postgres check" >&2; exit 1; }

echo "4) real API chain: release context resolution + public search"
# Public search exercises DB-backed release-context resolution. On an empty
# disposable database the resolver fails closed (503, no active release) —
# that is the contracted behaviour, not a smoke failure. 200 proves the
# seeded path; 503 with service_unavailable proves context resolution.
code="$(curl -s -o /tmp/soymutdb-smoke-search.json -w '%{http_code}' \
  "http://${API_HOST}:${API_PORT}/api/v1/search?query=Glyma")"
echo "   search status: ${code}"
if [[ "${code}" == "200" ]]; then
    echo "   search body: $(head -c 120 /tmp/soymutdb-smoke-search.json)"
elif [[ "${code}" == "503" ]] && grep -q "service_unavailable\|No active data release" /tmp/soymutdb-smoke-search.json; then
    echo "   empty-database fail-closed release resolution confirmed (503)"
else
    echo "SMOKE FAIL: public search returned ${code} with $(head -c 200 /tmp/soymutdb-smoke-search.json)" >&2
    exit 1
fi

echo "SMOKE PASS: migrations + health (live/ready) + public API chain"

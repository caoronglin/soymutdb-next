#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Health Check Script
# =====================================================================
# Checks the health of all SoyMutDB services.
#
# Usage:
#   bash deploy/scripts/healthcheck.sh
# =====================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# Load environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
fi

API_HOST="${API_HOST:-localhost}"
# Compose only publishes nginx on 8080; set API_PORT=8010 for a direct/dev API.
API_PORT="${API_PORT:-8080}"
API_URL="http://${API_HOST}:${API_PORT}"

PASS=0
FAIL=0
WARN=0

check() {
    local name="$1"
    local cmd="$2"
    local expected="${3:-0}"

    if eval "${cmd}" >/dev/null 2>&1; then
        echo -e "  ${GREEN}[OK]${NC}   ${name}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}[FAIL]${NC} ${name}"
        FAIL=$((FAIL + 1))
    fi
}

check_warn() {
    local name="$1"
    local cmd="$2"

    if eval "${cmd}" >/dev/null 2>&1; then
        echo -e "  ${GREEN}[OK]${NC}   ${name}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${YELLOW}[WARN]${NC} ${name}"
        WARN=$((WARN + 1))
    fi
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Health Check${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ---------------------------------------------------------------------
# API checks
# ---------------------------------------------------------------------
echo "API Service (${API_URL}):"
check "API liveness endpoint" "curl -sf ${API_URL}/api/v1/health/live"
check "API readiness endpoint" "curl -sf ${API_URL}/api/v1/health/ready"
check "API metrics endpoint" "curl -sf ${API_URL}/metrics"
echo ""

# ---------------------------------------------------------------------
# Database checks
# ---------------------------------------------------------------------
echo "Databases:"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"

check "PostgreSQL connectivity" \
    "PGPASSWORD='${POSTGRES_PASSWORD:-soymutdb_dev_password}' pg_isready -h ${PG_HOST} -p ${PG_PORT} -U ${PG_USER}"

CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
check "ClickHouse ping" "curl -sf http://${CH_HOST}:${CH_PORT}/ping"

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
check_warn "Redis connectivity" \
    "redis-cli -h ${REDIS_HOST} -p ${REDIS_PORT} -a '${REDIS_PASSWORD:-soymutdb_dev_password}' ping"
echo ""

# ---------------------------------------------------------------------
# S3/MinIO checks
# ---------------------------------------------------------------------
echo "Object Storage:"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
check "MinIO health" "curl -sf ${S3_ENDPOINT}/minio/health/live"
echo ""

# ---------------------------------------------------------------------
# Frontend checks (if nginx is running)
# 前端静态站点（web）由 GitHub Pages（gh-pages 分支）托管，不在
# compose 中；nginx 仅反代 API，/health 即 API liveness 透传。
# ---------------------------------------------------------------------
echo "Frontend (GitHub Pages):"
NGINX_HOST="${NGINX_HOST:-localhost}"
NGINX_PORT="${NGINX_PORT:-8080}"
check_warn "Nginx /health proxy (API liveness)" "curl -sf http://${NGINX_HOST}:${NGINX_PORT}/health"
echo "  (web 静态站点由 GitHub Pages 托管，不在此检查)"
echo ""

# ---------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------
echo -e "${CYAN}========================================${NC}"
TOTAL=$((PASS + FAIL + WARN))
if [[ ${FAIL} -eq 0 ]]; then
    echo -e "${GREEN}  All critical checks passed!${NC}"
else
    echo -e "${RED}  ${FAIL} check(s) failed!${NC}"
fi
echo "  Passed: ${PASS}/${TOTAL}"
echo "  Failed: ${FAIL}/${TOTAL}"
echo "  Warnings: ${WARN}/${TOTAL}"
echo -e "${CYAN}========================================${NC}"

exit ${FAIL}

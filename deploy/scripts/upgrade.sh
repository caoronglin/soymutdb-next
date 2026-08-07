#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Upgrade Script (docker compose 主路径)
# =====================================================================
# 执行一次安全的生产发布。固定流程：
#   1. 配置校验（docker compose config）
#   2. 发布前预检（JWT/CORS/凭据，与 API fail-fast 校验对齐）
#   3. 拉取新镜像（docker compose pull）
#   4. 数据备份（deploy/scripts/backup.sh；首次部署且无运行容器时跳过）
#   5. 一次性迁移（docker compose run --rm migrate，alembic upgrade head）
#   6. 启动服务（docker compose up -d）
#   7. readiness 轮询（/api/v1/health/ready，失败自动回滚旧镜像并退出非零）
#   8. 业务 smoke（deploy/scripts/healthcheck.sh）
#   9. 记录发布结果（镜像 tag/digest、迁移版本、时间 -> .release-state.json）
#
# Usage:
#   sudo bash deploy/scripts/upgrade.sh
# 环境变量（可选）：SOYMUTDB_INSTALL_DIR、API_HOST、API_PORT、READY_RETRIES
# =====================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR] This script must be run as root (use sudo).${NC}"
    exit 1
fi

# ---------------------------------------------------------------------
# 定位 compose 项目目录（安装布局 /opt/soymutdb，或仓库根）
# ---------------------------------------------------------------------
if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
COMPOSE=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")

API_HOST="${API_HOST:-localhost}"
API_PORT="${API_PORT:-8000}"
READY_URL="http://${API_HOST}:${API_PORT}/api/v1/health/ready"
READY_RETRIES="${READY_RETRIES:-60}"   # 60 x 5s = 300s
READY_INTERVAL=5
STATE_FILE="${COMPOSE_DIR}/.release-state.json"

fail() {
    echo -e "${RED}[ERROR] $*${NC}" >&2
    exit 1
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Upgrade (compose)${NC}"
echo -e "${CYAN}  Compose dir: ${COMPOSE_DIR}${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ---------------------------------------------------------------------
# Step 1: 配置校验
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/9] Validating compose configuration...${NC}"
"${COMPOSE[@]}" config -q || fail "docker compose config failed (check ${COMPOSE_DIR}/.env variables)"
echo -e "${GREEN}  Compose config OK.${NC}"

# ---------------------------------------------------------------------
# Step 2: 发布前预检（与 apps/api/app/core/config.py prod 校验对齐）
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/9] Pre-flight checks...${NC}"
if [[ -f "${COMPOSE_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${COMPOSE_DIR}/.env"
    set +a
else
    fail "missing ${COMPOSE_DIR}/.env - copy deploy/.env.example and fill it first"
fi

[[ -n "${API_IMAGE_TAG:-}" ]] || fail "API_IMAGE_TAG is required (no bare :latest)"
[[ -n "${WORKER_IMAGE_TAG:-}" ]] || fail "WORKER_IMAGE_TAG is required (no bare :latest)"

if [[ -z "${SOYMUTDB_JWT_SECRET:-}" || "${#SOYMUTDB_JWT_SECRET}" -lt 32 ]]; then
    fail "SOYMUTDB_JWT_SECRET must be >= 32 characters (API will refuse to start otherwise)"
fi
if [[ -z "${SOYMUTDB_CORS_ORIGINS:-}" ]]; then
    fail "SOYMUTDB_CORS_ORIGINS is required (comma-separated origins, no wildcard)"
fi
if [[ "${MINIO_ROOT_USER:-minioadmin}" == "minioadmin" || "${MINIO_ROOT_PASSWORD:-minioadmin}" == "minioadmin" ]]; then
    fail "MINIO_ROOT_USER / MINIO_ROOT_PASSWORD must not use the default 'minioadmin' (API fail-fast)"
fi
if [[ "${POSTGRES_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" || \
      "${CLICKHOUSE_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" || \
      "${REDIS_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" ]]; then
    echo -e "${YELLOW}  [WARN] One or more datastore passwords still use the dev default - change them in .env${NC}"
fi
echo -e "${GREEN}  Pre-flight checks passed.${NC}"

# ---------------------------------------------------------------------
# Step 3: 拉取新镜像
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/9] Pulling images (${API_IMAGE_TAG}, ${WORKER_IMAGE_TAG})...${NC}"
"${COMPOSE[@]}" pull api migrate worker-default worker-blast worker-ingest beat || \
    fail "docker compose pull failed - check registry access and image tags"
echo -e "${GREEN}  Images pulled.${NC}"

# ---------------------------------------------------------------------
# Step 4: 数据备份（已有运行中的 postgres 才备份）
# ---------------------------------------------------------------------
echo -e "${CYAN}[4/9] Creating pre-upgrade backup...${NC}"
if [[ -n "$("${COMPOSE[@]}" ps -q postgres 2>/dev/null)" ]]; then
    bash "${SCRIPT_DIR}/backup.sh" || fail "backup failed - aborting upgrade (see deploy/scripts/backup.sh)"
    echo -e "${GREEN}  Backup complete.${NC}"
else
    echo -e "${YELLOW}  No running postgres container - first deploy, skipping backup.${NC}"
fi

# ---------------------------------------------------------------------
# Step 5: 一次性迁移（alembic upgrade head）
# ---------------------------------------------------------------------
echo -e "${CYAN}[5/9] Running one-shot migrations...${NC}"
"${COMPOSE[@]}" up -d postgres
for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" ps --status running postgres --format '{{.Health}}' 2>/dev/null | grep -q healthy; then
        break
    fi
    sleep 2
done
"${COMPOSE[@]}" run --rm migrate || fail "database migration failed - fix and re-run"
migration_version="$("${COMPOSE[@]}" run --rm --no-deps migrate alembic current 2>/dev/null | tail -1)"
echo -e "${GREEN}  Migrations complete (head: ${migration_version}).${NC}"

# ---------------------------------------------------------------------
# Step 6: 记录旧版本（用于失败回滚）
# ---------------------------------------------------------------------
OLD_API_TAG=""
OLD_WORKER_TAG=""
if [[ -f "${STATE_FILE}" ]]; then
    OLD_API_TAG="$(sed -n 's/.*"api_image_tag": *"\([^"]*\)".*/\1/p' "${STATE_FILE}" | head -1)"
    OLD_WORKER_TAG="$(sed -n 's/.*"worker_image_tag": *"\([^"]*\)".*/\1/p' "${STATE_FILE}" | head -1)"
fi
echo -e "  Previous release recorded: api=${OLD_API_TAG:-none} worker=${OLD_WORKER_TAG:-none}"

# ---------------------------------------------------------------------
# Step 7: 启动服务 + readiness 轮询（失败回滚）
# ---------------------------------------------------------------------
echo -e "${CYAN}[6/9] Starting services...${NC}"
"${COMPOSE[@]}" up -d

echo -e "${CYAN}[7/9] Waiting for readiness: ${READY_URL} (${READY_RETRIES} x ${READY_INTERVAL}s)...${NC}"
ready=false
for _ in $(seq 1 "${READY_RETRIES}"); do
    if curl -sf "${READY_URL}" >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep "${READY_INTERVAL}"
done

if [[ "${ready}" != "true" ]]; then
    echo -e "${RED}[ERROR] API not ready within ${READY_RETRIES} x ${READY_INTERVAL}s - rolling back${NC}" >&2
    if [[ -n "${OLD_API_TAG}" && -n "${OLD_WORKER_TAG}" ]]; then
        echo -e "${YELLOW}  Rolling back to api=${OLD_API_TAG} worker=${OLD_WORKER_TAG}...${NC}"
        API_IMAGE_TAG="${OLD_API_TAG}" WORKER_IMAGE_TAG="${OLD_WORKER_TAG}" \
            "${COMPOSE[@]}" up -d api worker-default worker-blast worker-ingest beat || \
            echo -e "${RED}  Rollback command failed - manual intervention required${NC}" >&2
        for _ in $(seq 1 "${READY_RETRIES}"); do
            if curl -sf "${READY_URL}" >/dev/null 2>&1; then
                echo -e "${GREEN}  Rollback healthy.${NC}"
                exit 1
            fi
            sleep "${READY_INTERVAL}"
        done
        echo -e "${RED}  Rolled-back stack also unhealthy - manual intervention required${NC}" >&2
    else
        echo -e "${RED}  No previous release recorded - manual intervention required${NC}" >&2
    fi
    exit 1
fi
echo -e "${GREEN}  API ready.${NC}"

# ---------------------------------------------------------------------
# Step 8: 业务 smoke
# ---------------------------------------------------------------------
echo -e "${CYAN}[8/9] Running business smoke checks...${NC}"
bash "${SCRIPT_DIR}/healthcheck.sh" || fail "smoke checks failed after upgrade - inspect logs"
echo -e "${GREEN}  Smoke checks passed.${NC}"

# ---------------------------------------------------------------------
# Step 9: 记录发布结果
# ---------------------------------------------------------------------
echo -e "${CYAN}[9/9] Recording release result...${NC}"
api_digest="n/a"
api_container_id="$("${COMPOSE[@]}" ps -q api 2>/dev/null || true)"
if [[ -n "${api_container_id}" ]]; then
    api_digest="$(docker inspect -f '{{index .RepoDigests 0}}' "${api_container_id}" 2>/dev/null || echo 'n/a')"
fi
released_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${STATE_FILE}" <<EOF
{
  "api_image_tag": "${API_IMAGE_TAG}",
  "worker_image_tag": "${WORKER_IMAGE_TAG}",
  "api_digest": "${api_digest}",
  "migration_version": "${migration_version}",
  "released_at": "${released_at}"
}
EOF
echo -e "${GREEN}  Release recorded: ${STATE_FILE}${NC}"
echo "    api_image_tag:     ${API_IMAGE_TAG}"
echo "    worker_image_tag:  ${WORKER_IMAGE_TAG}"
echo "    api_digest:        ${api_digest}"
echo "    migration_version: ${migration_version}"
echo "    released_at:       ${released_at}"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Upgrade Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Check status: sudo systemctl status soymutdb.target"
echo "  View logs:    cd ${COMPOSE_DIR} && docker compose logs -f api"
echo ""

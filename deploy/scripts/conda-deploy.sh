#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Conda Deployment Script（备选部署路径，D6 重新启用）
# =====================================================================
# 与 docker compose 主路径（deploy/linux/install.sh + upgrade.sh）互补，
# 适用于无 docker / 离线 / 本地开发服务器。完整指南见 deploy/conda/README.md。
#
# 流程：
#   1. 检查 conda 可用
#   2. 创建/更新两个环境：soymutdb-api（python 3.14）、soymutdb-worker
#      （python 3.13）—— 首次 conda env create -f，已存在则 conda env update -f
#   3. 可选：把仓库 apps/api、apps/worker 以 --no-deps -e 安装进对应环境
#      （依赖已在步骤 2 装好；设置 SOYMUTDB_SKIP_PIP_INSTALL=1 可跳过）
#   4. 初始化目录（${INSTALL_DIR}/{data,logs,config}）
#   5. 生成 .env（缺失时从 deploy/.env.example 复制，并注释 compose 专用
#      镜像 digest ref 行；conda 模式下应用变量使用 SOYMUTDB_ 前缀）
#   6. 启动前校验（与 apps/api/app/core/config.py 生产 fail-fast 对齐：
#      JWT>=32 字符、CORS 非空且不含通配符）
#   7. 输出启动命令模板（uvicorn / celery multi / beat / alembic）
#
# Usage:
#   bash deploy/scripts/conda-deploy.sh
# 环境变量（可选）：
#   SOYMUTDB_INSTALL_DIR      安装目录（默认 /opt/soymutdb，非 root 请改为可写路径）
#   SOYMUTDB_SKIP_PIP_INSTALL 设为 1 跳过步骤 3（应用代码已装/用 PYTHONPATH）
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

API_ENV="soymutdb-api"
WORKER_ENV="soymutdb-worker"

fail() {
    echo -e "${RED}[ERROR] $*${NC}" >&2
    exit 1
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Conda Deploy (备选路径)${NC}"
echo -e "${CYAN}  Project: ${PROJECT_ROOT}${NC}"
echo -e "${CYAN}  Install: ${INSTALL_DIR}${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# ---------------------------------------------------------------------
# Step 1: 检查 conda
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/7] Checking conda...${NC}"
if ! command -v conda &>/dev/null; then
    fail "conda not found. Install Miniforge first (https://github.com/conda-forge/miniforge)"
fi
CONDA_BASE="$(conda info --base)"
echo -e "${GREEN}  conda: $("${CONDA_BASE}/bin/conda" --version 2>/dev/null || conda --version) (base: ${CONDA_BASE})${NC}"

# ---------------------------------------------------------------------
# Step 2: 创建/更新两个 conda 环境
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/7] Ensuring conda environments...${NC}"

env_exists() {
    conda env list | awk '{print $1}' | grep -qx "$1"
}

for spec in "${API_ENV}:${PROJECT_ROOT}/deploy/conda/environment-api.yml" \
            "${WORKER_ENV}:${PROJECT_ROOT}/deploy/conda/environment-worker.yml"; do
    env_name="${spec%%:*}"
    yml_file="${spec#*:}"
    if env_exists "${env_name}"; then
        echo -e "  ${YELLOW}${env_name} exists - running conda env update${NC}"
        conda env update -f "${yml_file}" --prune
    else
        echo -e "  ${GREEN}${env_name} missing - running conda env create${NC}"
        conda env create -f "${yml_file}"
    fi
done
echo -e "${GREEN}  Environments ready: ${API_ENV} (python 3.14), ${WORKER_ENV} (python 3.13).${NC}"

# ---------------------------------------------------------------------
# Step 3: 安装应用代码（可选，依赖已在 env 内）
# ---------------------------------------------------------------------
if [[ "${SOYMUTDB_SKIP_PIP_INSTALL:-0}" == "1" ]]; then
    echo -e "${YELLOW}[3/7] Skipping app pip install (SOYMUTDB_SKIP_PIP_INSTALL=1).${NC}"
elif [[ ! -d "${PROJECT_ROOT}/apps/api" || ! -d "${PROJECT_ROOT}/apps/worker" ]]; then
    echo -e "${YELLOW}[3/7] apps/ not found at repo root - skipping app pip install.${NC}"
    echo -e "${YELLOW}  Use PYTHONPATH=${PROJECT_ROOT}/apps/api,${PROJECT_ROOT}/apps/worker/src instead.${NC}"
else
    echo -e "${CYAN}[3/7] Installing app code into envs (--no-deps, editable)...${NC}"
    conda run -n "${API_ENV}" python -m pip install --no-deps -e "${PROJECT_ROOT}/apps/api"
    conda run -n "${WORKER_ENV}" python -m pip install --no-deps -e "${PROJECT_ROOT}/apps/worker"
    echo -e "${GREEN}  App code installed (editable, deps from env).${NC}"
fi

# ---------------------------------------------------------------------
# Step 4: 初始化目录
# ---------------------------------------------------------------------
echo -e "${CYAN}[4/7] Initializing directories...${NC}"
if ! mkdir -p "${INSTALL_DIR}"/{data,logs,config} 2>/dev/null; then
    fail "cannot create ${INSTALL_DIR} - run as root or set SOYMUTDB_INSTALL_DIR to a writable path"
fi
echo -e "${GREEN}  Directories ready: ${INSTALL_DIR}/{data,logs,config}.${NC}"

# ---------------------------------------------------------------------
# Step 5: 生成 .env（缺失时）
# ---------------------------------------------------------------------
echo -e "${CYAN}[5/7] Ensuring environment file...${NC}"
ENV_FILE="${INSTALL_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
    echo -e "${YELLOW}  ${ENV_FILE} exists - keeping as is.${NC}"
else
    CONDA_ENV_TEMPLATE="${PROJECT_ROOT}/deploy/conda/env.example"
    if [[ -f "${CONDA_ENV_TEMPLATE}" ]]; then
        cp "${CONDA_ENV_TEMPLATE}" "${ENV_FILE}"
        echo -e "${GREEN}  Created ${ENV_FILE} from deploy/conda/env.example.${NC}"
    else
        cp "${PROJECT_ROOT}/deploy/.env.example" "${ENV_FILE}"
        # conda 模式无镜像概念：注释掉 compose 专用 digest ref，避免误导
        sed -i 's/^\([A-Z]*_IMAGE_REF=\)/# conda 模式无需镜像 digest（由源码\/editable 安装提供）：\1/' "${ENV_FILE}"
        echo -e "${GREEN}  Created ${ENV_FILE} from deploy/.env.example (fallback).${NC}"
    fi
    echo -e "${YELLOW}  >>> 请编辑 ${ENV_FILE}：SOYMUTDB_JWT_SECRET / SOYMUTDB_CORS_ORIGINS /"
    echo -e "${YELLOW}      数据层连接（SOYMUTDB_DATABASE_URL / SOYMUTDB_CLICKHOUSE_* /"
    echo -e "${YELLOW}      SOYMUTDB_REDIS_URL / SOYMUTDB_CELERY_BROKER_URL / SOYMUTDB_S3_ENDPOINT）<<<${NC}"
fi

# ---------------------------------------------------------------------
# Step 6: 启动前校验（与 API prod fail-fast 对齐）
# ---------------------------------------------------------------------
echo -e "${CYAN}[6/7] Pre-flight checks...${NC}"
set -a
# shellcheck disable=SC1091
source "${ENV_FILE}"
set +a

if [[ -z "${SOYMUTDB_JWT_SECRET:-}" || "${#SOYMUTDB_JWT_SECRET}" -lt 32 ]]; then
    fail "SOYMUTDB_JWT_SECRET must be >= 32 characters (API will refuse to start otherwise)"
fi
if [[ "${SOYMUTDB_JWT_SECRET:-}" == *please-generate* || "${SOYMUTDB_JWT_SECRET:-}" == *change-me* ]]; then
    echo -e "${YELLOW}  [WARN] SOYMUTDB_JWT_SECRET still looks like the template placeholder - generate a real secret.${NC}"
fi
if [[ -z "${SOYMUTDB_CORS_ORIGINS:-}" ]]; then
    fail "SOYMUTDB_CORS_ORIGINS is required (comma-separated origins, no wildcard)"
fi
if [[ "${SOYMUTDB_CORS_ORIGINS}" == *"*"* ]]; then
    fail "SOYMUTDB_CORS_ORIGINS cannot contain '*' when credentials are enabled (API fail-fast)"
fi
for required_var in     SOYMUTDB_DATABASE_URL SOYMUTDB_CLICKHOUSE_HOST SOYMUTDB_CLICKHOUSE_PASSWORD     SOYMUTDB_REDIS_URL SOYMUTDB_CELERY_BROKER_URL SOYMUTDB_CELERY_RESULT_BACKEND     SOYMUTDB_S3_ENDPOINT SOYMUTDB_S3_ACCESS_KEY SOYMUTDB_S3_SECRET_KEY; do
    if [[ -z "${!required_var:-}" ]]; then
        fail "${required_var} is required in ${ENV_FILE} for conda deployment"
    fi
done
if [[ "${SOYMUTDB_DATABASE_URL:-}" != postgresql+asyncpg://* ]]; then
    fail "SOYMUTDB_DATABASE_URL must use the postgresql+asyncpg:// scheme for the API"
fi
if [[ "${SOYMUTDB_S3_ACCESS_KEY:-}" == *change-me* || "${SOYMUTDB_S3_SECRET_KEY:-}" == *change-me* ]]; then
    echo -e "${YELLOW}  [WARN] SOYMUTDB_S3_ACCESS_KEY/SECRET_KEY still look like template placeholders.${NC}"
fi
if [[ "${POSTGRES_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" || \
      "${CLICKHOUSE_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" || \
      "${REDIS_PASSWORD:-soymutdb_dev_password}" == "soymutdb_dev_password" ]]; then
    echo -e "${YELLOW}  [WARN] One or more datastore passwords still use the dev default - change them in ${ENV_FILE}${NC}"
fi
echo -e "${GREEN}  Pre-flight checks passed.${NC}"

# ---------------------------------------------------------------------
# Step 7: 输出启动命令模板
# ---------------------------------------------------------------------
echo -e "${CYAN}[7/7] Startup commands (copy & run):${NC}"
echo ""
echo "  # 一次性迁移（首次/升级后执行）"
echo "  cd ${PROJECT_ROOT}/apps/api && conda run -n ${API_ENV} alembic upgrade head"
echo ""
echo "  # API（FastAPI，4 workers；--proxy-headers 供 nginx 反代取真实 IP）"
echo "  cd ${PROJECT_ROOT}/apps/api && conda run -n ${API_ENV} uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips=*"
echo ""
echo "  # Celery worker（队列契约：ingest,export,stats,cleanup,default / blast / analyses）"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=4 --max-tasks-per-child=100 --hostname=worker-default@%h"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=blast --concurrency=2 --max-tasks-per-child=50 --hostname=worker-blast@%h"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=2 --max-tasks-per-child=20 --hostname=worker-ingest@%h"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=analyses --concurrency=2 --max-tasks-per-child=20 --hostname=worker-analyses@%h"
echo ""
echo "  # beat（定时任务）"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app beat --loglevel=info --schedule=${INSTALL_DIR}/data/celerybeat-schedule"
echo ""
echo "  # 简化：单命令 celery multi（四个 worker 后台运行，日志写 ${INSTALL_DIR}/logs/）"
echo "  conda run -n ${WORKER_ENV} celery -A soymutdb_worker.main:celery_app multi start worker-default worker-blast worker-ingest worker-analyses \\"
echo "    -Q:worker-default ingest,export,stats,cleanup,default -Q:worker-blast blast -Q:worker-ingest ingest,export,stats,cleanup,default -Q:worker-analyses analyses \\"
echo "    --concurrency:worker-default=4 --concurrency:worker-blast=2 --concurrency:worker-ingest=2 --concurrency:worker-analyses=2 \\"
echo "    --logfile=${INSTALL_DIR}/logs/worker-%n.log --pidfile=${INSTALL_DIR}/logs/worker-%n.pid"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Conda deploy prepared.${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  .env:            ${ENV_FILE}"
echo "  API health:      curl http://localhost:8000/api/v1/health/live"
echo "  推荐组合:        docker 起数据层（postgres/clickhouse/redis/redis-celery/minio）"
echo "                   + conda 跑应用层（api/worker/beat）——见 deploy/conda/README.md"
echo ""

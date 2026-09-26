#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Conda systemd 单元生成器（无 Docker 部署探索）
# =====================================================================
# 为 conda 裸进程生成 systemd units：
#   soymutdb-api.service
#   soymutdb-worker-default.service
#   soymutdb-worker-blast.service
#   soymutdb-worker-ingest.service
#   soymutdb-worker-analyses.service
#   soymutdb-beat.service
#
# 用法：
#   bash deploy/scripts/conda-services.sh --print     # 打印到 stdout（默认）
#   sudo bash deploy/scripts/conda-services.sh --install  # 写入 /etc/systemd/system 并 daemon-reload
#
# 环境变量：
#   SOYMUTDB_INSTALL_DIR   安装目录（默认 /opt/soymutdb）
#   SOYMUTDB_API_ENV_BIN   API conda env 的 bin 目录（默认 <conda_base>/envs/soymutdb-api/bin）
#   SOYMUTDB_WORKER_ENV_BIN Worker conda env 的 bin 目录（默认 <conda_base>/envs/soymutdb-worker/bin）
#   SOYMUTDB_API_WORKERS   API worker 进程数（默认 4）
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
ENV_FILE="${INSTALL_DIR}/.env"
MODE="${1:---print}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

if [[ ! -f "${ENV_FILE}" ]]; then
    fail "${ENV_FILE} not found. Run conda-deploy.sh first or set SOYMUTDB_INSTALL_DIR."
fi

if ! command -v conda >/dev/null 2>&1; then
    fail "conda not found"
fi
CONDA_BASE="$(conda info --base)"
API_ENV_BIN="${SOYMUTDB_API_ENV_BIN:-${CONDA_BASE}/envs/soymutdb-api/bin}"
WORKER_ENV_BIN="${SOYMUTDB_WORKER_ENV_BIN:-${CONDA_BASE}/envs/soymutdb-worker/bin}"
API_WORKERS="${SOYMUTDB_API_WORKERS:-4}"

if [[ ! -x "${API_ENV_BIN}/uvicorn" ]]; then
    warn "uvicorn not found at ${API_ENV_BIN}/uvicorn; generated unit may fail until env is created."
fi
if [[ ! -x "${WORKER_ENV_BIN}/celery" ]]; then
    warn "celery not found at ${WORKER_ENV_BIN}/celery; generated unit may fail until env is created."
fi

unit_api() {
cat <<UNIT
[Unit]
Description=SoyMutDB API (conda)
After=network.target postgresql.service clickhouse-server.service redis-server.service minio.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/api
EnvironmentFile=${ENV_FILE}
ExecStart=${API_ENV_BIN}/uvicorn app.main:app --host 0.0.0.0 --port 8010 --workers ${API_WORKERS} --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
}

unit_worker_default() {
cat <<UNIT
[Unit]
Description=SoyMutDB Celery Worker (default/ingest/export/stats/cleanup)
After=network.target redis-server.service soymutdb-api.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/worker
EnvironmentFile=${ENV_FILE}
ExecStart=${WORKER_ENV_BIN}/celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=4 --max-tasks-per-child=100 --hostname=worker-default@%%h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}

unit_worker_blast() {
cat <<UNIT
[Unit]
Description=SoyMutDB Celery Worker (blast)
After=network.target redis-server.service soymutdb-api.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/worker
EnvironmentFile=${ENV_FILE}
ExecStart=${WORKER_ENV_BIN}/celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=blast --concurrency=2 --max-tasks-per-child=50 --hostname=worker-blast@%%h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}

unit_worker_ingest() {
cat <<UNIT
[Unit]
Description=SoyMutDB Celery Worker (ingest/export/stats/cleanup)
After=network.target redis-server.service soymutdb-api.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/worker
EnvironmentFile=${ENV_FILE}
ExecStart=${WORKER_ENV_BIN}/celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=2 --max-tasks-per-child=20 --hostname=worker-ingest@%%h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}

unit_worker_analyses() {
cat <<UNIT
[Unit]
Description=SoyMutDB Celery Worker (analyses)
After=network.target redis-server.service soymutdb-api.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/worker
EnvironmentFile=${ENV_FILE}
ExecStart=${WORKER_ENV_BIN}/celery -A soymutdb_worker.main:celery_app worker --loglevel=info --queues=analyses --concurrency=2 --max-tasks-per-child=20 --hostname=worker-analyses@%%h
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}

unit_beat() {
cat <<UNIT
[Unit]
Description=SoyMutDB Celery Beat (conda)
After=network.target redis-server.service soymutdb-api.service

[Service]
User=${SOYMUTDB_SERVICE_USER:-soymutdb}
Group=${SOYMUTDB_SERVICE_GROUP:-soymutdb}
WorkingDirectory=${PROJECT_ROOT}/apps/worker
EnvironmentFile=${ENV_FILE}
ExecStart=${WORKER_ENV_BIN}/celery -A soymutdb_worker.main:celery_app beat --loglevel=info --schedule=${INSTALL_DIR}/data/celerybeat-schedule
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
}

UNITS=(api worker-default worker-blast worker-ingest worker-analyses beat)

if [[ "${MODE}" == "--print" ]]; then
    for name in "${UNITS[@]}"; do
        echo "### soymutdb-${name}.service"
        "unit_${name//-/_}"
        echo ""
    done
    exit 0
fi

if [[ "${MODE}" == "--install" ]]; then
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        fail "--install requires root (or run with sudo)"
    fi
    mkdir -p "${INSTALL_DIR}/data" "${INSTALL_DIR}/logs"
    for name in "${UNITS[@]}"; do
        "unit_${name//-/_}" > "/etc/systemd/system/soymutdb-${name}.service"
        info "wrote /etc/systemd/system/soymutdb-${name}.service"
    done
    systemctl daemon-reload
    info "systemd daemon reloaded. Enable/start with:"
    for name in "${UNITS[@]}"; do
        echo "  sudo systemctl enable --now soymutdb-${name}"
    done
    exit 0
fi

fail "Unknown mode '${MODE}' (expected --print or --install)"

#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Conda 数据层初始化（无 Docker 探索用）
# =====================================================================
# 作用：
#   - 从 $INSTALL_DIR/.env 读取 SOYMUTDB_* 连接变量
#   - 探测本机 PostgreSQL / ClickHouse / MinIO（mc）是否可用
#   - 幂等创建 PG 用户/库、CH 数据库/用户、MinIO 桶
#   - 不修改 Redis 配置（仅提示两个实例要求）
#   - 不删除/覆盖任何已有数据
#
# 用法：
#   bash deploy/scripts/conda-data-init.sh            # 初始化
#   bash deploy/scripts/conda-data-init.sh --check    # 只检查并打印待办
#
# 依赖（可选）：
#   psql / clickhouse-client / mc；缺失时对应步骤自动跳过并提示。
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
ENV_FILE="${INSTALL_DIR}/.env"
MODE="${1:-init}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

if [[ ! -f "${ENV_FILE}" ]]; then
    fail "${ENV_FILE} not found. Run conda-deploy.sh first or set SOYMUTDB_INSTALL_DIR."
fi

set -a
# shellcheck disable=SC1091
source "${ENV_FILE}"
set +a

# 统一读取 SOYMUTDB_ 变量，允许从 .env 直接使用 SOYMUTDB_ 前缀
PG_URL="${SOYMUTDB_DATABASE_URL:-}"
CH_HOST="${SOYMUTDB_CLICKHOUSE_HOST:-127.0.0.1}"
CH_PORT="${SOYMUTDB_CLICKHOUSE_PORT:-8123}"
CH_USER="${SOYMUTDB_CLICKHOUSE_USER:-soymutdb}"
CH_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-}"
CH_DATABASE="${SOYMUTDB_CLICKHOUSE_DATABASE:-soymutdb}"
S3_ENDPOINT="${SOYMUTDB_S3_ENDPOINT:-http://127.0.0.1:9000}"
S3_ACCESS="${SOYMUTDB_S3_ACCESS_KEY:-}"
S3_SECRET="${SOYMUTDB_S3_SECRET_KEY:-}"

echo "== SoyMutDB Conda Data Init =="
echo "  mode: ${MODE}"
echo "  env:  ${ENV_FILE}"
echo ""

# ---------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------
if command -v psql >/dev/null 2>&1; then
    # 从 URL 解析 user/db/host/port（简化：仅支持 postgresql+asyncpg://user:pass@host:port/db）
    pg_user="$(printf '%s' "${PG_URL}" | sed -n 's#^postgresql+asyncpg://\([^:]*\):.*#\1#p')"
    pg_db="$(printf '%s' "${PG_URL}" | sed -n 's#.*/\([^/]*\)$#\1#p')"
    if [[ -n "${pg_user}" && -n "${pg_db}" ]]; then
        if [[ "${MODE}" == "--check" ]]; then
            if sudo -n -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${pg_user}'" 2>/dev/null | grep -q 1; then
                info "PostgreSQL role '${pg_user}' exists"
            else
                warn "PostgreSQL role '${pg_user}' missing (run init as root or with sudo)"
            fi
        else
            info "Creating PostgreSQL role/database if missing (${pg_user}/${pg_db})"
            sudo -u postgres psql <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${pg_user}') THEN
    CREATE ROLE ${pg_user} LOGIN PASSWORD '${SOYMUTDB_POSTGRES_PASSWORD:-change-me-postgres}';
  END IF;
END
\$\$;
SQL
            sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${pg_db}'" | grep -q 1 || \
                sudo -u postgres createdb -O "${pg_user}" "${pg_db}"
            info "PostgreSQL ready: ${pg_user}/${pg_db}"
        fi
    else
        warn "Could not parse SOYMUTDB_DATABASE_URL; skipping PostgreSQL init"
    fi
else
    warn "psql not found; skipping PostgreSQL init"
fi

# ---------------------------------------------------------------------
# ClickHouse
# ---------------------------------------------------------------------
if command -v clickhouse-client >/dev/null 2>&1; then
    if [[ "${MODE}" == "--check" ]]; then
        clickhouse-client --host "${CH_HOST}" --port "${CH_PORT}" \
            --user "${CH_USER}" --password "${CH_PASSWORD}" \
            --query "SELECT 1" >/dev/null 2>&1 && \
            info "ClickHouse reachable (${CH_HOST}:${CH_PORT})" || \
            warn "ClickHouse not reachable with configured credentials"
    else
        info "Creating ClickHouse database/user if missing"
        clickhouse-client --host "${CH_HOST}" --port "${CH_PORT}" \
            --user "${CH_USER}" --password "${CH_PASSWORD}" \
            --query "CREATE DATABASE IF NOT EXISTS ${CH_DATABASE}" || true
        # 如果当前用户已有权限，下面会因权限不足失败；用 --multiquery 包裹避免中断
        clickhouse-client --host "${CH_HOST}" --port "${CH_PORT}" \
            --user "${CH_USER}" --password "${CH_PASSWORD}" \
            --multiquery "CREATE USER IF NOT EXISTS ${CH_USER} IDENTIFIED WITH sha256_password BY '${CH_PASSWORD}'; GRANT ALL ON ${CH_DATABASE}.* TO ${CH_USER};" || \
            warn "ClickHouse user grant skipped (may already exist or insufficient privilege)"
        info "ClickHouse database ready: ${CH_DATABASE}"
    fi
else
    warn "clickhouse-client not found; skipping ClickHouse init (use HTTP API or install client)"
fi

# ---------------------------------------------------------------------
# MinIO buckets
# ---------------------------------------------------------------------
if command -v mc >/dev/null 2>&1 && [[ -n "${S3_ACCESS}" && -n "${S3_SECRET}" ]]; then
    if ! mc alias list 2>/dev/null | grep -q '^local '; then
        mc alias set local "${S3_ENDPOINT}" "${S3_ACCESS}" "${S3_SECRET}" >/dev/null
    fi
    if [[ "${MODE}" == "--check" ]]; then
        info "MinIO alias 'local' configured (${S3_ENDPOINT})"
    else
        for bucket in \
            "${SOYMUTDB_S3_PUBLIC_BUCKET:-genomic-data}" \
            "${SOYMUTDB_S3_PRIVATE_BUCKET:-user-tracks}" \
            "${SOYMUTDB_S3_BLAST_BUCKET:-blast-dbs}" \
            "${SOYMUTDB_S3_EXPORT_BUCKET:-exports}" \
            "${SOYMUTDB_S3_GWAS_BUCKET:-gwas}" \
            "${SOYMUTDB_S3_ANALYSES_BUCKET:-analyses}"; do
            mc mb --ignore-existing "local/${bucket}"
        done
        mc policy set public "local/${SOYMUTDB_S3_PUBLIC_BUCKET:-genomic-data}" >/dev/null || true
        mc version enable "local/${SOYMUTDB_S3_PRIVATE_BUCKET:-user-tracks}" >/dev/null || true
        info "MinIO buckets ready"
    fi
else
    warn "mc not found or S3 credentials missing; skipping MinIO bucket init"
fi

# ---------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------
info "Redis note: configure two instances manually (see deploy/conda/no-docker-data-layer.md)."
if command -v redis-cli >/dev/null 2>&1; then
    redis-cli -u "${SOYMUTDB_REDIS_URL:-redis://127.0.0.1:6379/0}" ping >/dev/null 2>&1 && \
        info "Cache Redis reachable" || warn "Cache Redis not reachable at SOYMUTDB_REDIS_URL"
    redis-cli -u "${SOYMUTDB_CELERY_BROKER_URL:-redis://127.0.0.1:6380/0}" ping >/dev/null 2>&1 && \
        info "Celery Redis reachable" || warn "Celery Redis not reachable at SOYMUTDB_CELERY_BROKER_URL"
fi

echo ""
if [[ "${MODE}" == "--check" ]]; then
    echo "== Check complete =="
else
    echo "== Data init complete (best-effort) =="
fi

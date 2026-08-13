#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Unified Backup Script (v2)
# =====================================================================
# 一次 run 内完成全部数据面的权威备份：
#   [1] PostgreSQL   pg_dump (custom format) + 行数快照 (pg_rows.tsv)
#   [2] ClickHouse   BACKUP DATABASE soymutdb TO Disk('backups', ...)
#                    （产物从容器内复制进最终 tar；含事实表 variant_facts、
#                    维度表与物化视图；另存每表行数/分区数快照）
#   [3] MinIO/S3     mc mirror 各 bucket 对象到本地 + 每对象 SHA-256
#                    清单 (s3_manifest.tsv) + bucket policy
#   [4] manifest     backup_id（时间戳+短 sha）、组件文件清单、大小、SHA-256
#   [5] tar.gz + <id>.tar.gz.sha256 校验文件
#   [6] 可选：上传到独立 S3 备份位置（BACKUP_S3）
#   [7] 保留策略：默认 7 日备 + 4 周备 + 6 月备（滚动删除，可配置）
#
# Redis 不备份（设计如此）：缓存 Redis（allkeys-lru 可驱逐）与
# redis-celery（broker/result，消息 TTL 有限）均为易失/可重建状态；
# Job/Outbox 等权威状态全部在 PostgreSQL 中，恢复后由应用重建缓存与队列。
#
# 恢复演练（建议至少每月一次，假数据隔离环境）：
#   1. 在隔离主机/独立 compose 项目启动一套空栈（同版本镜像）
#   2. TARGET=drill 并指向隔离栈，执行:
#        bash deploy/scripts/restore.sh --target drill <backup>.tar.gz
#   3. 执行验证:
#        bash deploy/scripts/verify-restore.sh <backup>.tar.gz
#      全部 PASS 且退出码 0 才视为演练成功
#
# Usage:
#   bash deploy/scripts/backup.sh
#   bash deploy/scripts/backup.sh --full     # 兼容旧参数：v2 默认即全量
#   bash deploy/scripts/backup.sh --help
#
# 环境变量（均有默认值，无需配置即可运行）：
#   BAK_BASE_DIR            本地备份根目录（默认 /opt/soymutdb/backups）
#   BACKUP_S3               可选异地备份目标 <alias>/<bucket>/<prefix>，
#                           如 backup-bkt/soymutdb/backups（为空=仅本地）
#   BACKUP_S3_ENDPOINT      异地备份 S3 endpoint（可选，缺省用已有 mc alias）
#   BACKUP_S3_ACCESS_KEY / BACKUP_S3_SECRET_KEY  异地备份凭据（可选）
#   BAK_S3_BUCKETS          需要备份对象数据的 bucket 列表
#                           （默认 "genomic-data user-tracks blast-dbs exports gwas"；
#                           analyses 为临时可重建数据，默认不纳入）
#   BAK_RETAIN_DAILY        保留日备数（默认 7）
#   BAK_RETAIN_WEEKLY       保留周备数（默认 4）
#   BAK_RETAIN_MONTHLY      保留月备数（默认 6）
#   BAK_S3_HASH_OBJECTS     对 S3 对象计算 SHA-256（默认 1；大数据可设 0
#                           关闭，代价是 restore 校验只能比对数量/大小）
#   SOYMUTDB_INSTALL_DIR    安装布局目录（缺省自动探测 compose 项目）
# 连接目标（默认本机 compose 栈；隔离演练时覆盖指向演练栈）：
#   POSTGRES_HOST/POSTGRES_PORT/POSTGRES_USER/POSTGRES_DB/POSTGRES_PASSWORD
#   S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY
#   CLICKHOUSE_HOST/CLICKHOUSE_PORT/CLICKHOUSE_USER/CLICKHOUSE_PASSWORD
#
# 安全：本脚本不在命令行或日志中打印任何密钥/密码；
#       compose 容器内命令利用容器注入的环境变量完成认证。
# =====================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${GREEN}  $*${NC}"; }
warn() { echo -e "${YELLOW}  [WARN] $*${NC}"; }
err()  { echo -e "${RED}[ERROR] $*${NC}" >&2; }
die()  { err "$*"; exit 1; }

usage() {
    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

# ---------------------------------------------------------------------
# 环境与配置
# ---------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
fi

[[ "${1:-}" == "--help" || "${1:-}" == "-h" ]] && usage
if [[ "${1:-}" == "--full" ]]; then
    warn "--full 已废弃：v2 备份默认即为全量（PG+CH+对象存储）。"
fi
[[ $# -gt 1 ]] && die "未知参数: $*"

# 定位 compose 项目（与 upgrade.sh 相同的安装布局探测）
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
COMPOSE_BIN=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")

BAK_BASE_DIR="${BAK_BASE_DIR:-/opt/soymutdb/backups}"
BACKUP_S3="${BACKUP_S3:-}"
BACKUP_S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-}"
BACKUP_S3_ACCESS_KEY="${BACKUP_S3_ACCESS_KEY:-}"
BACKUP_S3_SECRET_KEY="${BACKUP_S3_SECRET_KEY:-}"
BAK_S3_BUCKETS="${BAK_S3_BUCKETS:-genomic-data user-tracks blast-dbs exports gwas}"
BAK_RETAIN_DAILY="${BAK_RETAIN_DAILY:-7}"
BAK_RETAIN_WEEKLY="${BAK_RETAIN_WEEKLY:-4}"
BAK_RETAIN_MONTHLY="${BAK_RETAIN_MONTHLY:-6}"
BAK_S3_HASH_OBJECTS="${BAK_S3_HASH_OBJECTS:-1}"

# 校验数值配置
for v in BAK_RETAIN_DAILY BAK_RETAIN_WEEKLY BAK_RETAIN_MONTHLY; do
    [[ "${!v}" =~ ^[0-9]+$ ]] || die "${v} must be a positive integer (got '${!v}')"
done

# 连接目标（默认本机 compose 栈）
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"
CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
CH_USER="${CLICKHOUSE_USER:-soymutdb}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || echo unknown)"
STAGING_DIR="${BAK_BASE_DIR}/.staging/${TIMESTAMP}"
ARCHIVE_NAME=""   # 填充为 <TS>-<sha8>.tar.gz

mkdir -p "${BAK_BASE_DIR}" "${STAGING_DIR}"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Backup (v2 unified)${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Timestamp:     ${TIMESTAMP}"
echo "  Host:          ${HOSTNAME_SHORT}"
echo "  Staging:       ${STAGING_DIR}"
echo "  S3 buckets:    ${BAK_S3_BUCKETS}"
echo "  Offsite:       ${BACKUP_S3:-none}"
echo ""

# ---------------------------------------------------------------------
# 工具 helpers
# ---------------------------------------------------------------------

# compose exec（容器内命令利用容器环境认证，不在 CLI 传密钥）
compose_exec() { # service cmd...
    local svc="$1"; shift
    "${COMPOSE_BIN[@]}" exec -T "${svc}" "$@"
}

# PG 查询：优先容器内 psql；本机直连（隔离演练）时用 host psql
pg_query() { # sql
    local sql="$1"
    if [[ "${PG_HOST}" == "localhost" || "${PG_HOST}" == "127.0.0.1" ]]; then
        compose_exec postgres psql -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    fi
}

# CH 查询：优先容器内 clickhouse-client（复用容器 CLICKHOUSE_PASSWORD 环境）
ch_query() { # sql
    local sql="$1"
    if [[ "${CH_HOST}" == "localhost" || "${CH_HOST}" == "127.0.0.1" ]]; then
        compose_exec clickhouse clickhouse-client --user "${CH_USER}" -q "${sql}"
    else
        curl -sf -u "${CH_USER}:${CH_PASSWORD:-soymutdb_dev_password}" \
            "http://${CH_HOST}:${CH_PORT}/" --data-binary "${sql}"
    fi
}

# mc 客户端：优先 host mc；否则用 compose 已有的 minio/mc 镜像（一次性容器）
MC_CFG_DIR="${BAK_BASE_DIR}/.mc"
mc_run() { # args...
    if command -v mc &>/dev/null; then
        mc --config-dir "${MC_CFG_DIR}" "$@"
    else
        # 容器内 mc 需要挂载配置目录与本地备份目录（本地路径保持一致）
        docker run --rm --network host \
            -v "${MC_CFG_DIR}:/root/.mc" \
            -v "${BAK_BASE_DIR}:${BAK_BASE_DIR}" \
            minio/mc:RELEASE.2024-01-01T00-00-00Z \
            --config-dir /root/.mc "$@"
    fi
}

# mc 别名（静默，凭据不落日志）
mc_alias() { # alias endpoint key secret
    mc_run alias set "$1" "$2" "$3" "$4" >/dev/null 2>&1 || true
}

sha256_of() { # file -> sha256 hex
    sha256sum "$1" | awk '{print $1}'
}

# JSON 字符串转义（路径/名称可能含引号或反斜杠）
json_escape() {
    local s="$1" out=""
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "${s}"
}

# ---------------------------------------------------------------------
# [1] PostgreSQL：行数快照 + pg_dump
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/3] PostgreSQL backup...${NC}"
PG_ROWS_TSV="${STAGING_DIR}/pg_rows.tsv"
: > "${PG_ROWS_TSV}"
# 行数快照（verify-restore.sh 恢复后逐表比对；先于 dump 记录）
while IFS= read -r tbl; do
    [[ -n "${tbl}" ]] || continue
    cnt="$(pg_query "SELECT count(*) FROM ${tbl}" 2>/dev/null || echo ERROR)"
    printf '%s\t%s\n' "${tbl}" "${cnt}" >> "${PG_ROWS_TSV}"
done < <(pg_query "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1" 2>/dev/null || true)
PG_TABLES_SNAPSHOTED="$(wc -l < "${PG_ROWS_TSV}")"
info "Row-count snapshot: ${PG_TABLES_SNAPSHOTED} tables -> $(basename "${PG_ROWS_TSV}")"

PG_DUMP_FILE="${STAGING_DIR}/postgres.dump"
if [[ "${PG_HOST}" == "localhost" || "${PG_HOST}" == "127.0.0.1" ]]; then
    compose_exec postgres pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc > "${PG_DUMP_FILE}"
else
    PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
        pg_dump -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
        -Fc -f "${PG_DUMP_FILE}"
fi
PG_SIZE="$(stat -c%s "${PG_DUMP_FILE}")"
PG_SHA="$(sha256_of "${PG_DUMP_FILE}")"
info "pg_dump: $(du -sh "${PG_DUMP_FILE}" | cut -f1)  sha256=${PG_SHA:0:16}..."

# ---------------------------------------------------------------------
# [2] ClickHouse：BACKUP DATABASE（含事实表），产物复制进 tar
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/3] ClickHouse backup...${NC}"
CH_ZIP_NAME="soymutdb_${TIMESTAMP}.zip"
CH_BACKUP_STATUS="ok"
if docker info &>/dev/null || "${COMPOSE_BIN[@]}" ps -q clickhouse >/dev/null 2>&1; then
    # BACKUP 产物落在容器内默认 Disk('backups') = /var/lib/clickhouse/backups/
    ch_query "BACKUP DATABASE soymutdb TO Disk('backups', '${CH_ZIP_NAME}')" >/dev/null \
        || CH_BACKUP_STATUS="backup-failed"
    if [[ "${CH_BACKUP_STATUS}" == "ok" ]] && \
       compose_exec clickhouse test -f "/var/lib/clickhouse/backups/${CH_ZIP_NAME}" >/dev/null 2>&1; then
        # 关键修复：把 CH 本地 disk 上的备份产物实际复制进最终 tar
        "${COMPOSE_BIN[@]}" cp "clickhouse:/var/lib/clickhouse/backups/${CH_ZIP_NAME}" "${STAGING_DIR}/clickhouse_soymutdb.zip"
        compose_exec clickhouse rm -f "/var/lib/clickhouse/backups/${CH_ZIP_NAME}" >/dev/null 2>&1 || true
        CH_SIZE="$(stat -c%s "${STAGING_DIR}/clickhouse_soymutdb.zip")"
        CH_SHA="$(sha256_of "${STAGING_DIR}/clickhouse_soymutdb.zip")"
        info "BACKUP DATABASE ok: $(du -sh "${STAGING_DIR}/clickhouse_soymutdb.zip" | cut -f1)  sha256=${CH_SHA:0:16}..."
    else
        CH_BACKUP_STATUS="backup-failed"
        warn "BACKUP DATABASE 失败或产物缺失——回退为维度表 TSV 导出（事实表将缺失，restore 会显式失败）"
    fi
else
    CH_BACKUP_STATUS="docker-unavailable"
    warn "docker/compose 不可用，无法访问 ClickHouse 备份盘；回退为维度表 TSV 导出。"
fi

# 每表行数/分区数快照（verify-restore.sh 恢复后比对）
CH_ROWS_TSV="${STAGING_DIR}/clickhouse_rows.tsv"
: > "${CH_ROWS_TSV}"
if [[ "${CH_BACKUP_STATUS}" == "ok" ]]; then
    while IFS= read -r tname; do
        [[ -n "${tname}" ]] || continue
        rows="$(ch_query "SELECT count() FROM soymutdb.\`${tname}\`" 2>/dev/null || echo ERROR)"
        parts="$(ch_query "SELECT count(DISTINCT partition) FROM system.parts WHERE database='soymutdb' AND table='${tname}' AND active=1" 2>/dev/null || echo ERROR)"
        printf '%s\t%s\t%s\n' "${tname}" "${rows}" "${parts}" >> "${CH_ROWS_TSV}"
    done < <(ch_query "SELECT name FROM system.tables WHERE database='soymutdb' AND name NOT LIKE '.inner%' ORDER BY name" 2>/dev/null || true)
fi
CH_TABLES_SNAPSHOTED="$(wc -l < "${CH_ROWS_TSV}")"
info "CH row/partition snapshot: ${CH_TABLES_SNAPSHOTED} tables"

# 回退路径：维度表 TSV 导出（与旧版兼容，restore 失败时用于人工救援）
for table in release_dim gene_dim mutant_line_dim consequence_dim; do
    ch_query "SELECT * FROM soymutdb.${table} FORMAT TabSeparated" \
        > "${STAGING_DIR}/clickhouse_${table}.tsv" 2>/dev/null || true
done

# ---------------------------------------------------------------------
# [3] MinIO/S3：对象数据 + bucket policy
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/3] MinIO/S3 backup...${NC}"
S3_MANIFEST_TSV="${STAGING_DIR}/s3_manifest.tsv"
: > "${S3_MANIFEST_TSV}"
printf '%s\n' ${BAK_S3_BUCKETS} > "${STAGING_DIR}/s3_buckets.txt"
S3_STATUS="ok"
S3_OBJECT_COUNT=0
S3_TOTAL_BYTES=0
S3_SKIPPED_BUCKETS=""

if mc_run alias set s3src "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null 2>&1; then
    for bucket in ${BAK_S3_BUCKETS}; do
        LOCAL_BUCKET_DIR="${STAGING_DIR}/s3_data/${bucket}"
        if mc_run mirror --overwrite --remove "s3src/${bucket}" "${LOCAL_BUCKET_DIR}" >/dev/null 2>&1; then
            # 每对象 SHA-256 清单（restore/verify 按此校验 checksum）
            while IFS= read -r -d '' f; do
                rel="${f#${LOCAL_BUCKET_DIR}/}"
                size="$(stat -c%s "${f}")"
                if [[ "${BAK_S3_HASH_OBJECTS}" == "1" ]]; then
                    hash="$(sha256_of "${f}")"
                else
                    hash=""
                fi
                printf '%s\t%s\t%s\t%s\n' "${bucket}" "${rel}" "${size}" "${hash}" >> "${S3_MANIFEST_TSV}"
                S3_OBJECT_COUNT=$((S3_OBJECT_COUNT + 1))
                S3_TOTAL_BYTES=$((S3_TOTAL_BYTES + size))
            done < <(find "${LOCAL_BUCKET_DIR}" -type f -print0)
        else
            S3_SKIPPED_BUCKETS="${S3_SKIPPED_BUCKETS} ${bucket}"
        fi
        # bucket policy 一并保存
        mc_run policy get "s3src/${bucket}" > "${STAGING_DIR}/s3_policy_${bucket}.json" 2>/dev/null || true
    done
    if [[ -n "${S3_SKIPPED_BUCKETS}" ]]; then
        S3_STATUS="partial"
        warn "以下 bucket 镜像失败（已跳过）:${S3_SKIPPED_BUCKETS}"
        [[ " ${S3_SKIPPED_BUCKETS} " != *" gwas "* ]] || die "gwas bucket 镜像失败，拒绝生成不完整备份"
    fi
    grep -qx 'gwas' "${STAGING_DIR}/s3_buckets.txt" || die "完整备份必须包含 gwas bucket"
    info "Objects: ${S3_OBJECT_COUNT}, bytes: ${S3_TOTAL_BYTES}, manifest: $(basename "${S3_MANIFEST_TSV}")"
else
    S3_STATUS="skipped"
    die "mc 不可用，对象数据（包括 gwas）未备份，拒绝生成不完整备份"
fi

# ---------------------------------------------------------------------
# [4] manifest（backup_id = 时间戳 + 组件哈希短 sha）
# ---------------------------------------------------------------------
COMPONENT_HASH="$(printf '%s%s%s' "${PG_SHA:-}" "${CH_SHA:-}" "${S3_TOTAL_BYTES}${S3_OBJECT_COUNT}" | sha256sum | cut -c1-8)"
BACKUP_ID="${TIMESTAMP}-${COMPONENT_HASH}"
ARCHIVE_NAME="${BACKUP_ID}.tar.gz"
MANIFEST_FILE="${STAGING_DIR}/manifest.json"

{
    printf '{\n'
    printf '  "format_version": 1,\n'
    printf '  "backup_id": "%s",\n' "${BACKUP_ID}"
    printf '  "created_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "host": "%s",\n' "$(json_escape "${HOSTNAME_SHORT}")"
    printf '  "tool": "deploy/scripts/backup.sh v2",\n'
    printf '  "components": {\n'
    printf '    "postgres": {\n'
    printf '      "status": "ok",\n'
    printf '      "file": "postgres.dump",\n'
    printf '      "size": %s,\n' "${PG_SIZE:-0}"
    printf '      "sha256": "%s",\n' "${PG_SHA:-}"
    printf '      "row_counts_file": "pg_rows.tsv",\n'
    printf '      "tables": %s\n' "${PG_TABLES_SNAPSHOTED:-0}"
    printf '    },\n'
    printf '    "clickhouse": {\n'
    printf '      "status": "%s",\n' "${CH_BACKUP_STATUS}"
    printf '      "file": "clickhouse_soymutdb.zip",\n'
    printf '      "size": %s,\n' "${CH_SIZE:-0}"
    printf '      "sha256": "%s",\n' "${CH_SHA:-}"
    printf '      "row_counts_file": "clickhouse_rows.tsv",\n'
    printf '      "tables": %s\n' "${CH_TABLES_SNAPSHOTED:-0}"
    printf '    },\n'
    printf '    "s3": {\n'
    printf '      "status": "%s",\n' "${S3_STATUS}"
    printf '      "manifest_file": "s3_manifest.tsv",\n'
    printf '      "object_count": %s,\n' "${S3_OBJECT_COUNT}"
    printf '      "total_bytes": %s\n' "${S3_TOTAL_BYTES}"
    printf '    },\n'
    printf '    "redis": {\n'
    printf '      "status": "not-backed-up",\n'
    printf '      "note": "cache & broker state are rebuildable; authoritative state lives in postgres"\n'
    printf '    }\n'
    printf '  }\n'
    printf '}\n'
} > "${MANIFEST_FILE}"
info "manifest: $(basename "${MANIFEST_FILE}")  backup_id=${BACKUP_ID}"

# ---------------------------------------------------------------------
# [5] 打包 + SHA-256 校验文件
# ---------------------------------------------------------------------
echo -e "${CYAN}Packaging archive...${NC}"
mkdir -p "${BAK_BASE_DIR}"
cp "${MANIFEST_FILE}" "${BAK_BASE_DIR}/${BACKUP_ID}.manifest.json"
# 以 staging 目录名为顶层目录打包（restore 按单一顶层目录解包）
tar -C "$(dirname "${STAGING_DIR}")" -czf "${BAK_BASE_DIR}/${ARCHIVE_NAME}" "$(basename "${STAGING_DIR}")"
rm -rf "${STAGING_DIR}"

ARCHIVE_SHA="$(sha256_of "${BAK_BASE_DIR}/${ARCHIVE_NAME}")"
printf '%s  %s\n' "${ARCHIVE_SHA}" "${ARCHIVE_NAME}" > "${BAK_BASE_DIR}/${ARCHIVE_NAME}.sha256"

BACKUP_SIZE="$(du -sh "${BAK_BASE_DIR}/${ARCHIVE_NAME}" | cut -f1)"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Backup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo "  Archive:  ${BAK_BASE_DIR}/${ARCHIVE_NAME}"
echo "  Size:     ${BACKUP_SIZE}"
echo "  SHA-256:  ${ARCHIVE_SHA}"
echo "  Manifest: ${BAK_BASE_DIR}/${BACKUP_ID}.manifest.json"
echo ""

# ---------------------------------------------------------------------
# [6] 上传到独立备份位置（可选 BACKUP_S3）
# ---------------------------------------------------------------------
if [[ -n "${BACKUP_S3}" ]]; then
    echo -e "${CYAN}Uploading to offsite backup: ${BACKUP_S3}...${NC}"
    S3_ALIAS="${BACKUP_S3%%/*}"
    S3_TARGET="${BACKUP_S3#*/}"   # bucket/prefix
    if [[ -n "${BACKUP_S3_ENDPOINT}" ]]; then
        mc_run alias set "${S3_ALIAS}" "${BACKUP_S3_ENDPOINT}" \
            "${BACKUP_S3_ACCESS_KEY}" "${BACKUP_S3_SECRET_KEY}" >/dev/null 2>&1 \
            || warn "无法配置异地备份 alias ${S3_ALIAS}（已存在的 alias 会继续使用）"
    fi
    if mc_run cp "${BAK_BASE_DIR}/${ARCHIVE_NAME}" "${S3_ALIAS}/${S3_TARGET}/" >/dev/null 2>&1 \
       && mc_run cp "${BAK_BASE_DIR}/${ARCHIVE_NAME}.sha256" "${S3_ALIAS}/${S3_TARGET}/" >/dev/null 2>&1 \
       && mc_run cp "${BAK_BASE_DIR}/${BACKUP_ID}.manifest.json" "${S3_ALIAS}/${S3_TARGET}/" >/dev/null 2>&1; then
        info "Uploaded archive + sha256 + manifest to ${BACKUP_S3}/"
    else
        warn "异地上传失败——本地备份仍然有效，请检查 BACKUP_S3 配置。"
    fi
fi

# ---------------------------------------------------------------------
# [7] 保留策略（滚动删除，默认 7 日备 + 4 周备 + 6 月备）
# ---------------------------------------------------------------------
prune_local() {
    local dir="$1"
    local now_epoch keep_days i
    now_epoch="$(date +%s)"
    keep_days=$(( (BAK_RETAIN_DAILY - 1) * 86400 ))

    local -a names=()
    local f
    for f in "${dir}"/*.tar.gz; do
        [[ -e "${f}" ]] || continue
        names+=("$(basename "${f}")")
    done
    [[ ${#names[@]} -gt 0 ]] || return 0

    local -A keep=()
    local n t d wk mo newest
    for n in "${names[@]}"; do
        t="${n%.tar.gz}"
        t="${t%%-*}"
        [[ "${t}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || { warn "未识别的备份文件名，跳过保留判定: ${n}"; continue; }
        d="${t:0:8}"
        if [[ "$(date -d "${d}" +%s)" -ge $(( now_epoch - keep_days )) ]]; then
            keep["${n}"]="daily"
        fi
    done
    # 周备：最近 N 个 ISO 周内，每周保留最新一份
    for ((i = 0; i < BAK_RETAIN_WEEKLY; i++)); do
        wk="$(date -d "now - ${i} weeks" +%G-%V)"
        newest=""
        for n in "${names[@]}"; do
            t="${n%.tar.gz}"
            t="${t%%-*}"
            [[ "${t}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || continue
            d="${t:0:8}"
            [[ "$(date -d "${d}" +%G-%V)" == "${wk}" ]] || continue
            if [[ -z "${newest}" || "${t}" > "${newest%%-*}" ]]; then newest="${n}"; fi
        done
        [[ -n "${newest}" ]] && keep["${newest}"]="weekly"
    done
    # 月备：最近 N 个自然月内，每月保留最新一份
    for ((i = 0; i < BAK_RETAIN_MONTHLY; i++)); do
        mo="$(date -d "now - ${i} months" +%Y%m)"
        newest=""
        for n in "${names[@]}"; do
            t="${n%.tar.gz}"
            t="${t%%-*}"
            [[ "${t}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || continue
            d="${t:0:8}"
            [[ "${d:0:6}" == "${mo}" ]] || continue
            if [[ -z "${newest}" || "${t}" > "${newest%%-*}" ]]; then newest="${n}"; fi
        done
        [[ -n "${newest}" ]] && keep["${newest}"]="monthly"
    done

    for n in "${names[@]}"; do
        if [[ -n "${keep[${n}]:-}" ]]; then
            info "retain ${n} (${keep[${n}]})"
        else
            info "prune  ${n}"
            rm -f "${dir}/${n}" "${dir}/${n}.sha256" "${dir}/${n%.tar.gz}.manifest.json"
        fi
    done
}

echo -e "${CYAN}Applying retention (daily=${BAK_RETAIN_DAILY} weekly=${BAK_RETAIN_WEEKLY} monthly=${BAK_RETAIN_MONTHLY})...${NC}"
prune_local "${BAK_BASE_DIR}"

# 异地保留：与本地保留集保持一致（删除远端多余的归档）
if [[ -n "${BACKUP_S3}" && -n "${S3_ALIAS:-}" ]]; then
    KEEP_NAMES=""
    for f in "${BAK_BASE_DIR}"/*.tar.gz; do
        [[ -e "${f}" ]] || continue
        KEEP_NAMES="${KEEP_NAMES} $(basename "${f}")"
    done
    while IFS= read -r key; do
        [[ -n "${key}" ]] || continue
        name="$(basename "${key}")"
        if [[ "${name}" == *.tar.gz && " ${KEEP_NAMES} " != *" ${name} "* ]]; then
            info "prune remote ${key}"
            mc_run rm --force "${S3_ALIAS}/${S3_TARGET}/${name}" >/dev/null 2>&1 || true
        fi
    done < <(mc_run ls --recursive --json "${S3_ALIAS}/${S3_TARGET}/" 2>/dev/null | sed -n 's/.*"key": *"\([^"]*\)".*/\1/p' || true)
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Backup retention complete${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "  Next: bash deploy/scripts/restore.sh --target <name> ${BAK_BASE_DIR}/${ARCHIVE_NAME}"
echo "  Verify: bash deploy/scripts/verify-restore.sh ${BAK_BASE_DIR}/${ARCHIVE_NAME}"
echo ""

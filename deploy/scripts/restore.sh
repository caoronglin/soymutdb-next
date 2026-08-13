#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Restore Script (v2)
# =====================================================================
# 从 v2 备份归档（含 manifest.json）恢复数据面：
#   顺序：PostgreSQL -> ClickHouse（含事实表 variant_facts、维度表、
#         物化视图，经 BACKUP/RESTORE DATABASE 完整恢复）-> S3/对象存储
#         （按 manifest 校验每对象 SHA-256）。
#   Job/Outbox 状态：权威记录在 PostgreSQL 中，随 PG 恢复一并还原；
#         Redis 缓存与 Celery broker 不恢复（由应用在 PG 恢复后重建，
#         见 backup.sh 头部说明）。
#
# 安全门槛（防误操作）：
#   - 默认只允许恢复到“隔离目标”：环境变量 TARGET 非空（如 TARGET=drill）
#     或显式 --target <name> 才执行；
#   - 生产恢复必须显式 `--target prod|production` 并二次确认（输入 restore）；
#   - 隔离演练（推荐至少每月一次，假数据环境）：
#       1) 在隔离主机/独立 compose 项目启动同版本空栈
#       2) POSTGRES_HOST/S3_ENDPOINT/CLICKHOUSE_HOST 等指向演练栈，
#          TARGET=drill 后执行本脚本
#       3) bash deploy/scripts/verify-restore.sh <backup>.tar.gz
#          全部 PASS 且退出码 0 才视为演练成功
#
# Usage:
#   bash deploy/scripts/restore.sh <backup-file.tar.gz>
#   bash deploy/scripts/restore.sh --target drill <backup-file.tar.gz>
#   bash deploy/scripts/restore.sh --target prod <backup-file.tar.gz>   # 生产
#
# 环境变量：
#   TARGET                    目标标识（隔离目标名；缺省拒绝执行）
#   SOYMUTDB_INSTALL_DIR      compose 项目目录（缺省自动探测）
#   POSTGRES_HOST/POSTGRES_PORT/POSTGRES_USER/POSTGRES_DB/POSTGRES_PASSWORD
#   CLICKHOUSE_HOST/CLICKHOUSE_PORT/CLICKHOUSE_USER/CLICKHOUSE_PASSWORD
#   S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY
#   BAK_BASE_DIR              与 backup.sh 一致（mc 配置目录所在，默认
#                             /opt/soymutdb/backups）
#
# 安全：不在命令行/日志打印密钥；容器内命令复用容器环境认证。
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

# ---------------------------------------------------------------------
# 参数与目标门槛
# ---------------------------------------------------------------------
TARGET_ARG=""
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            [[ $# -ge 2 ]] || die "--target requires a value"
            TARGET_ARG="$2"; shift 2 ;;
        --target=*)
            TARGET_ARG="${1#*=}"; shift ;;
        --help|-h)
            sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)
            die "unknown option: $1" ;;
        *)
            [[ -n "${BACKUP_FILE}" ]] && die "too many arguments: $1"
            BACKUP_FILE="$1"; shift ;;
    esac
done

[[ -n "${BACKUP_FILE}" ]] || die "Usage: bash deploy/scripts/restore.sh [--target <name>] <backup-file.tar.gz>"
[[ -f "${BACKUP_FILE}" ]] || die "Backup file not found: ${BACKUP_FILE}"

# 目标解析：--target 优先，其次环境变量 TARGET；都为空则拒绝
TARGET="${TARGET_ARG:-${TARGET:-}}"
if [[ -z "${TARGET}" ]]; then
    die "未指定恢复目标。默认只允许恢复到隔离目标：\n" \
        "  演练: TARGET=drill bash deploy/scripts/restore.sh <backup>.tar.gz\n" \
        "  生产: bash deploy/scripts/restore.sh --target prod <backup>.tar.gz (需二次确认)"
fi

IS_PROD=0
case "${TARGET}" in
    prod|production) IS_PROD=1 ;;
esac

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

INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
COMPOSE_BIN=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")

BAK_BASE_DIR="${BAK_BASE_DIR:-/opt/soymutdb/backups}"
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

RESTORE_DIR="$(mktemp -d)"
trap 'rm -rf "${RESTORE_DIR}"' EXIT

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Restore (v2)${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Backup: ${BACKUP_FILE}"
echo "  Target: ${TARGET} $([ "${IS_PROD}" == "1" ] && echo '(PRODUCTION)' || echo '(isolated)')"
echo "  Temp:   ${RESTORE_DIR}"
echo ""

# ---------------------------------------------------------------------
# 二次确认
# ---------------------------------------------------------------------
if [[ "${IS_PROD}" == "1" ]]; then
    echo -e "${RED}WARNING: 生产环境恢复，将 OVERWRITE 现有数据（PG + ClickHouse + S3）！${NC}"
    read -r -p "Type 'restore' to confirm production restore: " CONFIRM
    [[ "${CONFIRM}" == "restore" ]] || die "Aborted (confirmation mismatch)."
else
    read -r -p "将恢复到隔离目标 '${TARGET}'（覆盖该目标上现有数据）。确认? [y/N]: " CONFIRM
    [[ "${CONFIRM}" == "y" || "${CONFIRM}" == "Y" ]] || die "Aborted."
fi

# ---------------------------------------------------------------------
# 校验归档：sidecar SHA-256（存在则必过）+ 解包
# ---------------------------------------------------------------------
if [[ -f "${BACKUP_FILE}.sha256" ]]; then
    echo -e "${CYAN}Verifying archive SHA-256...${NC}"
    (cd "$(dirname "${BACKUP_FILE}")" && sha256sum -c "$(basename "${BACKUP_FILE}").sha256") \
        || die "Archive checksum mismatch - refusing to restore a corrupted backup."
    info "Archive checksum OK."
fi

echo -e "${CYAN}Extracting backup...${NC}"
tar -xzf "${BACKUP_FILE}" -C "${RESTORE_DIR}"
BACKUP_SUBDIR=""
for cand in "${RESTORE_DIR}"/*; do
    [[ -d "${cand}" ]] && BACKUP_SUBDIR="$(basename "${cand}")" && break
done
[[ -n "${BACKUP_SUBDIR}" ]] || die "Backup archive has no content directory."
RESTORE_SRC="${RESTORE_DIR}/${BACKUP_SUBDIR}"
info "Extracted to ${RESTORE_SRC}"

# manifest 是 v2 恢复的前提（旧版归档缺事实表/S3 对象，不完整，拒绝恢复）
MANIFEST="${RESTORE_SRC}/manifest.json"
[[ -f "${MANIFEST}" ]] || die "manifest.json not found in backup - 该归档不是 v2 完整备份（缺少事实表/S3 对象恢复能力），请重新创建备份。"
FMT_VER="$(sed -n 's/.*"format_version": *\([0-9]*\).*/\1/p' "${MANIFEST}" | head -1)"
[[ "${FMT_VER}" == "1" ]] || die "Unsupported manifest format_version: ${FMT_VER:-?}"
BACKUP_ID="$(sed -n 's/.*"backup_id": *"\([^"]*\)".*/\1/p' "${MANIFEST}" | head -1)"
info "Manifest OK (backup_id: ${BACKUP_ID:-unknown})"

# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------
compose_exec() {
    local svc="$1"; shift
    "${COMPOSE_BIN[@]}" exec -T "${svc}" "$@"
}
pg_query() {
    local sql="$1"
    if [[ "${PG_HOST}" == "localhost" || "${PG_HOST}" == "127.0.0.1" ]]; then
        compose_exec postgres psql -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    fi
}
ch_query() {
    local sql="$1"
    if [[ "${CH_HOST}" == "localhost" || "${CH_HOST}" == "127.0.0.1" ]]; then
        compose_exec clickhouse clickhouse-client --user "${CH_USER}" -q "${sql}"
    else
        curl -sf -u "${CH_USER}:${CH_PASSWORD:-soymutdb_dev_password}" \
            "http://${CH_HOST}:${CH_PORT}/" --data-binary "${sql}"
    fi
}
MC_CFG_DIR="${BAK_BASE_DIR}/.mc"
mc_run() {
    if command -v mc &>/dev/null; then
        mc --config-dir "${MC_CFG_DIR}" "$@"
    else
        docker run --rm --network host \
            -v "${MC_CFG_DIR}:/root/.mc" \
            -v "${BAK_BASE_DIR}:${BAK_BASE_DIR}" \
            minio/mc:RELEASE.2024-01-01T00-00-00Z \
            --config-dir /root/.mc "$@"
    fi
}

RESTORE_SKIPPED=""

# ---------------------------------------------------------------------
# 1. PostgreSQL（--clean 重建；Job/Outbox 表随库恢复）
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/3] Restoring PostgreSQL...${NC}"
if [[ -f "${RESTORE_SRC}/postgres.dump" ]]; then
    if [[ "${PG_HOST}" == "localhost" || "${PG_HOST}" == "127.0.0.1" ]]; then
        "${COMPOSE_BIN[@]}" cp "${RESTORE_SRC}/postgres.dump" "postgres:/tmp/soymutdb_restore.dump"
        compose_exec postgres pg_restore -U "${PG_USER}" -d "${PG_DB}" \
            --clean --if-exists --no-owner --no-privileges /tmp/soymutdb_restore.dump \
            || die "PostgreSQL restore failed (pg_restore)."
        compose_exec postgres rm -f /tmp/soymutdb_restore.dump
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            pg_restore -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
            --clean --if-exists --no-owner --no-privileges "${RESTORE_SRC}/postgres.dump" \
            || die "PostgreSQL restore failed (pg_restore)."
    fi
    info "PostgreSQL restore complete."
else
    warn "postgres.dump 缺失，跳过 PG 恢复。"
    RESTORE_SKIPPED="${RESTORE_SKIPPED} postgres"
fi

# ---------------------------------------------------------------------
# 2. ClickHouse：BACKUP DATABASE 产物整体恢复（含事实表与物化视图）
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/3] Restoring ClickHouse...${NC}"
CH_ZIP="${RESTORE_SRC}/clickhouse_soymutdb.zip"
if [[ -f "${CH_ZIP}" ]]; then
    if [[ "${CH_HOST}" != "localhost" && "${CH_HOST}" != "127.0.0.1" ]]; then
        warn "远程 CH（${CH_HOST}）恢复需手工放置 zip；跳过 ZIP 恢复。"
        RESTORE_SKIPPED="${RESTORE_SKIPPED} clickhouse"
    else
        # 将产物放回容器备份盘
        "${COMPOSE_BIN[@]}" cp "${CH_ZIP}" "clickhouse:/var/lib/clickhouse/backups/soymutdb_restore.zip"
        ch_query "CREATE DATABASE IF NOT EXISTS soymutdb" >/dev/null
        # 清空现有表（含物化视图；.inner 表随 MV 自动删除，跳过以免误删）
        while IFS= read -r tname; do
            [[ -n "${tname}" ]] || continue
            ch_query "DROP TABLE IF EXISTS soymutdb.\`${tname}\` SYNC" >/dev/null || true
        done < <(ch_query "SELECT name FROM system.tables WHERE database='soymutdb' AND name NOT LIKE '.inner%' ORDER BY name" 2>/dev/null || true)
        # RESTORE DATABASE 重建全部表 + 数据 + 物化视图（含事实表）
        ch_query "RESTORE DATABASE soymutdb FROM Disk('backups', 'soymutdb_restore.zip')" >/dev/null \
            || die "ClickHouse RESTORE failed."
        compose_exec clickhouse rm -f /var/lib/clickhouse/backups/soymutdb_restore.zip >/dev/null 2>&1 || true
        info "ClickHouse restore complete (database-level, incl. fact tables)."
    fi
else
    warn "clickhouse_soymutdb.zip 缺失——尝试维度表 TSV 回退恢复（事实表将缺失，请用 verify-restore.sh 确认）。"
    for table in release_dim gene_dim mutant_line_dim consequence_dim; do
        TSV_FILE="${RESTORE_SRC}/clickhouse_${table}.tsv"
        if [[ -f "${TSV_FILE}" ]]; then
            ch_query "TRUNCATE TABLE soymutdb.${table}" >/dev/null 2>&1 || \
                warn "  ${table} TRUNCATE 失败（表可能不存在，尝试直接插入）。"
            ch_query "INSERT INTO soymutdb.${table} FORMAT TabSeparated" < "${TSV_FILE}" >/dev/null 2>&1 || \
                warn "  ${table} TSV 恢复失败（请人工介入）。"
        fi
    done
    RESTORE_SKIPPED="${RESTORE_SKIPPED} clickhouse-facts"
fi

# ---------------------------------------------------------------------
# 3. MinIO/S3：对象数据（mc mirror 精确恢复）+ 按 manifest 校验 checksum
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/3] Restoring MinIO/S3 objects...${NC}"
S3_MANIFEST="${RESTORE_SRC}/s3_manifest.tsv"
S3_DATA_DIR="${RESTORE_SRC}/s3_data"
if [[ -d "${S3_DATA_DIR}" && -f "${S3_MANIFEST}" ]]; then
    [[ -f "${RESTORE_SRC}/s3_buckets.txt" ]] || die "备份缺少 S3 bucket manifest"
    grep -qx 'gwas' "${RESTORE_SRC}/s3_buckets.txt" || die "备份缺少 gwas bucket manifest"
    if mc_run alias set s3dst "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null 2>&1; then
        for bucket in $({ cut -f1 "${S3_MANIFEST}"; cat "${RESTORE_SRC}/s3_buckets.txt"; } | sort -u); do
            SRC_DIR="${S3_DATA_DIR}/${bucket}"
            [[ -d "${SRC_DIR}" ]] || continue
            # --remove: 删除远端多余对象，得到与备份完全一致的状态
            mc_run mirror --overwrite --remove "${SRC_DIR}" "s3dst/${bucket}" >/dev/null 2>&1 \
                || warn "  bucket ${bucket} 镜像恢复失败。"
            # bucket policy 恢复
            POLICY_FILE="${RESTORE_SRC}/s3_policy_${bucket}.json"
            if [[ -f "${POLICY_FILE}" && -s "${POLICY_FILE}" ]]; then
                mc_run policy set "$(cat "${POLICY_FILE}")" "s3dst/${bucket}" >/dev/null 2>&1 || true
            fi
            info "  ${bucket}: mirrored."
        done
        # 按 manifest 校验每对象 SHA-256（下载比对）
        CHK_TMP="$(mktemp -d)"
        MISMATCH=0
        CHECKED=0
        while IFS=$'\t' read -r bucket rel size hash; do
            [[ -n "${rel}" ]] || continue
            if [[ -n "${hash}" ]]; then
                mc_run cp "s3dst/${bucket}/${rel}" "${CHK_TMP}/obj" >/dev/null 2>&1 || { warn "  对象缺失: ${bucket}/${rel}"; MISMATCH=$((MISMATCH + 1)); continue; }
                got="$(sha256sum "${CHK_TMP}/obj" | awk '{print $1}')"
                if [[ "${got}" != "${hash}" ]]; then
                    warn "  checksum mismatch: ${bucket}/${rel}"
                    MISMATCH=$((MISMATCH + 1))
                fi
                CHECKED=$((CHECKED + 1))
                rm -f "${CHK_TMP}/obj"
            fi
        done < "${S3_MANIFEST}"
        rm -rf "${CHK_TMP}"
        if [[ "${MISMATCH}" -gt 0 ]]; then
            warn "S3 校验发现 ${MISMATCH} 个对象不一致（已检查 ${CHECKED}）。"
        else
            info "S3 checksum verified: ${CHECKED} objects OK."
        fi
    else
        warn "mc 不可用，S3 对象未恢复。"
        RESTORE_SKIPPED="${RESTORE_SKIPPED} s3"
    fi
else
    warn "备份中无 S3 数据（s3_data/s3_manifest.tsv），跳过。"
    RESTORE_SKIPPED="${RESTORE_SKIPPED} s3"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Restore Complete (target: ${TARGET})${NC}"
echo -e "${GREEN}========================================${NC}"
if [[ -n "${RESTORE_SKIPPED}" ]]; then
    echo -e "${YELLOW}  跳过/未完整恢复的组件:${RESTORE_SKIPPED}${NC}"
fi
echo ""
echo "Next steps:"
echo "  1. 重启/验证服务（生产: sudo systemctl restart soymutdb.target）"
echo "  2. 运行恢复验证:"
echo "       bash deploy/scripts/verify-restore.sh ${BACKUP_FILE}"
echo "     全部 PASS 且退出码 0 才代表恢复成功"
echo ""

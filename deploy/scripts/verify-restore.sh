#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Restore Verification Script (v2)
# =====================================================================
# 恢复后比对（与备份时记录到 manifest 的快照逐项核对）：
#   [1] 归档自身 SHA-256（存在 <file>.sha256 时必过）
#   [2] PostgreSQL 行数（pg_rows.tsv：pg_dump 前的行数快照）
#   [3] ClickHouse 行数 + 分区数（clickhouse_rows.tsv）
#   [4] S3/对象存储 对象数量 + 大小 + 每对象 SHA-256（s3_manifest.tsv）
# 任一不一致 => 打印 FAIL 并以非零退出码结束。
#
# 用途：恢复演练（至少每月一次，假数据隔离环境）与生产恢复后的验收：
#   bash deploy/scripts/restore.sh --target <name> <backup>.tar.gz
#   bash deploy/scripts/verify-restore.sh <backup>.tar.gz
# 全部 PASS 且退出码 0 才视为恢复成功。
#
# 选项：
#   --skip-s3              跳过 S3 对象校验（如目标环境无 S3）
#   --skip-s3-checksum     只比对 S3 对象数量/大小，不下载比对 SHA-256
# 环境变量（与 backup.sh/restore.sh 一致，演练时指向演练栈）：
#   POSTGRES_HOST/POSTGRES_PORT/POSTGRES_USER/POSTGRES_DB/POSTGRES_PASSWORD
#   CLICKHOUSE_HOST/CLICKHOUSE_PORT/CLICKHOUSE_USER/CLICKHOUSE_PASSWORD
#   S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY
#   BAK_BASE_DIR（mc 配置目录，默认 /opt/soymutdb/backups）
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

SKIP_S3=0
SKIP_S3_CHECKSUM=0
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-s3)          SKIP_S3=1; shift ;;
        --skip-s3-checksum) SKIP_S3_CHECKSUM=1; shift ;;
        --help|-h)
            sed -n '2,28p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)
            die "unknown option: $1" ;;
        *)
            [[ -n "${BACKUP_FILE}" ]] && die "too many arguments: $1"
            BACKUP_FILE="$1"; shift ;;
    esac
done

[[ -n "${BACKUP_FILE}" ]] || die "Usage: bash deploy/scripts/verify-restore.sh <backup-file.tar.gz> [--skip-s3] [--skip-s3-checksum]"
[[ -f "${BACKUP_FILE}" ]] || die "Backup file not found: ${BACKUP_FILE}"

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

FAIL_COUNT=0
PASS_COUNT=0

check() { # description ok(fail=0)
    local desc="$1" ok="$2"
    if [[ "${ok}" == "0" ]]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        info "PASS  ${desc}"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        err "FAIL  ${desc}"
    fi
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Restore Verification${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Backup: ${BACKUP_FILE}"
echo ""

# ---------------------------------------------------------------------
# [0] 归档 SHA-256
# ---------------------------------------------------------------------
if [[ -f "${BACKUP_FILE}.sha256" ]]; then
    echo -e "${CYAN}[0/4] Archive SHA-256...${NC}"
    if (cd "$(dirname "${BACKUP_FILE}")" && sha256sum -c "$(basename "${BACKUP_FILE}").sha256" >/dev/null 2>&1); then
        check "archive sha256 (${BACKUP_FILE##*/})" 0
    else
        check "archive sha256 (${BACKUP_FILE##*/})" 1
    fi
else
    warn "sidecar <file>.sha256 不存在，跳过归档校验（v2 备份应始终生成）。"
fi

# ---------------------------------------------------------------------
# 解包 + manifest
# ---------------------------------------------------------------------
echo -e "${CYAN}Extracting backup...${NC}"
tar -xzf "${BACKUP_FILE}" -C "${RESTORE_DIR}"
BACKUP_SUBDIR=""
for cand in "${RESTORE_DIR}"/*; do
    [[ -d "${cand}" ]] && BACKUP_SUBDIR="$(basename "${cand}")" && break
done
[[ -n "${BACKUP_SUBDIR}" ]] || die "Backup archive has no content directory."
RESTORE_SRC="${RESTORE_DIR}/${BACKUP_SUBDIR}"

MANIFEST="${RESTORE_SRC}/manifest.json"
[[ -f "${MANIFEST}" ]] || die "manifest.json not found - 不是 v2 备份，无法验证。"
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

# ---------------------------------------------------------------------
# [1] PostgreSQL 行数
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/4] PostgreSQL row counts...${NC}"
PG_ROWS_TSV="${RESTORE_SRC}/pg_rows.tsv"
if [[ -f "${PG_ROWS_TSV}" ]]; then
    while IFS=$'\t' read -r tbl expected; do
        [[ -n "${tbl}" ]] || continue
        if [[ "${expected}" == "ERROR" ]]; then
            warn "  备份时 ${tbl} 行数快照失败，跳过该表比对。"
            continue
        fi
        actual="$(pg_query "SELECT count(*) FROM ${tbl}" 2>/dev/null || echo ERROR)"
        if [[ "${actual}" == "${expected}" ]]; then
            check "pg ${tbl} = ${expected} rows" 0
        else
            err "    pg ${tbl}: expected ${expected}, actual ${actual}"
            check "pg ${tbl} row count" 1
        fi
    done < "${PG_ROWS_TSV}"
else
    warn "pg_rows.tsv 缺失，跳过 PG 行数比对。"
fi

# ---------------------------------------------------------------------
# [2] ClickHouse 行数 + 分区数
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/4] ClickHouse rows & partitions...${NC}"
CH_ROWS_TSV="${RESTORE_SRC}/clickhouse_rows.tsv"
if [[ -f "${CH_ROWS_TSV}" ]]; then
    while IFS=$'\t' read -r tname exp_rows exp_parts; do
        [[ -n "${tname}" ]] || continue
        rows="$(ch_query "SELECT count() FROM soymutdb.\`${tname}\`" 2>/dev/null || echo ERROR)"
        parts="$(ch_query "SELECT count(DISTINCT partition) FROM system.parts WHERE database='soymutdb' AND table='${tname}' AND active=1" 2>/dev/null || echo ERROR)"
        if [[ "${rows}" == "${exp_rows}" ]]; then
            check "ch ${tname} rows = ${exp_rows}" 0
        else
            err "    ch ${tname}: expected ${exp_rows} rows, actual ${rows}"
            check "ch ${tname} rows" 1
        fi
        if [[ "${parts}" == "${exp_parts}" ]]; then
            check "ch ${tname} partitions = ${exp_parts}" 0
        else
            err "    ch ${tname}: expected ${exp_parts} partitions, actual ${parts}"
            check "ch ${tname} partitions" 1
        fi
    done < "${CH_ROWS_TSV}"
else
    warn "clickhouse_rows.tsv 缺失，跳过 CH 比对。"
fi

# ---------------------------------------------------------------------
# [3] S3 对象数量 + 大小 + checksum
# ---------------------------------------------------------------------
if [[ "${SKIP_S3}" == "1" ]]; then
    echo -e "${CYAN}[3/4] S3 verification skipped (--skip-s3).${NC}"
else
    echo -e "${CYAN}[3/4] S3 objects & checksums...${NC}"
    S3_MANIFEST="${RESTORE_SRC}/s3_manifest.tsv"
    if [[ -f "${S3_MANIFEST}" ]]; then
        if mc_run alias set s3dst "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" >/dev/null 2>&1; then
            # 数量 + 大小
            for bucket in $(cut -f1 "${S3_MANIFEST}" | sort -u); do
                exp_count="$(grep -c "^${bucket}"$'\t' "${S3_MANIFEST}" || true)"
                exp_bytes="$(awk -F'\t' -v b="${bucket}" '$1==b {s+=$3} END {print s+0}' "${S3_MANIFEST}")"
                act_count=0
                act_bytes=0
                while IFS= read -r line; do
                    [[ -n "${line}" ]] || continue
                    sz="$(printf '%s' "${line}" | sed -n 's/.*"size": *\([0-9]*\).*/\1/p')"
                    act_bytes=$((act_bytes + sz))
                    act_count=$((act_count + 1))
                done < <(mc_run ls --recursive --json "s3dst/${bucket}/" 2>/dev/null || true)
                if [[ "${act_count}" == "${exp_count}" ]]; then
                    check "s3 ${bucket} object count = ${exp_count}" 0
                else
                    err "    s3 ${bucket}: expected ${exp_count} objects, actual ${act_count}"
                    check "s3 ${bucket} object count" 1
                fi
                if [[ "${act_bytes}" == "${exp_bytes}" ]]; then
                    check "s3 ${bucket} total bytes = ${exp_bytes}" 0
                else
                    err "    s3 ${bucket}: expected ${exp_bytes} bytes, actual ${act_bytes}"
                    check "s3 ${bucket} total bytes" 1
                fi
            done
            # checksum（下载比对，默认全量；--skip-s3-checksum 时跳过）
            if [[ "${SKIP_S3_CHECKSUM}" == "1" ]]; then
                warn "S3 checksum verification skipped (--skip-s3-checksum)."
            else
                CHK_TMP="$(mktemp -d)"
                while IFS=$'\t' read -r bucket rel size hash; do
                    [[ -n "${rel}" ]] || continue
                    [[ -n "${hash}" ]] || continue   # 备份时未计算哈希（BAK_S3_HASH_OBJECTS=0）
                    if mc_run cp "s3dst/${bucket}/${rel}" "${CHK_TMP}/obj" >/dev/null 2>&1; then
                        got="$(sha256sum "${CHK_TMP}/obj" | awk '{print $1}')"
                        if [[ "${got}" == "${hash}" ]]; then
                            check "s3 ${bucket}/${rel} sha256" 0
                        else
                            err "    s3 ${bucket}/${rel}: sha256 mismatch"
                            check "s3 ${bucket}/${rel} sha256" 1
                        fi
                        rm -f "${CHK_TMP}/obj"
                    else
                        err "    s3 ${bucket}/${rel}: object missing on target"
                        check "s3 ${bucket}/${rel} exists" 1
                    fi
                done < "${S3_MANIFEST}"
                rm -rf "${CHK_TMP}"
            fi
        else
            warn "mc 不可用，跳过 S3 校验。"
        fi
    else
        warn "s3_manifest.tsv 缺失，跳过 S3 校验。"
    fi
fi

# ---------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Verification Summary${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  PASS: ${PASS_COUNT}   FAIL: ${FAIL_COUNT}"
echo ""
if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    echo -e "${RED}  RESTORE VERIFICATION FAILED (${FAIL_COUNT} checks)${NC}" >&2
    echo "  请检查上述 FAIL 项；如需容忍 ReplacingMergeTree 合并延迟，"
    echo "  可在表合并完成后重跑本脚本。"
    exit 1
else
    echo -e "${GREEN}  ALL CHECKS PASSED.${NC}"
    exit 0
fi

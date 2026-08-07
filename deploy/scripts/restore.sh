#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Restore Script
# =====================================================================
# Restores from a backup archive.
#
# Usage:
#   bash deploy/scripts/restore.sh /path/to/backup.tar.gz
# =====================================================================
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

BACKUP_FILE="${1:-}"

if [[ -z "${BACKUP_FILE}" ]]; then
    echo -e "${RED}[ERROR] Usage: bash deploy/scripts/restore.sh <backup-file.tar.gz>${NC}"
    exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo -e "${RED}[ERROR] Backup file not found: ${BACKUP_FILE}${NC}"
    exit 1
fi

# Load environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
fi

RESTORE_DIR=$(mktemp -d)
trap 'rm -rf ${RESTORE_DIR}' EXIT

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Restore${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Backup: ${BACKUP_FILE}"
echo "  Temp:   ${RESTORE_DIR}"
echo ""

echo -e "${YELLOW}WARNING: This will OVERWRITE existing data!${NC}"
read -p "Type 'restore' to confirm: " CONFIRM
if [[ "${CONFIRM}" != "restore" ]]; then
    echo "Cancelled."
    exit 0
fi

# Extract backup
echo -e "${CYAN}Extracting backup...${NC}"
tar -xzf "${BACKUP_FILE}" -C "${RESTORE_DIR}"
BACKUP_SUBDIR=$(ls "${RESTORE_DIR}")
echo -e "${GREEN}  Extracted to ${RESTORE_DIR}/${BACKUP_SUBDIR}${NC}"

# ---------------------------------------------------------------------
# 1. Restore PostgreSQL
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/3] Restoring PostgreSQL...${NC}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"

if [[ -f "${RESTORE_DIR}/${BACKUP_SUBDIR}/postgres.dump" ]]; then
    PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
        pg_restore \
        --host="${PG_HOST}" \
        --port="${PG_PORT}" \
        --username="${PG_USER}" \
        --dbname="${PG_DB}" \
        --clean --if-exists --no-owner --no-privileges \
        "${RESTORE_DIR}/${BACKUP_SUBDIR}/postgres.dump" || true
    echo -e "${GREEN}  PostgreSQL restore complete.${NC}"
else
    echo -e "${YELLOW}  PostgreSQL backup not found, skipping.${NC}"
fi

# ---------------------------------------------------------------------
# 2. Restore ClickHouse dimension tables
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/3] Restoring ClickHouse dimension tables...${NC}"
CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
CH_USER="${CLICKHOUSE_USER:-soymutdb}"
CH_PASS="${CLICKHOUSE_PASSWORD:-soymutdb_dev_password}"

for table in release_dim gene_dim mutant_line_dim consequence_dim; do
    TSV_FILE="${RESTORE_DIR}/${BACKUP_SUBDIR}/clickhouse_${table}.tsv"
    if [[ -f "${TSV_FILE}" ]]; then
        curl -s -u "${CH_USER}:${CH_PASS}" \
            "http://${CH_HOST}:${CH_PORT}/?query=TRUNCATE+TABLE+soymutdb.${table}"
        curl -s -u "${CH_USER}:${CH_PASS}" \
            "http://${CH_HOST}:${CH_PORT}/?query=INSERT+INTO+soymutdb.${table}+FORMAT+TabSeparated" \
            --data-binary @"${TSV_FILE}"
        echo -e "  Restored ${table}"
    fi
done
echo -e "${GREEN}  ClickHouse restore complete.${NC}"

# ---------------------------------------------------------------------
# 3. Restore S3 configuration
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/3] Restoring S3 configuration...${NC}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"

if command -v mc &>/dev/null; then
    mc alias set restore "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" 2>/dev/null || true
    for bucket in genomic-data user-tracks blast-dbs exports; do
        POLICY_FILE="${RESTORE_DIR}/${BACKUP_SUBDIR}/s3_policy_${bucket}.json"
        if [[ -f "${POLICY_FILE}" ]]; then
            mc policy set "$(cat ${POLICY_FILE})" "restore/${bucket}" 2>/dev/null || true
        fi
    done
    echo -e "${GREEN}  S3 configuration restored.${NC}"
else
    echo -e "${YELLOW}  mc not found, skipping S3 restore.${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Restore Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Restart services: sudo systemctl restart soymutdb.target"
echo "  2. Verify data integrity"
echo ""

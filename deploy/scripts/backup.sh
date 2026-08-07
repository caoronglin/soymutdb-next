#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Backup Script
# =====================================================================
# Creates backups of:
#   - PostgreSQL (pg_dump)
#   - ClickHouse (BACKUP command)
#   - MinIO/S3 lifecycle configuration
#
# Usage:
#   bash deploy/scripts/backup.sh           # Standard backup
#   bash deploy/scripts/backup.sh --full    # Full backup (including genomic data)
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

BACKUP_DIR="${BACKUP_DIR:-/opt/soymutdb/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
FULL_BACKUP=false

if [[ "${1:-}" == "--full" ]]; then
    FULL_BACKUP=true
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Backup${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Timestamp: ${TIMESTAMP}"
echo "  Path: ${BACKUP_PATH}"
echo "  Full: ${FULL_BACKUP}"
echo ""

mkdir -p "${BACKUP_PATH}"

# ---------------------------------------------------------------------
# 1. PostgreSQL backup
# ---------------------------------------------------------------------
echo -e "${CYAN}[1/3] Backing up PostgreSQL...${NC}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"

PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
    pg_dump \
    --host="${PG_HOST}" \
    --port="${PG_PORT}" \
    --username="${PG_USER}" \
    --dbname="${PG_DB}" \
    --format=custom \
    --file="${BACKUP_PATH}/postgres.dump"

echo -e "${GREEN}  PostgreSQL backup complete: $(du -sh ${BACKUP_PATH}/postgres.dump | cut -f1)${NC}"

# ---------------------------------------------------------------------
# 2. ClickHouse backup
# ---------------------------------------------------------------------
echo -e "${CYAN}[2/3] Backing up ClickHouse...${NC}"
CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
CH_USER="${CLICKHOUSE_USER:-soymutdb}"
CH_PASS="${CLICKHOUSE_PASSWORD:-soymutdb_dev_password}"

# Use ClickHouse BACKUP command
curl -s -u "${CH_USER}:${CH_PASS}" \
    "http://${CH_HOST}:${CH_PORT}/" \
    --data-binary "BACKUP TABLE soymutdb.variant_facts TO Disk('backups', 'variant_facts_${TIMESTAMP}.zip');"

# Also dump dimension tables as SQL
for table in release_dim gene_dim mutant_line_dim consequence_dim; do
    curl -s -u "${CH_USER}:${CH_PASS}" \
        "http://${CH_HOST}:${CH_PORT}/?query=SELECT+*+FROM+soymutdb.${table}+FORMAT+TabSeparated" \
        > "${BACKUP_PATH}/clickhouse_${table}.tsv"
done

echo -e "${GREEN}  ClickHouse backup complete.${NC}"

# ---------------------------------------------------------------------
# 3. MinIO/S3 lifecycle (bucket policies)
# ---------------------------------------------------------------------
echo -e "${CYAN}[3/3] Saving MinIO/S3 configuration...${NC}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"

if command -v mc &>/dev/null; then
    mc alias set backup "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" 2>/dev/null || true
    for bucket in genomic-data user-tracks blast-dbs exports; do
        mc policy get "backup/${bucket}" > "${BACKUP_PATH}/s3_policy_${bucket}.json" 2>/dev/null || true
    done
    echo -e "${GREEN}  S3 configuration saved.${NC}"
else
    echo -e "${YELLOW}  mc (MinIO client) not found, skipping S3 config backup.${NC}"
fi

# ---------------------------------------------------------------------
# Full backup: include genomic data from S3
# ---------------------------------------------------------------------
if [[ "${FULL_BACKUP}" == "true" ]] && command -v mc &>/dev/null; then
    echo -e "${CYAN}  [Full] Backing up genomic data from S3...${NC}"
    mkdir -p "${BACKUP_PATH}/s3_data"
    for bucket in genomic-data user-tracks blast-dbs exports; do
        mc cp --recursive "backup/${bucket}" "${BACKUP_PATH}/s3_data/${bucket}" 2>/dev/null || true
    done
    echo -e "${GREEN}  Genomic data backup complete.${NC}"
fi

# ---------------------------------------------------------------------
# Compress and clean old backups
# ---------------------------------------------------------------------
echo -e "${CYAN}Compressing backup...${NC}"
cd "${BACKUP_DIR}"
tar -czf "${TIMESTAMP}.tar.gz" "${TIMESTAMP}"
rm -rf "${TIMESTAMP}"

BACKUP_SIZE=$(du -sh "${TIMESTAMP}.tar.gz" | cut -f1)
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Backup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo "  File: ${BACKUP_DIR}/${TIMESTAMP}.tar.gz"
echo "  Size: ${BACKUP_SIZE}"
echo ""

# Clean backups older than 30 days
find "${BACKUP_DIR}" -name "*.tar.gz" -mtime +30 -delete 2>/dev/null || true
echo "  Old backups (>30 days) cleaned."

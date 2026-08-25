#!/usr/bin/env bash
set -euo pipefail
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; fi
ROOT="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
ENV_FILE="${SOYMUTDB_ENV_FILE:-/etc/soymutdb/soymutdb.env}"
OUT_DIR="${SOYMUTDB_BASELINE_BACKUP_DIR:-${ROOT}/backups}"
if (( DRY_RUN )); then echo "DRY-RUN: would pg_dump PostgreSQL to ${OUT_DIR}"; exit 0; fi
[[ -f "${ENV_FILE}" ]] || { echo "missing ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
DB_URL="${SOYMUTDB_DATABASE_URL:-}"
DB_URL="${DB_URL/+asyncpg/}"
[[ -n "${DB_URL}" ]] || { echo "SOYMUTDB_DATABASE_URL is required" >&2; exit 1; }
mkdir -p "${OUT_DIR}"
OUT="${OUT_DIR}/baseline-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --dbname="${DB_URL}" --file="${OUT}"
sha256sum "${OUT}" > "${OUT}.sha256"
printf 'Backup written: %s\\n' "${OUT}"

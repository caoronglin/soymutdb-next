#!/usr/bin/env bash
set -euo pipefail
DUMP="${1:-}"
[[ -n "${DUMP}" && -f "${DUMP}" ]] || { echo "usage: $0 backup.dump" >&2; exit 2; }
ENV_FILE="${SOYMUTDB_ENV_FILE:-/etc/soymutdb/soymutdb.env}"
[[ -f "${ENV_FILE}" ]] || { echo "missing ${ENV_FILE}" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a
DB_URL="${SOYMUTDB_DATABASE_URL:-}"
DB_URL="${DB_URL/+asyncpg/}"
[[ -n "${DB_URL}" ]] || { echo "SOYMUTDB_DATABASE_URL is required" >&2; exit 1; }
pg_restore --clean --if-exists --no-owner --dbname="${DB_URL}" "${DUMP}"

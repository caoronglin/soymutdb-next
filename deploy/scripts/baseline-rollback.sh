#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-}"
ROOT="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
[[ -n "${TARGET}" ]] || { echo "usage: $0 /opt/soymutdb/releases/<id>" >&2; exit 2; }
[[ -d "${TARGET}" ]] || { echo "release not found: ${TARGET}" >&2; exit 1; }
ln -sfn "${TARGET}" "${ROOT}/current"
systemctl restart soymutdb-api.service
"${ROOT}/current/deploy/scripts/baseline-healthcheck.sh"
printf 'Rollback completed: %s\\n' "${TARGET}"

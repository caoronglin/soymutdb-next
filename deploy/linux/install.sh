#!/usr/bin/env bash
# SoyMutDB Linux baseline installer: native FastAPI + PostgreSQL, no Docker.
# Usage: sudo bash deploy/linux/install.sh [--dry-run]
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; shift; fi
[[ $# -eq 0 ]] || { echo "usage: $0 [--dry-run]" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
SERVICE_USER="${SOYMUTDB_SERVICE_USER:-soymutdb}"
RELEASE_ID="${SOYMUTDB_RELEASE_ID:-$(date -u +%Y%m%d%H%M%S)}"
RELEASE_DIR="${INSTALL_DIR}/releases/${RELEASE_ID}"
ENV_DIR="${SOYMUTDB_ENV_DIR:-/etc/soymutdb}"
ENV_FILE="${ENV_DIR}/soymutdb.env"

run_step() {
  echo "==> $*"
  if (( DRY_RUN == 0 )); then "$@"; fi
}
run_shell() {
  echo "==> $*"
  if (( DRY_RUN == 0 )); then bash -c "$*"; fi
}
require_cmd() {
  if (( DRY_RUN == 1 )); then return 0; fi
  command -v "$1" >/dev/null 2>&1 || { echo "missing required command: $1" >&2; exit 1; }
}

if (( DRY_RUN == 0 && EUID != 0 )); then
  echo "run as root or use sudo" >&2
  exit 1
fi
for cmd in python3 systemctl; do require_cmd "$cmd"; done
[[ -d "${PROJECT_ROOT}/apps/api" ]] || { echo "apps/api not found" >&2; exit 1; }

run_step install -d -m 0750 "${INSTALL_DIR}/releases" "${INSTALL_DIR}/backups" "${ENV_DIR}"
if (( DRY_RUN == 0 )); then
  if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
  fi
fi
run_step install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0750 "${RELEASE_DIR}/apps"
run_step cp -a "${PROJECT_ROOT}/apps/api" "${RELEASE_DIR}/apps/api"
run_step cp -a "${PROJECT_ROOT}/deploy" "${RELEASE_DIR}/deploy"
run_step python3 -m venv "${RELEASE_DIR}/venv"
run_shell "${RELEASE_DIR}/venv/bin/python -m pip install --upgrade pip && ${RELEASE_DIR}/venv/bin/python -m pip install -e ${RELEASE_DIR}/apps/api"

if (( DRY_RUN == 0 )); then
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${PROJECT_ROOT}/.env" ]]; then
      install -o root -g "${SERVICE_USER}" -m 0640 "${PROJECT_ROOT}/.env" "${ENV_FILE}"
    else
      cat >"${ENV_FILE}" <<'EOF'
SOYMUTDB_APP_ENV=prod
SOYMUTDB_DEPLOYMENT_MODE=baseline
SOYMUTDB_DATABASE_URL=postgresql+asyncpg://soymutdb:CHANGE_ME@127.0.0.1:5432/soymutdb
SOYMUTDB_JWT_SECRET=CHANGE_ME_generate_a_long_random_secret
SOYMUTDB_CORS_ORIGINS=https://CHANGE_ME.example
SOYMUTDB_ADMIN_EMAIL=admin@CHANGE_ME.example
SOYMUTDB_ADMIN_PASSWORD=CHANGE_ME_use_a_long_password
EOF
      chown root:"${SERVICE_USER}" "${ENV_FILE}"
      chmod 0640 "${ENV_FILE}"
      echo "created ${ENV_FILE}; edit production secrets before starting" >&2
    fi
  fi
fi

if (( DRY_RUN == 0 )); then
  ln -sfn "${RELEASE_DIR}" "${INSTALL_DIR}/current"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${RELEASE_DIR}"
  sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" -e "s|@SERVICE_USER@|${SERVICE_USER}|g" -e "s|@ENV_FILE@|${ENV_FILE}|g" \\
    "${SCRIPT_DIR}/soymutdb-api.service" > /etc/systemd/system/soymutdb-api.service
  sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" "${SCRIPT_DIR}/soymutdb.target" > /etc/systemd/system/soymutdb.target
  systemctl daemon-reload
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  runuser -u "${SERVICE_USER}" -- "${INSTALL_DIR}/current/venv/bin/python" -m alembic \\
    -c "${INSTALL_DIR}/current/apps/api/alembic.ini" upgrade head
  systemctl enable soymutdb-api.service soymutdb.target
  systemctl restart soymutdb-api.service
fi

echo "baseline installation prepared at ${RELEASE_DIR}"
echo "environment: ${ENV_FILE}"
echo "logs: journalctl -u soymutdb-api.service -f"
echo "health: curl --fail http://127.0.0.1:8000/health"

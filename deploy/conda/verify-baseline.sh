#!/usr/bin/env bash
# Create/update the unified mamba environment and run a Docker-free API smoke test.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export MAMBA_CACHE_DIR="${MAMBA_CACHE_DIR:-${ROOT}/.mamba-cache}"
mkdir -p "${MAMBA_CACHE_DIR}"
ENV_FILE="${ROOT}/deploy/conda/environment-baseline.yml"
MAMBA_BIN="${MAMBA:-mamba}"
ENV_PREFIX="${SOYMUTDB_MAMBA_PREFIX:-${MAMBA_ROOT_PREFIX:-${HOME}/.conda}/envs/soymutdb-baseline}"
PYTHON_BIN="${ENV_PREFIX}/bin/python"
API_DIR="${ROOT}/apps/api"
JOBS_DIR="${ROOT}/packages/jobs-py"
PROJECT_SITE="${SOYMUTDB_PROJECT_SITE_PACKAGES:-${API_DIR}/.venv/lib/python3.15/site-packages}"
PG_PORT="${SOYMUTDB_SMOKE_PG_PORT:-55432}"
API_PORT="${SOYMUTDB_SMOKE_API_PORT:-18000}"
PG_DIR=""
API_PID=""

command -v "${MAMBA_BIN}" >/dev/null 2>&1 || { echo "mamba is required: ${MAMBA_BIN}" >&2; exit 1; }

if [[ ! -x "${ENV_PREFIX}/bin/python" ]]; then
  "${MAMBA_BIN}" env create --yes --override-channels --channel conda-forge --prefix "${ENV_PREFIX}" --file "${ENV_FILE}"
elif [[ "${SOYMUTDB_MAMBA_UPDATE:-0}" == "1" ]]; then
  "${MAMBA_BIN}" env update --yes --prefix "${ENV_PREFIX}" --file "${ENV_FILE}" --prune
fi

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "${PY_VERSION}" == "3.15" ]] || { echo "expected Python 3.15, got ${PY_VERSION}" >&2; exit 1; }

PIP_FLAGS=()
if [[ -d "${PROJECT_SITE}" ]]; then
  export PYTHONPATH="${PROJECT_SITE}:${PYTHONPATH:-}"
  PIP_FLAGS+=(--no-deps)
fi
"${PYTHON_BIN}" -m pip install --upgrade "${PIP_FLAGS[@]}" --editable "${JOBS_DIR}[dev]"
"${PYTHON_BIN}" -m pip install --upgrade "${PIP_FLAGS[@]}" --editable "${API_DIR}[dev]"

cleanup() {
  set +e
  if [[ -n "${API_PID}" ]]; then kill "${API_PID}" >/dev/null 2>&1 || true; fi
  if [[ -n "${PG_DIR}" ]]; then "${ENV_PREFIX}/bin/pg_ctl" -D "${PG_DIR}" -m fast stop >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

"${PYTHON_BIN}" -m ruff check "${API_DIR}/app/api/v1/health.py" "${API_DIR}/app/core/config.py" "${API_DIR}/tests/test_health_unit.py" "${API_DIR}/tests/test_config_security.py"
"${PYTHON_BIN}" -m pytest "${API_DIR}/tests/test_health_unit.py" "${API_DIR}/tests/test_config_security.py" -q

export SOYMUTDB_APP_ENV=dev
export SOYMUTDB_DEPLOYMENT_MODE=baseline
export SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:${PG_PORT}/soymutdb"
# Ephemeral per-run credentials: a literal here would be a published secret
# that every copy of this script shares. 48 bytes of /dev/urandom is well
# above the 32-character floor the API enforces.
smoke_secret() { LC_ALL=C tr -dc "A-Za-z0-9" </dev/urandom | head -c 48; }
export SOYMUTDB_JWT_SECRET="$(smoke_secret)"
export SOYMUTDB_CORS_ORIGINS="http://127.0.0.1:4173"
export SOYMUTDB_ADMIN_EMAIL="smoke@example.invalid"
export SOYMUTDB_ADMIN_PASSWORD="$(smoke_secret)"

PG_DIR="$(mktemp -d)"
"${ENV_PREFIX}/bin/initdb" -D "${PG_DIR}" --username=postgres --auth=trust >/dev/null
"${ENV_PREFIX}/bin/pg_ctl" -D "${PG_DIR}" -o "-p ${PG_PORT}" -w start >/dev/null
"${ENV_PREFIX}/bin/createdb" -h 127.0.0.1 -p "${PG_PORT}" -U postgres soymutdb
cd "${API_DIR}"
"${PYTHON_BIN}" -m alembic upgrade head
"${PYTHON_BIN}" -m app.scripts.seed_page_builder
"${PYTHON_BIN}" -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}" >"${PG_DIR}/api.log" 2>&1 &
API_PID=$!
cd "${ROOT}"

for attempt in $(seq 1 40); do
  if curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/health/live" >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/health/live" >/dev/null
curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/health/ready" >/dev/null
page_definition="$(curl --fail --silent "http://127.0.0.1:${API_PORT}/api/v1/page-definitions/%2F")"
"${PYTHON_BIN}" -c 'import json, sys
payload = json.loads(sys.argv[1])
assert payload["status"] == "published"
definition = payload["definition"]
assert definition["root"]["type"] == "columns"
def walk(node):
    yield node
    for child in node.get("children", []):
        yield from walk(child)
assert any(node.get("type") == "resource_cards" for node in walk(definition["root"]))' "${page_definition}"
printf "mamba baseline smoke passed: Python %s, PostgreSQL 16, API port %s, Page Builder contract verified\n" "${PY_VERSION}" "${API_PORT}"

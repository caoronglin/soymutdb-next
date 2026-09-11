#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — cloud development bootstrap (CNB 云原生开发)
# =============================================================================
# Owns everything that turns a bare CNB branch page into a working SoyMutDB
# development environment, so the `.cnb.yml` stage body stays a single
# `bash scripts/start-cloud-dev.sh <mode>` call that the platform's default
# shell cannot misinterpret (see docs/ops/ci-cd.md, "Stage shell").
#
# Modes
#   full         prepare dependencies only; the developer drives the servers
#                from the WebIDE terminal (`pnpm dev:web`, uvicorn, …).
#   preview      additionally launch the public portal on 0.0.0.0:${PREVIEW_PORT}
#                and leave it running in the background, so the CNB port
#                preview page works without touching a terminal.
#   api-preview  additionally launch the FastAPI app on 0.0.0.0:${API_PORT}.
#
# Why a script and not inline YAML
#   * A CNB stage body is executed with `sh` (dash), which rejects `set -o
#     pipefail` at run time. The shebang makes the interpreter explicit.
#   * The same bootstrap must run for WebIDE, only-preview, and manual triggers.
#     Duplicating it per event is how the two drift apart.
#
# Environment
#   SOYMUTDB_DEV_MODE        full | preview | api-preview   (default: full)
#   SOYMUTDB_DEV_INSTALL     1 (default) to run pnpm install; 0 to skip
#   SOYMUTDB_DEV_WEB_PORT    public portal port              (default: 5173)
#   SOYMUTDB_DEV_API_PORT    FastAPI port                    (default: 8000)
#   SOYMUTDB_DEV_LOG_DIR     where background logs land      (default: .dev-logs)
#
# Exit status
#   0  the requested mode reached its goal
#   1  a required prerequisite was missing or a step failed
#
# Note: `preview` mode is what CNB's only-preview mode drives. That mode
# requires the business service on the fixed platform port 8686, so
# .cnb.yml sets SOYMUTDB_DEV_WEB_PORT=8686 for the preview entry point.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${SOYMUTDB_DEV_MODE:-full}"
INSTALL="${SOYMUTDB_DEV_INSTALL:-1}"
WEB_PORT="${SOYMUTDB_DEV_WEB_PORT:-5173}"
API_PORT="${SOYMUTDB_DEV_API_PORT:-8000}"
LOG_DIR="${SOYMUTDB_DEV_LOG_DIR:-${REPO_ROOT}/.dev-logs}"

for argument in "$@"; do
  case "${argument}" in
    full|preview|api-preview) MODE="${argument}" ;;
    -h|--help)
      sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: ${argument}" >&2; exit 2 ;;
  esac
done

case "${MODE}" in
  full|preview|api-preview) ;;
  *) echo "unknown mode: ${MODE}" >&2; exit 2 ;;
esac

log() { printf '[start-cloud-dev] %s\n' "$*" >&2; }

# -----------------------------------------------------------------------------
# 1. Bind every service to 0.0.0.0
# -----------------------------------------------------------------------------
# A service listening on localhost/127.0.0.1 is unreachable from CNB's port
# preview and from a forwarded local browser: the proxy connects from outside
# the container's loopback. This is the single most common reason a "started"
# environment shows a blank preview, so it is defaulted here rather than left to
# each launch command.
export VITE_HOST="${VITE_HOST:-0.0.0.0}"
export HOST="${HOST:-0.0.0.0}"

# -----------------------------------------------------------------------------
# 2. Materialise the workspace inside THIS container
# -----------------------------------------------------------------------------
# CNB gives every stage a fresh container, and the checkout carries no
# node_modules. scripts/setup-workspace.sh is the single place that enables the
# pinned pnpm and links the store volume; without it the next command fails with
# `pnpm: command not found`.
if [[ "${INSTALL}" == "1" ]]; then
  bash "${REPO_ROOT}/scripts/setup-workspace.sh"
else
  log "SOYMUTDB_DEV_INSTALL=0; skipping dependency materialisation"
fi

# -----------------------------------------------------------------------------
# 3. Report the raw material commands (always useful)
# -----------------------------------------------------------------------------
cat >&2 <<USAGE

SoyMutDB cloud development environment is ready (mode: ${MODE}).

  public portal     pnpm dev:web
  admin console     pnpm dev:admin
  api (FastAPI)     cd apps/api && uvicorn app.main:app --reload --port ${API_PORT}
  data layer        docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile core up -d postgres clickhouse redis minio
  delivery jobs     pnpm ci:jobs
  acceptance        bash scripts/acceptance.sh

USAGE

# -----------------------------------------------------------------------------
# 4. Background launch helpers
# -----------------------------------------------------------------------------
mkdir -p "${LOG_DIR}"

# Launch a service in the background and wait for its port to accept a
# connection. Waiting matters twice over:
#   * only-preview mode polls the business port and gives up after ~200s, so a
#     slow first Vite start must not be reported as a failure;
#   * a "started" service that never bound the port is the failure mode this
#     whole script exists to make visible.
launch_background() {
  local name="$1" port="$2"
  shift 2

  local log_file="${LOG_DIR}/${name}.log"
  log "starting ${name}: $* (log: ${log_file})"
  nohup "$@" >"${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${LOG_DIR}/${name}.pid"

  local attempt
  for attempt in $(seq 1 60); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      log "${name} exited before binding port ${port}; last log lines:"
      tail -n 40 "${log_file}" >&2 || true
      return 1
    fi
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
      log "${name} is listening on 0.0.0.0:${port} (pid ${pid})"
      return 0
    fi
    sleep 2
  done

  log "${name} did not bind port ${port} within 120s; last log lines:"
  tail -n 40 "${log_file}" >&2 || true
  return 1
}

# -----------------------------------------------------------------------------
# 5. Mode-specific work
# -----------------------------------------------------------------------------
case "${MODE}" in
  full)
    log "mode=full: dependencies ready, no server started"
    ;;

  preview)
    # `pnpm dev:web` passes --host/--port through to Vite when the package
    # script forwards them. Vite also honours the --host flag via the CLI, so
    # both are supplied: the package script may or may not forward them.
    launch_background web "${WEB_PORT}" \
      pnpm --filter @soymutdb/web dev --host 0.0.0.0 --port "${WEB_PORT}"
    log "public portal preview: http://0.0.0.0:${WEB_PORT}/"
    log "CNB port preview: map ${WEB_PORT}, or use CNB_VSCODE_PROXY_URI with {{port}}"
    ;;

  api-preview)
    if [[ ! -x apps/api/.venv/bin/python ]]; then
      log "missing apps/api/.venv; run: python -m venv apps/api/.venv && apps/api/.venv/bin/pip install -e packages/jobs-py -e 'apps/api[dev]'"
      exit 1
    fi
    # The API refuses to start without a database URL in every non-test
    # environment, so fail with an actionable message instead of a stack trace.
    if [[ -z "${SOYMUTDB_DATABASE_URL:-}" ]]; then
      log "SOYMUTDB_DATABASE_URL is required for api-preview; start the data layer first:"
      log "  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile core up -d postgres clickhouse redis minio"
      exit 1
    fi
    launch_background api "${API_PORT}" \
      env SOYMUTDB_APP_ENV=dev SOYMUTDB_DEPLOYMENT_MODE=baseline \
      SOYMUTDB_JWT_SECRET="${SOYMUTDB_JWT_SECRET:-dev-only-secret-not-for-production}" \
      apps/api/.venv/bin/python -m uvicorn app.main:app \
      --host 0.0.0.0 --port "${API_PORT}"
    log "api preview: http://0.0.0.0:${API_PORT}/api/v1/health/live"
    ;;
esac

log "mode=${MODE} completed"

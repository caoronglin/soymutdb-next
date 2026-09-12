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
#   SOYMUTDB_DEV_ALLOWED_HOSTS  extra Vite dev hosts (default: the CNB preview
#                              domains, see step 1b)
#   SOYMUTDB_DEV_WEB_HOST    address the portal binds to   (default: 0.0.0.0)
#   SOYMUTDB_DEV_API_HOST    address the API binds to      (default: 0.0.0.0)
#   SOYMUTDB_DEV_DATA_LAYER  auto | on | off               (default: auto)
#   SOYMUTDB_DEV_FRONTEND    dev | preview | off           (default: dev)
#
# Exit status
#   0  the requested mode reached its goal
#   1  a required prerequisite was missing or a step failed
#
# Note: `preview` mode is what CNB's only-preview mode drives. That mode
# requires the business service on the fixed platform port 8686, so
# .cnb.yml sets SOYMUTDB_DEV_WEB_PORT=8686 for the preview entry point.
#
# Two failure modes this script exists to make impossible
#   1. "Blocked request. This host (...cnb.space) is not allowed." — Vite 6
#      rejects a Host it does not know, and CNB mints a NEW `*.cnb.space`
#      hostname for every environment. The allowlist therefore cannot be
#      hard-coded; step 1b derives it from the platform domains, so the preview
#      works from outside through the proxy AND from inside through loopback.
#   2. "The environment started but the preview is blank" — a server bound to
#      loopback is unreachable from CNB's proxy, which connects from outside the
#      container's loopback. Step 1 defaults both bind addresses to 0.0.0.0.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${SOYMUTDB_DEV_MODE:-full}"
INSTALL="${SOYMUTDB_DEV_INSTALL:-1}"
WEB_PORT="${SOYMUTDB_DEV_WEB_PORT:-5173}"
API_PORT="${SOYMUTDB_DEV_API_PORT:-8000}"
LOG_DIR="${SOYMUTDB_DEV_LOG_DIR:-${REPO_ROOT}/.dev-logs}"
# Bind addresses. 0.0.0.0 because the CNB preview proxy connects from outside
# the container's loopback; a developer who wants loopback-only can set these.
BIND_HOST="${SOYMUTDB_DEV_WEB_HOST:-0.0.0.0}"
API_BIND_HOST="${SOYMUTDB_DEV_API_HOST:-0.0.0.0}"
# The data layer (postgres/clickhouse/redis/minio) is what gives the API a
# release to serve. Brought up automatically when a Docker daemon is reachable,
# explicitly skippable, never silently assumed.
DATA_LAYER="${SOYMUTDB_DEV_DATA_LAYER:-auto}"
# `dev` runs the Vite dev server (HMR); `preview` serves the built tree, which
# starts faster and is what reviewing an existing artifact wants.
FRONTEND="${SOYMUTDB_DEV_FRONTEND:-dev}"

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
export VITE_HOST="${VITE_HOST:-${BIND_HOST}}"
export HOST="${HOST:-${BIND_HOST}}"

# -----------------------------------------------------------------------------
# 1b. Allow the CNB preview hostname at the Vite dev server
# -----------------------------------------------------------------------------
# Vite 6 refuses any request whose Host header is not allowlisted:
#
#   Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not allowed.
#   To allow this host, add "cnb-38o-1k28dm5ta-001.cnb.space" to
#   `server.allowedHosts` in vite.config.js.
#
# The hostname is generated per environment, so listing it by hand is not a fix —
# the next environment gets a different one. The Vite configs now match the
# platform domains (`*.cnb.space`, `*.cnb.run`) by pattern; this step feeds the
# same variable for the cases a config cannot see:
#
#   * CNB_VSCODE_PROXY_URI is the documented way to obtain the preview host
#     (https://<id>-{{port}}.cnb.run); its hostname is added verbatim;
#   * CNB_DEV_DOMAIN / CNB_WEB_HOST / CNB_HOSTS, when the platform exports them,
#     are added the same way;
#   * SOYMUTDB_DEV_ALLOWED_HOSTS stays the escape hatch for any other tunnel.
#
# The existing value is APPENDED to, never replaced, so an operator-provided list
# stays authoritative and additive.
export SOYMUTDB_DEV_ALLOWED_HOSTS="${SOYMUTDB_DEV_ALLOWED_HOSTS:-}"
for candidate in \
  cnb.space cnb.run localhost \
  "${CNB_DEV_DOMAIN:-}" "${CNB_WEB_HOST:-}" "${CNB_HOSTS:-}" "${CNB_VSCODE_PROXY_URI:-}"; do
  [[ -n "${candidate}" ]] || continue
  # Keep only the host, which is what Vite compares: drop the scheme, any
  # userinfo, then the path/query/fragment and finally the port. `{{port}}` in a
  # proxy URI is already dropped by the path rule, so it needs no special case.
  host="${candidate#*://}"
  host="${host##*@}"
  host="${host%%/*}"
  host="${host%%\?*}"
  host="${host%%#*}"
  host="${host%%:*}"
  [[ -n "${host}" ]] || continue
  case ",${SOYMUTDB_DEV_ALLOWED_HOSTS}," in
    *",${host},"*) ;;
    *) SOYMUTDB_DEV_ALLOWED_HOSTS="${SOYMUTDB_DEV_ALLOWED_HOSTS:+${SOYMUTDB_DEV_ALLOWED_HOSTS},}${host}" ;;
  esac
done
if [[ -n "${SOYMUTDB_DEV_ALLOWED_HOSTS}" ]]; then
  export SOYMUTDB_DEV_ALLOWED_HOSTS
  log "Vite dev-server allowlist extended: ${SOYMUTDB_DEV_ALLOWED_HOSTS}"
else
  log "Vite dev-server allowlist: platform defaults only (*.cnb.space, *.cnb.run, localhost)"
fi

# -----------------------------------------------------------------------------
# 1c. Give the frontend configs the dev origins they validate
# -----------------------------------------------------------------------------
# `apps/web/vite.config.ts` validates its deployment origins at IMPORT time —
# `requireDeploymentOrigin` throws rather than defaulting to a placeholder, so an
# unset VITE_API_BASE_URL is
#
#   Error: API origin is required for production deployment
#
# and the command fails before serving anything. That is the desired behaviour
# for a build; for a development server there is no reason to demand a deployed
# API, and Vite's proxy forwards `/api` to the origin anyway.
#
# Two commands need this, not one: `vite dev` does not read `.env` files that the
# repository is not allowed to commit, and `vite preview` ALSO loads the config
# (it serves a built tree through the same pipeline), so a preview of an artifact
# whose build-time origin was not exported would fail the same way.
#
# Only defaulted when unset: an exported value stays authoritative, so pointing
# the environment at a real backend keeps working.
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:${API_PORT}}"
if [[ "${FRONTEND}" == "preview" ]]; then
  # Only a build reads this, and only a non-minimal build requires it; supply it
  # so a preview-shaped config load never trips the same validation.
  export VITE_JBROWSE_BASE_URL="${VITE_JBROWSE_BASE_URL:-http://127.0.0.1:5175}"
fi
export VITE_DEPLOYMENT_MODE="${VITE_DEPLOYMENT_MODE:-standard}"

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
# 2b. Optionally bring the data layer up
# -----------------------------------------------------------------------------
# A portal alone is a frontend-only environment: with no PostgreSQL the API
# cannot resolve an active release and every data-backed page reports
# "unavailable". The compose stack is therefore brought up whenever a Docker
# daemon is reachable, which is exactly when `services: [docker]` is declared on
# the CNB pipeline.
#
# `off` is never implied: the switch reports what it did, so a reviewer can tell
# "no database because I asked for none" from "no database because it failed".
# `--env-file /dev/null` is deliberate. Without it Compose also reads a `.env`
# file next to the top-level `-f` file (`docker-compose.yml`, i.e. the repo
# root), so a developer's leftover `.env` silently changes the development data
# layer — and the preview would depend on a file that is not in the repository.
# The development defaults live in `docker-compose.dev.yml` and in
# `data_layer_start`, nowhere else.
compose_cmd() {
  docker compose --env-file /dev/null \
    -f "${REPO_ROOT}/docker-compose.yml" \
    -f "${REPO_ROOT}/docker-compose.dev.yml" "$@"
}

data_layer_start() {
  case "${DATA_LAYER}" in
    off)
      log "SOYMUTDB_DEV_DATA_LAYER=off; leaving the data layer alone"
      return 0
      ;;
  esac

  if [[ -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
    log "SOYMUTDB_DATABASE_URL is set; reusing the caller-provided database"
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    if [[ "${DATA_LAYER}" == "on" ]]; then
      log "SOYMUTDB_DEV_DATA_LAYER=on but no Docker daemon is reachable"
      log "the CNB pipeline needs \`services: [docker]\` for this"
      return 1
    fi
    log "no Docker daemon; skipping the data layer (set SOYMUTDB_DEV_DATA_LAYER=on to require it)"
    return 0
  fi

  log "starting the data layer (postgres clickhouse redis minio)"

  # Compose interpolates the base file's `${NAME:?message}` references before it
  # merges in docker-compose.dev.yml, and a reference it cannot satisfy aborts
  # the whole command:
  #
  #   error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
  #   required variable MINIO_ROOT_USER is missing a value: MINIO_ROOT_USER is
  #   required
  #
  # `docker-compose.dev.yml` supplies development defaults for the four services
  # below (asserted by scripts/test_development_compose_contract.py), so this
  # call needs nothing exported. The defaults are applied here anyway, because
  # `--env-file /dev/null` above makes this script the only thing that can put a
  # value in the environment, and the base file's `${POSTGRES_PASSWORD:?…}`-style
  # references sit on services the operator will start by hand from the same
  # shell once the preview is up.
  #
  # An operator-provided value still wins: a real credential in the environment
  # is authoritative and is never overwritten. Empty counts as unset, because an
  # empty credential is exactly what the data layer must not run with
  # (`config.py` refuses a default MinIO credential, the release preflight
  # refuses an empty password).
  set_default() {
    local name="$1" fallback="$2"
    if [[ -z "${!name:-}" ]]; then
      export "${name}=${fallback}"
    fi
  }
  set_default POSTGRES_PASSWORD soymutdb_dev_password
  set_default CLICKHOUSE_PASSWORD soymutdb_dev_password
  set_default REDIS_PASSWORD soymutdb_dev_password
  set_default MINIO_ROOT_USER soymutdb_dev
  set_default MINIO_ROOT_PASSWORD soymutdb_dev_password
  # Only the services a portal actually needs. The workers, Celery and the full
  # extended profile stay opt-in from the terminal, so bringing up a preview
  # cannot pull half the stack.
  #
  # `--wait` is NOT used. It waits on every started container, and
  # `minio-init` -- a one-shot bucket creator required by `--profile core` --
  # exits 0 by design, which is the classic "dependency failed to start:
  # container ... exited (0)" that would make every preview report failure on a
  # healthy stack. Readiness is therefore asserted on the port that matters,
  # with a bounded retry, exactly the way the frontend wait works.
  if ! compose_cmd --profile core up -d postgres clickhouse redis minio; then
    log "the data layer did not start; container state follows"
    compose_cmd ps >&2 || true
    return 1
  fi

  local attempt
  for attempt in $(seq 1 45); do
    if (exec 3<>"/dev/tcp/127.0.0.1/5432") 2>/dev/null; then
      # The TCP accept proves the listener; the compose healthcheck proves the
      # server. A container that is up but unwell would let the API start and
      # then fail on its first query, so require both.
      if compose_cmd ps --format '{{.Health}}' postgres 2>/dev/null | grep -qx healthy; then
        # The compose file is the single source of the development credentials,
        # so no second, drifting copy of the connection string is needed here.
        export SOYMUTDB_DATABASE_URL="postgresql+asyncpg://soymutdb:soymutdb_dev_password@127.0.0.1:5432/soymutdb"
        log "data layer ready; SOYMUTDB_DATABASE_URL points at the local PostgreSQL"
        return 0
      fi
    fi
    sleep 2
  done

  log "PostgreSQL did not become healthy within 90s; container state follows"
  compose_cmd ps >&2 || true
  compose_cmd logs --tail 40 postgres >&2 || true
  return 1
}

# The frontend command is built once so the preview and the printed usage text
# cannot disagree. `dev` is HMR against the source; `preview` serves the tree
# `pnpm build:web` produced, which starts materially faster and is the right
# target when the point of the environment is to look at an artifact.
frontend_cmd() {
  case "${FRONTEND}" in
    preview) printf '%s' "web-preview" ;;
    off) printf '%s' "off" ;;
    *) printf '%s' "web" ;;
  esac
}

# -----------------------------------------------------------------------------
# 3. Report the raw material commands (always useful)
# -----------------------------------------------------------------------------
cat >&2 <<USAGE

SoyMutDB cloud development environment is ready (mode: ${MODE}).

  public portal     pnpm dev:web
  admin console     pnpm dev:admin
  api (FastAPI)     cd apps/api && uvicorn app.main:app --reload --port ${API_PORT}
  data layer        docker compose --env-file /dev/null -f docker-compose.yml -f docker-compose.dev.yml \\
                    --profile core up -d postgres clickhouse redis minio
  delivery jobs     pnpm ci:jobs
  acceptance        bash scripts/acceptance.sh

  preview URL       host ${BIND_HOST}, port ${WEB_PORT} (CNB PORTS panel maps it)

USAGE
# The data layer is the expensive part of a preview, so it runs only when a mode
# asks for it: `full` prepares the environment, the preview modes need a backend.
case "${MODE}" in
  preview) data_layer_start ;;
esac

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
      log "${name} is listening on ${BIND_HOST}:${port} (pid ${pid})"
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
    # The frontend command is chosen by SOYMUTDB_DEV_FRONTEND. Both forms take
    # --host/--port through the Vite CLI, so neither depends on whether the
    # package script forwards them; the host is the variable the configs read
    # (VITE_HOST) and the CLI flag is passed as well, so the two cannot disagree.
    case "$(frontend_cmd)" in
      web-preview)
        # `vite preview` serves the tree `pnpm build:web` produced and starts in
        # roughly a second, which is what only-preview mode's ~200s budget wants.
        if [[ ! -d apps/web/dist ]]; then
          log "SOYMUTDB_DEV_FRONTEND=preview but apps/web/dist is missing; run: pnpm build:web"
          exit 1
        fi
        launch_background web "${WEB_PORT}" \
          pnpm --filter @soymutdb/web preview --host "${BIND_HOST}" --port "${WEB_PORT}"
        ;;
      off)
        launch_background_skipped=1
        log "SOYMUTDB_DEV_FRONTEND=off; the portal was not started"
        ;;
      *)
        launch_background web "${WEB_PORT}" \
          pnpm --filter @soymutdb/web dev --host "${BIND_HOST}" --port "${WEB_PORT}"
        ;;
    esac
    log "public portal preview: http://${BIND_HOST}:${WEB_PORT}/"
    log "CNB port preview: map ${WEB_PORT}, or use CNB_VSCODE_PROXY_URI with {{port}}"
    ;;

  api-preview)
    if [[ ! -x apps/api/.venv/bin/python ]]; then
      log "missing apps/api/.venv; run: python -m venv apps/api/.venv && apps/api/.venv/bin/pip install -e packages/jobs-py -e 'apps/api[dev]'"
      exit 1
    fi
    # The data layer is what api-preview is FOR, so it is required here rather
    # than best-effort: without a database the API exits at startup, and a
    # stack trace three steps later is a worse report than this message.
    DATA_LAYER="on" data_layer_start
    # The API refuses to start without a database URL in every non-test
    # environment, so fail with an actionable message instead of a stack trace.
    if [[ -z "${SOYMUTDB_DATABASE_URL:-}" ]]; then
      log "SOYMUTDB_DATABASE_URL is required for api-preview; start the data layer first:"
      log "  docker compose --env-file /dev/null -f docker-compose.yml -f docker-compose.dev.yml --profile core up -d postgres clickhouse redis minio"
      exit 1
    fi
    launch_background api "${API_PORT}" \
      env SOYMUTDB_APP_ENV=dev SOYMUTDB_DEPLOYMENT_MODE=baseline \
      SOYMUTDB_JWT_SECRET="${SOYMUTDB_JWT_SECRET:-dev-only-secret-not-for-production}" \
      apps/api/.venv/bin/python -m uvicorn app.main:app \
      --host "${API_BIND_HOST}" --port "${API_PORT}"
    log "api preview: http://${API_BIND_HOST}:${API_PORT}/api/v1/health/live"
    ;;
esac

log "mode=${MODE} completed"

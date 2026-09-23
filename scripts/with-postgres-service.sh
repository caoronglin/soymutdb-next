#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — run a gate against a real, disposable PostgreSQL service
# =============================================================================
# Why this script exists
#   The CNB stage that runs the API + worker test tree used to declare
#   `services: - postgres:16` and expect a database. The platform accepted the
#   declaration and then started NOTHING: measured on a real build
#   (cnb-j0g-1k285hm3b), the container had no postgres DNS entry, nothing
#   listening on 5432, and `/var/run/docker.sock` absent. The declared service
#   list is therefore a no-op for anything except the two platform services
#   (docker, vscode), and the gate fell back to Testcontainers, which failed
#   116 times with:
#
#     docker.errors.DockerException: Error while fetching server API version:
#     ('Connection aborted.', FileNotFoundError(2, 'No such file or directory'))
#
#   ...a stack trace instead of "the prerequisite is missing", and 116 ERRORS
#   that read as 116 product failures.
#
# What CNB actually offers
#   * `services: [docker]` starts a real dind daemon and puts `docker` on PATH.
#     Verified: `docker info` reports a client, `/var/run/docker.sock` exists.
#   * That daemon can run a PostgreSQL container published on the *runner's*
#     loopback. `--network host` is not usable here (`--network host` is
#     accepted but the daemon's network namespace is its own), so the container
#     is started with an explicit `-p 127.0.0.1:5432:5432` publish, which the
#     gate container shares because it runs on the same Docker host.
#
# Contract
#   * Idempotent: an already-running, healthy service is reused.
#   * Fail-closed: if no ready database can be produced, this script exits
#     non-zero. It never degrades into a skip. The privacy/identity/assembly
#     matrix is a merge gate; `SOYMUTDB_TEST_DATABASE_URL` (+
#     `SOYMUTDB_DATABASE_URL` for the worker's Alembic upgrade) are exported so
#     the suite targets this database instead of Testcontainers.
#   * Explicit opt-in only: `SOYMUTDB_TEST_DATABASE_URL` already set by the
#     caller (a developer's own PostgreSQL, or the GitHub runner where
#     Testcontainers already works) is honoured untouched. This script never
#     overrides it, and never starts a container when it is present.
#
# Usage
#   bash scripts/with-postgres-service.sh -- <command> [args...]   # scoped run
#   bash scripts/with-postgres-service.sh --print-exports          # KEY=VALUE
#   bash scripts/with-postgres-service.sh --ensure                 # writes a file
#     `--print-exports` is the POSIX-safe consumption path, because a CNB stage
#     body runs under `sh` (dash) where `source` does not exist (observed:
#     `sh: 4: source: not found`, exit 127). `--ensure` additionally writes the
#     same `KEY=VALUE` lines to $SOYMUTDB_PG_ENV_FILE for callers that prefer a
#     file. Both exit non-zero when no database could be produced.
#   bash scripts/with-postgres-service.sh --self-test
#
# Environment
#   SOYMUTDB_TEST_DATABASE_URL  caller-provided database; skips the bootstrap
#   SOYMUTDB_PG_DOCKER_IMAGE    postgres image (default postgres:16-alpine)
#   SOYMUTDB_PG_PORT            loopback port (default 5432)
#   SOYMUTDB_PG_CONTAINER       container name (default soymutdb-pg-test)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "${REPO_ROOT}"

PG_IMAGE="${SOYMUTDB_PG_DOCKER_IMAGE:-postgres:16-alpine}"
PG_PORT="${SOYMUTDB_PG_PORT:-5432}"
PG_CONTAINER="${SOYMUTDB_PG_CONTAINER:-soymutdb-pg-test}"
PG_USER="soymutdb"
PG_PASSWORD="soymutdb"
PG_DB="soymutdb_testfixtures"
# Interpreter used to prove the asyncpg driver can query the database. The
# default is the API virtualenv the gate builds; `python3` is the fallback for
# a plain container (or when the gate has not built the venv yet).
READY_PYTHON="${SOYMUTDB_PG_READY_PYTHON:-${REPO_ROOT}/apps/api/.venv/bin/python}"
[[ -x "${READY_PYTHON}" ]] || READY_PYTHON="$(command -v python3 || echo python3)"
READY_TIMEOUT_SECONDS="${SOYMUTDB_PG_READY_TIMEOUT:-90}"

log() { printf '[postgres-service] %s\n' "$*" >&2; }

usage() {
  sed -n '2,51p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//'
}

# -----------------------------------------------------------------------------
# URL helpers
# -----------------------------------------------------------------------------
async_url() {
  printf 'postgresql+asyncpg://%s:%s@127.0.0.1:%s/%s' \
    "${PG_USER}" "${PG_PASSWORD}" "${PG_PORT}" "${PG_DB}"
}

sync_url() {
  printf 'postgresql://%s:%s@127.0.0.1:%s/%s' \
    "${PG_USER}" "${PG_PASSWORD}" "${PG_PORT}" "${PG_DB}"
}

container_is_running() {
  docker inspect --format '{{.State.Running}}' "${PG_CONTAINER}" 2>/dev/null | grep -q true
}

# The probe the suite's own driver must pass. `pg_isready` only proves the
# server accepts a TCP connect, and the vendor image runs a *temporary* server
# on a Unix socket during initdb that answers `pg_isready` too. Measured on a
# real build: with `pg_isready` alone the script declared the database unusable
# while PostgreSQL was already serving connections, then dumped the (healthy)
# initdb log. The probe must therefore run a query through asyncpg, the driver
# apps/api/tests/conftest.py actually uses.
DRIVER_PROBE="$(mktemp --suffix=.py)"
cleanup_probe() { rm -f "${DRIVER_PROBE}" 2>/dev/null || true; }
cat > "${DRIVER_PROBE}" <<'PY'
import asyncio
import os


async def main() -> None:
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1",
        port=int(os.environ["PROBE_PORT"]),
        user=os.environ["PROBE_USER"],
        password=os.environ["PROBE_PASSWORD"],
        database=os.environ["PROBE_DB"],
        timeout=5,
    )
    try:
        if await connection.fetchval("select 1") != 1:
            raise SystemExit("unexpected probe result")
    finally:
        await connection.close()


asyncio.run(main())
PY

driver_probe_available() {
  "${READY_PYTHON}" -c 'import asyncpg' >/dev/null 2>&1
}

driver_probe() {
  PROBE_PORT="${PG_PORT}" \
  PROBE_USER="${PG_USER}" \
  PROBE_PASSWORD="${PG_PASSWORD}" \
  PROBE_DB="${PG_DB}" \
    "${READY_PYTHON}" "${DRIVER_PROBE}" >/dev/null 2>&1
}

wait_for_ready() {
  local deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  local last_reason="no attempt was made"
  while (( SECONDS < deadline )); do
    if container_is_running \
      && docker exec "${PG_CONTAINER}" pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
      if ! driver_probe_available; then
        # No asyncpg in this interpreter (the venv may not be built yet).
        # `pg_isready` already proves the server accepts connections, so accept
        # it -- but say so, instead of implying a driver-level check ran.
        log "asyncpg is not importable by ${READY_PYTHON}; accepting pg_isready only"
        return 0
      fi
      if driver_probe; then
        return 0
      fi
      last_reason="the asyncpg probe could not query the database"
    else
      last_reason="the container is not accepting connections yet"
    fi
    sleep 2
  done
  log "readiness probe gave up after ${READY_TIMEOUT_SECONDS}s: ${last_reason}"
  return 1
}

# -----------------------------------------------------------------------------
# Body
# -----------------------------------------------------------------------------
start_service() {
  if [[ -n "${SOYMUTDB_TEST_DATABASE_URL:-}" ]]; then
    log "using caller-provided SOYMUTDB_TEST_DATABASE_URL; not starting a container"
    # Pair the caller-provided database the way the container path does: the
    # worker fixture runs the API's Alembic chain through SOYMUTDB_DATABASE_URL.
    # Without this, `--print-exports` dies on `SOYMUTDB_DATABASE_URL: unbound
    # variable` under `set -u` even though the caller supplied a usable URL,
    # which is exactly how the local/CI external-database path is meant to work.
    if [[ -z "${SOYMUTDB_DATABASE_URL:-}" ]]; then
      export SOYMUTDB_DATABASE_URL="${SOYMUTDB_TEST_DATABASE_URL}"
    fi
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    log "docker CLI is unavailable: this stage must declare \`services: [docker]\`"
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    log "the docker daemon is unreachable: this stage must declare \`services: [docker]\`"
    return 1
  fi

  if container_is_running "${PG_CONTAINER}"; then
    log "reusing running container ${PG_CONTAINER}"
  else
    docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
    log "starting ${PG_IMAGE} as ${PG_CONTAINER} on 127.0.0.1:${PG_PORT}"
    docker run -d --name "${PG_CONTAINER}" \
      -p "127.0.0.1:${PG_PORT}:5432" \
      -e "POSTGRES_USER=${PG_USER}" \
      -e "POSTGRES_PASSWORD=${PG_PASSWORD}" \
      -e "POSTGRES_DB=${PG_DB}" \
      "${PG_IMAGE}" >/dev/null
  fi

  if ! wait_for_ready; then
    log "PostgreSQL did not become ready; container state follows"
    docker ps -a --filter "name=^/${PG_CONTAINER}$" >&2 2>&1 || true
    docker logs "${PG_CONTAINER}" >&2 2>&1 | tail -40 || true
    cleanup_probe
    return 1
  fi
  cleanup_probe

  export SOYMUTDB_TEST_DATABASE_URL
  SOYMUTDB_TEST_DATABASE_URL="$(async_url)"
  # The worker fixture runs the API's Alembic chain through the sync driver.
  export SOYMUTDB_DATABASE_URL
  SOYMUTDB_DATABASE_URL="$(sync_url)"
  # Printed without the password: this line lands in the build log.
  log "ready: postgresql+asyncpg://127.0.0.1:${PG_PORT}/${PG_DB} (user ${PG_USER})"
}

stop_service() {
  cleanup_probe
  if [[ -n "${SOYMUTDB_PG_KEEP_CONTAINER:-}" ]]; then
    log "keeping ${PG_CONTAINER} (SOYMUTDB_PG_KEEP_CONTAINER set)"
    return 0
  fi
  docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
}

self_test() {
  # The rule that must never regress: a database the caller already provided is
  # used verbatim, and nothing is started. The probe evaluates the real
  # `start_service` in a throwaway shell, so the assertion cannot pass against a
  # re-implementation that merely agrees with this one.
  local failures=0
  local explicit="postgresql+asyncpg://tester:pw@db.example.internal:6000/explicit_db"

  # `main "$@"` at the bottom would dispatch when the file is sourced, so the
  # dispatch line is stripped before the definitions are evaluated.
  local definitions
  definitions="$(sed 's|^main "\$@"$||' "${BASH_SOURCE[0]}")"

  local observed
  observed="$(
    SOYMUTDB_TEST_DATABASE_URL="${explicit}" bash -c '
      eval "${1}"
      start_service >&2
      printf "%s" "${SOYMUTDB_TEST_DATABASE_URL}"
    ' _ "${definitions}"
  )"
  if [[ "${observed}" != "${explicit}" ]]; then
    log "self-test: an explicit SOYMUTDB_TEST_DATABASE_URL was not honoured"
    log "self-test: expected ${explicit}"
    log "self-test: got      ${observed}"
    failures=$((failures + 1))
  fi

  # With no docker on PATH and no caller-provided URL, the switch must fail
  # closed instead of continuing into a skip-green suite.
  local rc=0
  PATH="/usr/bin:/bin" SOYMUTDB_TEST_DATABASE_URL="" \
    bash "${BASH_SOURCE[0]}" --start-only >/dev/null 2>&1 || rc=$?
  if (( rc == 0 )); then
    log "self-test: a missing docker daemon was reported as success"
    failures=$((failures + 1))
  fi

  (( failures == 0 )) || return 1
  printf 'postgres-service self-test passed\n'
}

main() {
  local command="${1:-}"
  case "${command}" in
    --self-test) self_test ;;
    --start-only)
      # Used by `--self-test` (and by callers that only want the side effects in
      # their own environment). Proves the fail-closed path with the real code.
      start_service
      ;;
    --print-exports|--ensure)
      # One implementation for both names so they cannot drift. `--print-exports`
      # is the POSIX-safe consumption path for a `sh` stage script:
      #   env $(bash scripts/with-postgres-service.sh --print-exports) pytest ...
      # `--ensure` additionally writes the identical lines to $SOYMUTDB_PG_ENV_FILE
      # (still NOT shell `export` statements: `source` does not exist in dash).
      # That file is a convenience copy for a bash caller that wants to source
      # it; scripts/verify-backend-tests.sh -- the only gate -- consumes the
      # printed lines, so neither form is silently ignored.
      # The container is left running; the caller owns its lifetime.
      if [[ "${command}" == "--ensure" ]]; then
        SOYMUTDB_PG_ENV_FILE="${SOYMUTDB_PG_ENV_FILE:-${TMPDIR:-/tmp}/soymutdb-pg-test.env}"
        export SOYMUTDB_PG_ENV_FILE
      fi
      start_service
      exports="$(
        printf 'SOYMUTDB_TEST_DATABASE_URL=%s\n' "${SOYMUTDB_TEST_DATABASE_URL}"
        printf 'SOYMUTDB_DATABASE_URL=%s\n' "${SOYMUTDB_DATABASE_URL}"
        printf 'SOYMUTDB_RUN_POSTGRES_INTEGRATION=1\n'
      )"
      printf '%s\n' "${exports}"
      if [[ "${command}" == "--ensure" ]]; then
        printf '%s\n' "${exports}" > "${SOYMUTDB_PG_ENV_FILE}"
        log "wrote ${SOYMUTDB_PG_ENV_FILE}"
      fi
      ;;
    --)
      shift
      [[ $# -gt 0 ]] || { log "missing command after --"; exit 2; }
      trap stop_service EXIT
      start_service
      "$@"
      ;;
    -h|--help|"") usage ;;
    *) log "unknown argument: ${command}"; usage >&2; exit 2 ;;
  esac
}

main "$@"

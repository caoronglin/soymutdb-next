#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — build and run the PRODUCTION topology from the local checkout
# =============================================================================
# The production Compose file only accepts release images:
#
#     image: ${API_IMAGE_REF:?API_IMAGE_REF is required as image@sha256 - …}
#
# That fail-closed requirement is correct for a release and useless for the three
# things an operator actually wants to do off the release train:
#
#   1. build the images from this checkout and start the whole stack;
#   2. run the topology without touching a registry at all;
#   3. reproduce the production service graph locally without the development
#      overlay's bind mounts and reload flags.
#
# This script is the missing half. It:
#
#   * builds every release image with the names scripts/list-images.sh declares,
#     using the SAME Dockerfiles the release pipeline builds, so a local stack
#     cannot pass while the release build fails;
#   * exports `<NAME>_IMAGE` for each service, which
#     docker-compose.local.yml uses to discard the digest requirement;
#   * runs `docker compose` with the caller's arguments plus an explicit
#     `--env-file`, so a stale `.env` cannot silently change the stack.
#
# Usage
#   bash scripts/compose-local.sh build                 # build the 8 images
#   bash scripts/compose-local.sh up -d                 # start the whole stack
#   bash scripts/compose-local.sh up -d postgres clickhouse redis minio
#   bash scripts/compose-local.sh down
#   bash scripts/compose-local.sh ps
#   bash scripts/compose-local.sh --tag 2026.09.12 up -d
#
# Env
#   SOYMUTDB_LOCAL_IMAGE_TAG   tag for the locally built images (default: local)
#   SOYMUTDB_LOCAL_ENV_FILE    env file for compose (default: <repo>/.env if it
#                              exists, else /dev/null). A non-empty value there
#                              (like a non-empty value exported in the shell)
#                              satisfies the production `${…:?…}` references; an
#                              empty `NAME=` does not, so the local development
#                              default is used instead. /dev/null reads no `.env`
#                              at all.
#   SOYMUTDB_LOCAL_PROFILES    comma-separated Compose profiles (default: the
#                              shell COMPOSE_PROFILES, else the env file's
#                              COMPOSE_PROFILES, else `core`)
#   SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS
#                              extra `docker build` flags (e.g. --cache-from)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck source=scripts/list-images.sh
source "${REPO_ROOT}/scripts/list-images.sh"

local_image_tag() { printf '%s\n' "${SOYMUTDB_LOCAL_IMAGE_TAG:-local}"; }

usage() {
  sed -n '2,50p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

log() { printf '[compose-local] %s\n' "$*" >&2; }

IMAGE_TAG="$(local_image_tag)"

# The env file: never read a stray .env implicitly. `docker compose` would
# otherwise pick the one next to the first -f file, which is how a leftover
# `.env` from `deploy/.env.example` changes a stack behind the operator's back.
env_file() {
  if [[ -n "${SOYMUTDB_LOCAL_ENV_FILE:-}" ]]; then
    printf '%s\n' "${SOYMUTDB_LOCAL_ENV_FILE}"
  elif [[ -f "${REPO_ROOT}/.env" ]]; then
    printf '%s\n' "${REPO_ROOT}/.env"
  else
    printf '%s\n' /dev/null
  fi
}

# Compose variables consumed by docker-compose.local.yml. `MIGRATE_IMAGE` and
# friends are the local-build counterparts of the `*_IMAGE_REF` digests.
export_api_images() {
  export API_IMAGE="soymutdb-api:${IMAGE_TAG}"
  export WORKER_IMAGE="soymutdb-worker:${IMAGE_TAG}"
  export MCP_IMAGE="soymutdb-mcp:${IMAGE_TAG}"
  export MIGRATE_IMAGE="soymutdb-migrate:${IMAGE_TAG}"
  export MIGRATE_CLICKHOUSE_IMAGE="soymutdb-migrate-clickhouse:${IMAGE_TAG}"
}

# Names with a NON-EMPTY value in the Compose env file. An empty entry
# (`POSTGRES_PASSWORD=` or `POSTGRES_PASSWORD=""`) is not a value Compose can
# interpolate: `${NAME:?…}` fails on an empty string exactly as it does on an
# unset one, so the wrapper must fall back to the development default rather
# than treat the name as satisfied. COMPOSE_PROFILES is read as a value (a
# comma-separated list, not a flag) and exposed separately.
declare -A COMPOSE_ENV_FILE_VARIABLES=()
COMPOSE_ENV_FILE_COMPOSE_PROFILES=""
load_env_file_variables() {
  local file="$1" line name value
  COMPOSE_ENV_FILE_VARIABLES=()
  COMPOSE_ENV_FILE_COMPOSE_PROFILES=""
  [[ -f "${file}" ]] || return 0
  # `|| [[ -n ... ]]` keeps a final assignment line without a trailing newline;
  # that is legal Compose env-file syntax and must not be dropped.
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      name="${BASH_REMATCH[2]}"
      value="${BASH_REMATCH[3]}"
      # Compose's dotenv format: a ` # comment` after whitespace is not part of
      # an unquoted value, and one layer of matching quotes is removed.
      value="${value%$'\r'}"
      if [[ "${value}" =~ ^(.*[^[:space:]])?[[:space:]]+#.*$ ]]; then
        value="${BASH_REMATCH[1]}"
      fi
      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      if [[ ${#value} -ge 2 && "${value:0:1}" == "${value: -1}" &&
            ( "${value:0:1}" == '"' || "${value:0:1}" == "'" ) ]]; then
        value="${value:1:${#value}-2}"
      fi
      [[ -n "${value}" ]] || continue
      COMPOSE_ENV_FILE_VARIABLES["${name}"]=1
      if [[ "${name}" == "COMPOSE_PROFILES" ]]; then
        COMPOSE_ENV_FILE_COMPOSE_PROFILES="${value}"
      fi
    fi
  done < "${file}"
}

# Compose interpolates every input file before it applies docker-compose.local.yml.
# Supply safe local values for every production `:?` reference so the release
# file can be parsed without weakening its fail-fast behaviour when invoked
# directly. A non-empty caller value, or a non-empty value in the env file
# Compose reads, remains authoritative. Empty never satisfies a `:?` reference.
set_compose_default() {
  local name="$1" fallback="$2"
  # A non-empty shell value wins outright.
  if [[ -n "${!name:-}" ]]; then
    return 0
  fi
  # The env file has a usable value, but Compose gives the shell environment
  # precedence, so a leftover empty shell entry (`POSTGRES_PASSWORD=`) would
  # mask it and re-trigger `${NAME:?…}`. Drop the empty entry so the file value
  # applies; the value itself is never copied into this process' environment.
  if [[ -n "${COMPOSE_ENV_FILE_VARIABLES[${name}]:-}" ]]; then
    unset "${name}" 2>/dev/null || true
    return 0
  fi
  export "${name}=${fallback}"
}

set_local_compose_defaults() {
  load_env_file_variables "$1"
  set_compose_default API_IMAGE_REF "${API_IMAGE}"
  set_compose_default WORKER_IMAGE_REF "${WORKER_IMAGE}"
  set_compose_default MIGRATE_IMAGE_REF "${MIGRATE_IMAGE}"
  set_compose_default MIGRATE_CLICKHOUSE_IMAGE_REF "${MIGRATE_CLICKHOUSE_IMAGE}"
  set_compose_default MCP_IMAGE_REF "${MCP_IMAGE}"
  set_compose_default JBROWSE_IMAGE_REF "soymutdb-jbrowse:${IMAGE_TAG}"
  set_compose_default POSTGRES_PASSWORD soymutdb_dev_password
  set_compose_default CLICKHOUSE_PASSWORD soymutdb_dev_password
  set_compose_default REDIS_PASSWORD soymutdb_dev_password
  set_compose_default MINIO_ROOT_USER soymutdb_dev
  set_compose_default MINIO_ROOT_PASSWORD soymutdb_dev_password
  set_compose_default GRAFANA_PASSWORD soymutdb_dev_password
  set_compose_default SOYMUTDB_MCP_API_TOKEN soymutdb_dev_mcp_token
}

# Resolve the explicit `--profile` flags. Precedence, highest first:
#   1. SOYMUTDB_LOCAL_PROFILES (the wrapper's own switch)
#   2. a non-empty shell COMPOSE_PROFILES
#   3. a non-empty COMPOSE_PROFILES from the selected env file
#   4. `core`
# Compose also reads COMPOSE_PROFILES from the selected env file and unions it
# with any `--profile` flags, so the resolved value is also exported into the
# child environment (the shell overrides the env file). That keeps the explicit
# flags and the stack Compose actually starts in agreement, and drops the env
# file's list whenever SOYMUTDB_LOCAL_PROFILES overrides it.
resolve_profiles() {
  local profiles="${SOYMUTDB_LOCAL_PROFILES:-${COMPOSE_PROFILES:-}}"
  if [[ -z "${profiles}" ]]; then
    profiles="${COMPOSE_ENV_FILE_COMPOSE_PROFILES:-core}"
  fi
  printf '%s\n' "${profiles}"
}

compose() {
  local file
  file="$(env_file)"
  set_local_compose_defaults "${file}"
  local profiles
  profiles="$(resolve_profiles)"
  # Mask any COMPOSE_PROFILES in the env file: the shell environment wins, so
  # Compose enables exactly the list resolved above (see resolve_profiles).
  export COMPOSE_PROFILES="${profiles}"
  # `--profile` takes one profile per flag, so a comma list is split.
  local args=(
    docker compose
    --project-directory "${REPO_ROOT}"
    --env-file "${file}"
    -f "${REPO_ROOT}/docker-compose.yml"
    -f "${REPO_ROOT}/docker-compose.local.yml"
  )
  local profile
  IFS=',' read -r -a profile_list <<< "${profiles}"
  for profile in "${profile_list[@]}"; do
    [[ -n "${profile}" ]] || continue
    args+=(--profile "${profile}")
  done
  args+=("$@")
  log "${args[*]}"
  "${args[@]}"
}

build_images() {
  local command extra=()
  read -r -a extra <<< "${SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS:-}"
  while IFS='|' read -r name context dockerfile; do
    command=(docker build -f "${dockerfile}" -t "soymutdb-${name}:${IMAGE_TAG}")
    if [[ "${#extra[@]}" -gt 0 ]]; then
      command+=("${extra[@]}")
    fi
    command+=("${context}")
    log "+ ${command[*]}"
    "${command[@]}"
  done < <(soymutdb_image_entry)
}

export_api_images

if [[ "${1:-}" == "--tag" ]]; then
  [[ -n "${2:-}" ]] || { echo "--tag requires a value" >&2; exit 2; }
  export SOYMUTDB_LOCAL_IMAGE_TAG="$2"
  IMAGE_TAG="$2"
  shift 2
  export_api_images
fi

command="${1:-}"
case "${command}" in
  ""|-h|--help)
    usage
    exit 0
    ;;
  build)
    shift
    build_images "$@"
    ;;
  config|up|down|ps|logs|stop|start|restart|run|exec|pull|images|top|wait)
    shift
    compose "${command}" "$@"
    ;;
  *)
    echo "unknown command: ${command}" >&2
    usage >&2
    exit 2
    ;;
esac

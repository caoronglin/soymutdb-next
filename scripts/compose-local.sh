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
#   * exports `<NAME>_IMAGE` for each service, which the `x-service-local-*`
#     anchors in docker-compose.yml use to discard the digest requirement;
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
#                              exists, else /dev/null). Pass an explicit path to
#                              inject real credentials; /dev/null means the
#                              development defaults inside the compose file are
#                              used and no `.env` is read.
#   SOYMUTDB_LOCAL_PROFILES    comma-separated Compose profiles (default: the
#                              value of COMPOSE_PROFILES, else `core`)
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

# Compose variables for the `x-service-local-*` anchors. `MIGRATE_IMAGE` and
# friends are the local-build counterparts of the `*_IMAGE_REF` digests.
export_api_images() {
  export API_IMAGE="soymutdb-api:${IMAGE_TAG}"
  export WORKER_IMAGE="soymutdb-worker:${IMAGE_TAG}"
  export MCP_IMAGE="soymutdb-mcp:${IMAGE_TAG}"
  export MIGRATE_IMAGE="soymutdb-migrate:${IMAGE_TAG}"
  export MIGRATE_CLICKHOUSE_IMAGE="soymutdb-migrate-clickhouse:${IMAGE_TAG}"
}

compose() {
  local file
  file="$(env_file)"
  local profiles="${SOYMUTDB_LOCAL_PROFILES:-${COMPOSE_PROFILES:-core}}"
  # `--profile` takes one profile per flag, so a comma list is split.
  local args=(
    docker compose
    --project-directory "${REPO_ROOT}"
    --env-file "${file}"
    -f "${REPO_ROOT}/docker-compose.yml"
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

#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — the release image set, in one place
# =============================================================================
# Eight scripts used to agree on "the images" by repeating the same literals:
#
#   scripts/build-release-image.sh   docker build -f <dockerfile> -t soymutdb-<n>:ci-<arch>
#   scripts/release-contract.golden.sh  RUNTIME_IMAGES=(api worker mcp jbrowse)
#   scripts/check-dockerfile-copy.sh   the Dockerfiles whose COPY sources exist
#   scripts/test_worker_image_boundary.py, scripts/dependency_governance.py, …
#
# Adding a service therefore meant editing a build command, an export array, a
# COPY guard and the release manifest validator, and getting all four right.
# The failure mode of one missed edit is a release that silently ships seven of
# eight images, so the set is now enumerated HERE and every consumer source-s this
# file:
#
#   source scripts/list-images.sh
#   for entry in "${SOYMUTDB_IMAGES[@]}"; do ...; done
#
# Each entry is `<name>|<context>|<dockerfile>`:
#
#   name      the local tag suffix. The verify pipeline builds
#             `soymutdb-<name>:ci-<arch>`, the publisher re-tags it and pushes
#             `<registry>/<owner>/<remote-name>`.
#   context   the docker build context, relative to the repository root. A `.`
#             context is what lets infra/docker/Dockerfile.* COPY the workspace
#             manifests and `packages/jobs-py`; apps/mcp-server is the one image
#             that builds from its own directory.
#   dockerfile
#             path relative to the repository root (NOT to the context), so it
#             can be passed to `docker build -f` and read by the COPY guard
#             without a second mapping.
#
# `remote_name` is the registry-side repository name. It differs from `name`
# only for the MCP server (`mcp` locally, `mcp-server` remotely), because that
# was the pre-existing published name and a rename would be a breaking change to
# every consumer's image reference.
#
# Not listed on purpose:
#   * apps/jbrowse/Dockerfile targets `nginx` through the local `base` stage and
#     is built with context `.`, so `entry.context` is `.` even though the file
#     lives under apps/ — the pair above records that.
#   * prometheus / grafana / nginx run upstream images directly.
#   * web / admin static bundles are published as static artifacts by
#     scripts/build-pages-artifact.sh, not as OCI images (the Dockerfiles under
#     infra/docker/ remain for the Compose profiles that opt into them).
# =============================================================================

# shellcheck disable=SC2034  # consumed by the sourcing scripts
SOYMUTDB_IMAGES=(
  "api|.|infra/docker/Dockerfile.api"
  "worker|.|infra/docker/Dockerfile.worker"
  "migrate|.|infra/docker/Dockerfile.migrate"
  "migrate-clickhouse|.|infra/docker/Dockerfile.migrate-clickhouse"
  "mcp|apps/mcp-server|apps/mcp-server/Dockerfile"
  "jbrowse|.|apps/jbrowse/Dockerfile"
  "web|.|infra/docker/Dockerfile.web"
  "admin|.|infra/docker/Dockerfile.admin"
)

# The remote repository name for a local image name.
soymutdb_remote_image_name() {
  case "$1" in
    mcp) printf 'mcp-server\n' ;;
    *) printf '%s\n' "$1" ;;
  esac
}

soymutdb_image_names() {
  local entry
  for entry in "${SOYMUTDB_IMAGES[@]}"; do
    printf '%s\n' "${entry%%|*}"
  done
}

soymutdb_image_dockerfiles() {
  local entry rest
  for entry in "${SOYMUTDB_IMAGES[@]}"; do
    rest="${entry#*|}"
    printf '%s\n' "${rest#*|}"
  done
}

# `name|context|dockerfile` -> the three fields, for `while IFS='|' read`.
soymutdb_image_entry() {
  printf '%s\n' "${SOYMUTDB_IMAGES[@]}"
}

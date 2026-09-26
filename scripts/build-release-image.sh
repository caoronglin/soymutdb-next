#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — build, runtime-smoke, scan, SBOM, and export one platform's images
# =============================================================================
# Single source for the delivery image verification sequence. Both the GitHub
# mirror workflow and the CNB `docker-images` pipeline call this script, so the
# build/runtime/vulnerability evidence is produced identically everywhere.
#
# Contract (do not reorder without updating docs/ops/ci-cd.md):
#   1. supply-chain lock verification + Dockerfile COPY guard
#   2. build every release image           (hard gate)
#   3. runtime smoke for every image       (hard gate)
#   4. assert the built architecture matches the requested platform (hard gate)
#   5. Trivy CRITICAL/HIGH scan            (hard gate, .trivyignore triaged)
#   6. SPDX SBOM for every image
#   7. export a compressed, checksummed image package for the publisher
#
# The image set is enumerated once, in scripts/list-images.sh, and this script
# (plus the publisher, the COPY guard and the contract tests) iterates it instead
# of repeating `api worker mcp jbrowse` in five places. Adding an image means one
# line there.
#
# Build caching
#   With a BuildKit-capable daemon (docker >= 23, the platform default) the
#   multi-stage Dockerfiles cache per instruction, so an unrelated source change
#   rebuilds only the COPY layers. Pass
#   `SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS="--cache-from=type=registry,ref=..."` to
#   opt into a shared registry cache; the flag is never implied, because a
#   registry cache is a supply-chain input and has to be a reviewed decision.
#
# Usage:
#   bash scripts/build-release-image.sh                 # current arch
#   SOYMUTDB_CI_ARCH=arm64 bash scripts/build-release-image.sh
#
# Env:
#   SOYMUTDB_CI_ARCH             amd64 | arm64 (default: host architecture)
#   SOYMUTDB_CI_EXPORT           1 to export the package (default 1)
#   SOYMUTDB_CI_OUTPUT_DIR       export directory (default validated-runtime-images)
#   SOYMUTDB_CI_SKIP_COMPOSE     1 to skip the Docker-only Compose acceptance
#   SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS
#                                extra `docker build` flags (e.g. a registry
#                                `--cache-from`); empty by default
#   TRIVY_BIN                    path to trivy (default: `trivy`, else docker)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

host_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo amd64 ;;
    aarch64|arm64) echo arm64 ;;
    *) uname -m ;;
  esac
}

ARCH="${SOYMUTDB_CI_ARCH:-$(host_arch)}"
PLATFORM="linux/${ARCH}"
OUTPUT_DIR="${SOYMUTDB_CI_OUTPUT_DIR:-validated-runtime-images}"
EXPORT="${SOYMUTDB_CI_EXPORT:-1}"

# shellcheck source=scripts/list-images.sh
source "${REPO_ROOT}/scripts/list-images.sh"
IMAGE_NAMES=()
while IFS= read -r name; do
  IMAGE_NAMES+=("${name}")
done < <(soymutdb_image_names)

# `docker build` flags that apply to every image. Deliberately EMPTY by default:
# a registry cache is an external input to the build, so opting in is an explicit
# operator decision (see the header). Word-split on purpose, so the variable can
# carry several flags.
read -r -a DOCKER_BUILD_EXTRA_ARGS <<< "${SOYMUTDB_CI_DOCKER_BUILD_EXTRA_ARGS:-}"

step() { printf '\n==> %s\n' "$*"; }

# `docker build` for one entry of scripts/list-images.sh, with the optional extra
# args appended. Kept as one function so the local tag can never drift from the
# tag the publisher loads.
build_image() {
  local name="$1" context="$2" dockerfile="$3"
  local command=(docker build -f "${dockerfile}" -t "soymutdb-${name}:ci-${ARCH}")
  if [[ "${#DOCKER_BUILD_EXTRA_ARGS[@]}" -gt 0 ]]; then
    command+=("${DOCKER_BUILD_EXTRA_ARGS[@]}")
  fi
  command+=("${context}")
  echo "+ ${command[*]}"
  "${command[@]}"
}

# Read the current architecture of one built image.
image_arch() {
  docker image inspect --format '{{.Architecture}}' "soymutdb-$1:ci-${ARCH}"
}

step "Verify Python dependency locks"
bash scripts/check-supply-chain.sh

step "Verify Dockerfile COPY sources exist"
bash scripts/check-dockerfile-copy.sh

if [[ "${SOYMUTDB_CI_SKIP_COMPOSE:-0}" != "1" ]]; then
  step "Validate production Compose profiles (Docker-only gate)"
  bash scripts/ci-job-steps.sh run compose-acceptance
fi

step "Build release images (${PLATFORM})"
# The image set, its build contexts and its Dockerfiles come from
# scripts/list-images.sh; the jbrowse Dockerfile reads the repo .npmrc for its
# internal pnpm install; every image build is self-contained and none uses the CI
# registry override.
while IFS='|' read -r image_name image_context image_dockerfile; do
  build_image "${image_name}" "${image_context}" "${image_dockerfile}"
done < <(soymutdb_image_entry)

step "Smoke test API runtime image (hard gate)"
docker run --rm \
  -e SOYMUTDB_DATABASE_URL=postgresql+asyncpg://ci:ci@database.invalid/soymutdb \
  -e SOYMUTDB_REDIS_URL=redis://cache.invalid:6379/0 \
  -e SOYMUTDB_S3_ENDPOINT=http://storage.invalid:9000 \
  -e SOYMUTDB_S3_ACCESS_KEY=ci-runtime-access \
  -e SOYMUTDB_S3_SECRET_KEY=ci-runtime-secret \
  -e SOYMUTDB_JWT_SECRET=ci-runtime-smoke-jwt-secret-0123456789abcdef \
  -e SOYMUTDB_CORS_ORIGINS=https://runtime-smoke.invalid \
  -e SOYMUTDB_ANALYTICS_IP_SALT=ci-runtime-smoke-analytics-ip-salt-0123456789 \
  "soymutdb-api:ci-${ARCH}" \
  python -c "import soymutdb_jobs; from app.main import app; assert app.title == 'SoyMutDB'; print('API app import OK')"

step "Smoke test Worker task registry (hard gate)"
docker run --rm \
  --volume "${REPO_ROOT}/scripts/check-worker-task-registry.py:/tmp/check-worker-task-registry.py:ro" \
  "soymutdb-worker:ci-${ARCH}" \
  python /tmp/check-worker-task-registry.py

step "Smoke test MCP runtime image (hard gate)"
docker run --rm -e SOYMUTDB_MCP_API_TOKEN=ci-runtime-smoke-token \
  "soymutdb-mcp:ci-${ARCH}" \
  python -c "from mcp_server.server import mcp; assert mcp is not None; print('MCP server import OK')"

step "Smoke test JBrowse runtime image (hard gate)"
docker run --rm "soymutdb-jbrowse:ci-${ARCH}" \
  sh -ec 'nginx -t && test -s /usr/share/nginx/html/index.html'

step "Smoke test web runtime image (hard gate)"
docker run --rm "soymutdb-web:ci-${ARCH}" \
  sh -ec 'nginx -t && test -s /usr/share/nginx/html/index.html'

step "Smoke test admin runtime image (hard gate)"
docker run --rm "soymutdb-admin:ci-${ARCH}" \
  sh -ec 'nginx -t && test -s /usr/share/nginx/html/index.html'

# The migration images are what a production upgrade actually runs, so "the
# entrypoint exists" is not enough: assert the two properties an upgrade depends
# on and that have broken before --
#   1. the image carries the migration runner the Compose service invokes;
#   2. `alembic heads` resolves offline, i.e. the migrations directory is really
#      inside the image and the environment can load it.
step "Smoke test migrate runtime image (hard gate)"
docker run --rm \
  -e SOYMUTDB_DATABASE_URL=postgresql+asyncpg://ci:ci@database.invalid/soymutdb \
  -e SOYMUTDB_JWT_SECRET=ci-runtime-smoke-jwt-secret-0123456789abcdef \
  -e SOYMUTDB_CORS_ORIGINS=https://runtime-smoke.invalid \
  -e SOYMUTDB_ANALYTICS_IP_SALT=ci-runtime-smoke-analytics-ip-salt-0123456789 \
  "soymutdb-migrate:ci-${ARCH}" \
  sh -ec 'test -f alembic.ini && alembic heads >/dev/null && echo "Alembic heads resolved"'

step "Smoke test migrate-clickhouse runtime image (hard gate)"
docker run --rm "soymutdb-migrate-clickhouse:ci-${ARCH}" \
  sh -ec 'python /opt/soymutdb/migrate_clickhouse_lib.py --help >/dev/null 2>&1 || true; test -s /opt/soymutdb/migrate_clickhouse_lib.py && test -s /opt/soymutdb/upgrade_variant_facts_schema.sql && test -x /opt/soymutdb/migrate-clickhouse.sh && echo "ClickHouse migration payload present"'

step "Assert actual native image architecture (hard gate)"
for image_name in "${IMAGE_NAMES[@]}"; do
  image="soymutdb-${image_name}:ci-${ARCH}"
  actual="$(image_arch "${image_name}")"
  test "${actual}" = "${ARCH}"
  echo "verified ${image}: ${actual}"
done

trivy_scan() {
  local image="$1" report="$2"
  if command -v trivy >/dev/null 2>&1; then
    trivy image --format sarif --output "${report}" \
      --severity CRITICAL,HIGH --ignore-unfixed=false --exit-code 1 \
      --ignorefile .trivyignore --scanners vuln --quiet "${image}"
    return
  fi
  # Fall back to the pinned Trivy container so the same policy applies without a
  # pre-installed binary on a bare runner.
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${REPO_ROOT}:/workspace" -w /workspace \
    aquasecurity/trivy:0.61.0 image --format sarif --output "${report}" \
    --severity CRITICAL,HIGH --ignore-unfixed=false --exit-code 1 \
    --ignorefile .trivyignore --scanners vuln --quiet "${image}"
}

trivy_sbom() {
  local image="$1" document="$2"
  if command -v trivy >/dev/null 2>&1; then
    trivy image --format spdx-json --output "${document}" --quiet "${image}"
    return
  fi
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${REPO_ROOT}:/workspace" -w /workspace \
    aquasecurity/trivy:0.61.0 image --format spdx-json --output "${document}" \
    --quiet "${image}"
}

# CRITICAL/HIGH vulnerabilities in any release image fail this script. Every
# exception must be explicitly triaged in .trivyignore.
mkdir -p "${OUTPUT_DIR}"

# Scan and SBOM every image of the set. The report names follow the local image
# names, which is the same vocabulary the publisher reads in
# `image-ids-<arch>.txt`, so a report can never describe a different image than
# the one it is checked against.
for image_name in "${IMAGE_NAMES[@]}"; do
  step "Trivy scan ${image_name} image (hard gate)"
  trivy_scan "soymutdb-${image_name}:ci-${ARCH}" "trivy-${image_name}.sarif"

  step "Generate ${image_name} SPDX SBOM"
  trivy_sbom "soymutdb-${image_name}:ci-${ARCH}" "${OUTPUT_DIR}/sbom-${image_name}-${ARCH}.spdx.json"
done

if [[ "${EXPORT}" != "1" ]]; then
  echo "export skipped (SOYMUTDB_CI_EXPORT=${EXPORT})"
  exit 0
fi

step "Export validated runtime images"
mkdir -p "${OUTPUT_DIR}"
validated_images=()
for image_name in "${IMAGE_NAMES[@]}"; do
  validated_images+=("soymutdb-${image_name}:ci-${ARCH}")
done
: > "validated-runtime-images-${ARCH}.txt"
for image in "${validated_images[@]}"; do
  image_id="$(docker image inspect --format '{{.Id}}' "${image}")"
  printf '%s %s\n' "${image}" "${image_id}" >> "validated-runtime-images-${ARCH}.txt"
done
mv "validated-runtime-images-${ARCH}.txt" "${OUTPUT_DIR}/image-ids-${ARCH}.txt"
printf '%s\n' "${PLATFORM}" > "${OUTPUT_DIR}/platform.txt"
# The revision these images were built from. The publisher reads it to prove it
# is signing a coherent release: two packages from different builds would still
# be "made of verified bytes" while describing no single revision.
# The x86 build resolves it from the checkout, which is the tree it just built.
REVISION="${SOURCE_REVISION:-${CNB_COMMIT:-$(git rev-parse HEAD)}}"
printf '%s\n' "${REVISION}" > "${OUTPUT_DIR}/revision.txt"
# Keep the CNB event *type* alongside this package's revision. CNB_EVENT is a
# type such as push/tag_push, not a unique run identifier; the revision and the
# same-event await/resolve graph provide run-level provenance.
EVENT_TYPE="${SOURCE_EVENT:-${CNB_EVENT:-local}}"
printf '%s\n' "${EVENT_TYPE}" > "${OUTPUT_DIR}/source-event.txt"
docker save "${validated_images[@]}" | gzip -1 > "${OUTPUT_DIR}/soymutdb-runtime-images-${ARCH}.tar.gz"

step "validate-runtime-images (checksums)"
(
  cd "${OUTPUT_DIR}"
  sha256sum "soymutdb-runtime-images-${ARCH}.tar.gz" \
    "image-ids-${ARCH}.txt" platform.txt revision.txt source-event.txt sbom-*-"${ARCH}".spdx.json > SHA256SUMS
  sha256sum -c SHA256SUMS
)

printf '\nimage verification passed for %s\n' "${PLATFORM}"

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
#   2. build API / Worker / MCP / JBrowse  (hard gate)
#   3. runtime smoke for every image       (hard gate)
#   4. assert the built architecture matches the requested platform (hard gate)
#   5. Trivy CRITICAL/HIGH scan            (hard gate, .trivyignore triaged)
#   6. SPDX SBOM for every image
#   7. export a compressed, checksummed image package for the publisher
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

step() { printf '\n==> %s\n' "$*"; }

step "Verify Python dependency locks"
bash scripts/check-supply-chain.sh

step "Verify Dockerfile COPY sources exist"
bash scripts/check-dockerfile-copy.sh

if [[ "${SOYMUTDB_CI_SKIP_COMPOSE:-0}" != "1" ]]; then
  step "Validate production Compose profiles (Docker-only gate)"
  bash scripts/ci-job-steps.sh run compose-acceptance
fi

step "Build release images (${PLATFORM})"
# The jbrowse Dockerfile reads the repo .npmrc for its internal pnpm install;
# the image build is self-contained and does not use the CI registry override.
docker build -f infra/docker/Dockerfile.api -t "soymutdb-api:ci-${ARCH}" .
docker build -f infra/docker/Dockerfile.worker -t "soymutdb-worker:ci-${ARCH}" .
docker build -f apps/mcp-server/Dockerfile -t "soymutdb-mcp:ci-${ARCH}" apps/mcp-server
docker build -f apps/jbrowse/Dockerfile -t "soymutdb-jbrowse:ci-${ARCH}" .

step "Smoke test API runtime image (hard gate)"
docker run --rm \
  -e SOYMUTDB_DATABASE_URL=postgresql+asyncpg://ci:ci@database.invalid/soymutdb \
  -e SOYMUTDB_REDIS_URL=redis://cache.invalid:6379/0 \
  -e SOYMUTDB_S3_ENDPOINT=http://storage.invalid:9000 \
  -e SOYMUTDB_S3_ACCESS_KEY=ci-runtime-access \
  -e SOYMUTDB_S3_SECRET_KEY=ci-runtime-secret \
  -e SOYMUTDB_JWT_SECRET=ci-runtime-smoke-jwt-secret-0123456789abcdef \
  -e SOYMUTDB_CORS_ORIGINS=https://runtime-smoke.invalid \
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

step "Assert actual native image architecture (hard gate)"
for image_name in api worker mcp jbrowse; do
  image="soymutdb-${image_name}:ci-${ARCH}"
  actual="$(docker image inspect --format '{{.Architecture}}' "${image}")"
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
step "Trivy scan API image (hard gate)"
trivy_scan "soymutdb-api:ci-${ARCH}" "trivy-api.sarif"

step "Trivy scan Worker image (hard gate)"
trivy_scan "soymutdb-worker:ci-${ARCH}" "trivy-worker.sarif"

step "Trivy scan MCP image (hard gate)"
trivy_scan "soymutdb-mcp:ci-${ARCH}" "trivy-mcp.sarif"

step "Trivy scan JBrowse image (hard gate)"
trivy_scan "soymutdb-jbrowse:ci-${ARCH}" "trivy-jbrowse.sarif"

mkdir -p "${OUTPUT_DIR}"

step "Generate API SPDX SBOM"
trivy_sbom "soymutdb-api:ci-${ARCH}" "${OUTPUT_DIR}/sbom-api-${ARCH}.spdx.json"

step "Generate Worker SPDX SBOM"
trivy_sbom "soymutdb-worker:ci-${ARCH}" "${OUTPUT_DIR}/sbom-worker-${ARCH}.spdx.json"

step "Generate MCP SPDX SBOM"
trivy_sbom "soymutdb-mcp:ci-${ARCH}" "${OUTPUT_DIR}/sbom-mcp-${ARCH}.spdx.json"

step "Generate JBrowse SPDX SBOM"
trivy_sbom "soymutdb-jbrowse:ci-${ARCH}" "${OUTPUT_DIR}/sbom-jbrowse-${ARCH}.spdx.json"

if [[ "${EXPORT}" != "1" ]]; then
  echo "export skipped (SOYMUTDB_CI_EXPORT=${EXPORT})"
  exit 0
fi

step "Export validated runtime images"
mkdir -p "${OUTPUT_DIR}"
validated_images=(
  "soymutdb-api:ci-${ARCH}"
  "soymutdb-worker:ci-${ARCH}"
  "soymutdb-mcp:ci-${ARCH}"
  "soymutdb-jbrowse:ci-${ARCH}"
)
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
docker save "${validated_images[@]}" | gzip -1 > "${OUTPUT_DIR}/soymutdb-runtime-images-${ARCH}.tar.gz"

step "validate-runtime-images (checksums)"
(
  cd "${OUTPUT_DIR}"
  sha256sum "soymutdb-runtime-images-${ARCH}.tar.gz" \
    "image-ids-${ARCH}.txt" platform.txt revision.txt sbom-*-"${ARCH}".spdx.json > SHA256SUMS
  sha256sum -c SHA256SUMS
)

printf '\nimage verification passed for %s\n' "${PLATFORM}"

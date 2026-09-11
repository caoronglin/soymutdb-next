#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — OCI release contract (merge, sign, attest, publish)
# =============================================================================
# Single source for turning two platform-verified image packages into one signed
# multi-architecture release. The GitHub mirror workflow and the CNB release
# pipeline both call this script, so a release produced from either provider has
# the same image names, digest references, provenance, and SBOM attachments.
#
# Preconditions (verified here, not assumed):
#   * both platform packages are present and their SHA256SUMS verify
#   * the images loaded from them match the recorded image IDs exactly
#   * the built architecture matches the declared platform
#
# Guarantees:
#   * the release manifest references digests, never tags
#   * every image digest and platform digest is signed and carries a
#     SLSA provenance attestation and its SPDX SBOM attestation
#   * everything is checksummed and the manifest itself is signed as a blob
#
# Usage:
#   bash scripts/release-contract.golden.sh
#
# Env (all optional unless noted):
#   RELEASE_TAG            release tag. The tag_push CNB pipeline injects
#                          CNB_BRANCH (the tag name) here; otherwise it defaults
#                          to the UTC date plus the short revision.
#   RELEASE_REGISTRY       registry host (default: ${CNB_DOCKER_REGISTRY:-ghcr.io})
#   RELEASE_REGISTRY_OWNER registry namespace (default: repository owner)
#   RELEASE_SKIP_SIGNING   1 to skip cosign (contract-only dry run)
#   SOURCE_REPOSITORY      source repository slug
#   SOURCE_REVISION        source commit SHA
#   SOURCE_PIPELINE        pipeline identity recorded in provenance
#   VALIDATED_ROOT         directory holding validated-runtime-images-* packages
#   RELEASE_OUTPUT_DIR     output directory (default release-contract)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-${CNB_REPO_SLUG:-$(git config --get remote.origin.url || echo unknown)}}"
SOURCE_REVISION="${SOURCE_REVISION:-${CNB_COMMIT:-$(git rev-parse HEAD)}}"
SOURCE_PIPELINE="${SOURCE_PIPELINE:-${CNB_BUILD_ID:-local}}"
RELEASE_REGISTRY="${RELEASE_REGISTRY:-${CNB_DOCKER_REGISTRY:-ghcr.io}}"
RELEASE_REGISTRY_OWNER="${RELEASE_REGISTRY_OWNER:-${CNB_REPO_SLUG%%/*}}"
RELEASE_REGISTRY_OWNER="${RELEASE_REGISTRY_OWNER:-${GITHUB_REPOSITORY_OWNER:-soymutdb}}"
RELEASE_REGISTRY_OWNER="$(printf '%s' "${RELEASE_REGISTRY_OWNER}" | tr '[:upper:]' '[:lower:]')"
RELEASE_TAG="${RELEASE_TAG:-$(date -u +%Y.%m.%d)-$(printf '%s' "${SOURCE_REVISION}" | cut -c1-7)}"
VALIDATED_ROOT="${VALIDATED_ROOT:-validated-platforms}"
RELEASE_OUTPUT_DIR="${RELEASE_OUTPUT_DIR:-release-contract}"

step() { printf '\n==> %s\n' "$*"; }

# --- 1. verify both platform packages ---------------------------------------
step "Verify and load both platform packages"
for arch in amd64 arm64; do
  artifact_dir="${VALIDATED_ROOT}/validated-runtime-images-${arch}"
  test -d "${artifact_dir}" || {
    echo "missing validated package for ${arch}: ${artifact_dir}" >&2
    exit 1
  }
  test "$(cat "${artifact_dir}/platform.txt")" = "linux/${arch}"
  (cd "${artifact_dir}" && sha256sum -c SHA256SUMS)
  gzip -dc "${artifact_dir}/soymutdb-runtime-images-${arch}.tar.gz" | docker load
  expected_images=(api worker mcp jbrowse)
  test "$(wc -l < "${artifact_dir}/image-ids-${arch}.txt")" -eq "${#expected_images[@]}"
  for image_name in "${expected_images[@]}"; do
    image="soymutdb-${image_name}:ci-${arch}"
    expected_id="$(awk -v image="${image}" '$1 == image {print $2}' "${artifact_dir}/image-ids-${arch}.txt")"
    test -n "${expected_id}"
    actual_id="$(docker image inspect --format '{{.Id}}' "${image}")"
    test "${actual_id}" = "${expected_id}"
    test "$(docker image inspect --format '{{.Architecture}}' "${image}")" = "${arch}"
  done
done

# --- 2. authenticate ---------------------------------------------------------
step "Authenticate to ${RELEASE_REGISTRY}"
if [[ "${RELEASE_SKIP_SIGNING:-0}" != "1" ]]; then
  if [[ -n "${CNB_TOKEN:-}" && -n "${CNB_DOCKER_REGISTRY:-}" ]]; then
    # CNB injects a build-scoped token; it is never echoed.
    printf '%s' "${CNB_TOKEN}" | docker login "${CNB_DOCKER_REGISTRY}" \
      --username "${CNB_TOKEN_USER_NAME:-cnb}" --password-stdin
  elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    printf '%s' "${GITHUB_TOKEN}" | docker login "${RELEASE_REGISTRY}" \
      --username "${GITHUB_ACTOR:-github-actions}" --password-stdin
  else
    echo "no registry credentials available; set RELEASE_SKIP_SIGNING=1 for a dry run" >&2
    exit 2
  fi
fi

# --- 3. push per-platform images --------------------------------------------
step "Tag and push validated platform images"
local_names=(api worker mcp jbrowse)
remote_names=(api worker mcp-server jbrowse)
for arch in amd64 arm64; do
  for index in "${!local_names[@]}"; do
    image="${RELEASE_REGISTRY}/${RELEASE_REGISTRY_OWNER}/${remote_names[$index]}:${RELEASE_TAG}-${arch}"
    docker tag "soymutdb-${local_names[$index]}:ci-${arch}" "${image}"
    docker push "${image}"
  done
done

# --- 4. merge manifests, attest evidence, write the release contract --------
step "Merge manifests, attest evidence, and write release manifest"
mkdir -p "${RELEASE_OUTPUT_DIR}"
certificate_identity="https://${RELEASE_REGISTRY}/${SOURCE_REPOSITORY}/scripts/release-contract.golden.sh@refs/heads/main"
oidc_issuer="${SOYMUTDB_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

jq -n \
  --arg repository "${SOURCE_REPOSITORY}" \
  --arg revision "${SOURCE_REVISION}" \
  --arg workflow_identity "${certificate_identity}" \
  --arg run_id "${SOURCE_PIPELINE}" \
  --arg release_tag "${RELEASE_TAG}" \
  '{
    "schema_version": 1,
    "source": {
      "repository": $repository,
      "revision": $revision,
      "workflow_identity": $workflow_identity,
      "run_id": $run_id
    },
    "release_tag": $release_tag,
    "platforms": ["linux/amd64", "linux/arm64"],
    "images": []
  }' > "${RELEASE_OUTPUT_DIR}/release-manifest.json"

for index in "${!local_names[@]}"; do
  image_name="${local_names[$index]}"
  remote_name="${remote_names[$index]}"
  final_tag="${RELEASE_REGISTRY}/${RELEASE_REGISTRY_OWNER}/${remote_name}:${RELEASE_TAG}"
  amd64_tag="${final_tag}-amd64"
  arm64_tag="${final_tag}-arm64"

  docker manifest create "${final_tag}" "${amd64_tag}" "${arm64_tag}"
  digest="$(docker manifest push "${final_tag}" | tail -n 1)"
  [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
  image="${final_tag}"
  digest_ref="${image%:*}@${digest}"
  docker manifest inspect "${digest_ref}" >/dev/null

  platforms="$(docker manifest inspect "${digest_ref}" | jq -r '[.manifests[].platform | "\(.os)/\(.architecture)"] | sort | join(",")')"
  test "${platforms}" = "linux/amd64,linux/arm64"
  echo "Verify merged manifest platforms: ${image_name}=${platforms}"

  provenance="${RELEASE_OUTPUT_DIR}/provenance-${image_name}.json"
  jq -n \
    --arg repository "${SOURCE_REPOSITORY}" \
    --arg revision "${SOURCE_REVISION}" \
    --arg image "${image_name}" \
    --arg builder "${certificate_identity}" \
    --arg invocation "${SOURCE_PIPELINE}" \
    '{
      "builder": {"id": $builder},
      "buildType": "https://soymutdb/oci-multiarch@v1",
      "invocation": {
        "configSource": {
          "uri": ("git+" + $repository),
          "digest": {"sha1": $revision},
          "entryPoint": "scripts/release-contract.golden.sh"
        },
        "parameters": {
          "image": $image,
          "platforms": ["linux/amd64", "linux/arm64"]
        },
        "environment": {"pipeline_run_id": $invocation}
      },
      "metadata": {"buildInvocationId": $invocation},
      "materials": [{
        "uri": ("git+" + $repository),
        "digest": {"sha1": $revision}
      }]
    }' > "${provenance}"
  provenance_sha256="$(sha256sum "${provenance}" | cut -d ' ' -f 1)"

  platforms_json='[]'
  for arch in amd64 arm64; do
    platform_tag="${final_tag}-${arch}"
    platform_digest="$(docker manifest inspect --verbose "${platform_tag}" | jq -r '.Descriptor.digest')"
    [[ "${platform_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    platform_ref="${platform_tag%:*}@${platform_digest}"
    sbom_source="${VALIDATED_ROOT}/validated-runtime-images-${arch}/sbom-${image_name}-${arch}.spdx.json"
    sbom_target="${RELEASE_OUTPUT_DIR}/sbom-${image_name}-${arch}.spdx.json"
    cp "${sbom_source}" "${sbom_target}"
    jq -e '.spdxVersion | startswith("SPDX-")' "${sbom_target}" >/dev/null
    sbom_sha256="$(sha256sum "${sbom_target}" | cut -d ' ' -f 1)"

    if [[ "${RELEASE_SKIP_SIGNING:-0}" != "1" ]]; then
      cosign sign --yes "${digest_ref}"
      cosign attest --yes --type slsaprovenance --predicate "${provenance}" "${digest_ref}"
      cosign verify \
        --certificate-identity "${certificate_identity}" \
        --certificate-oidc-issuer "${oidc_issuer}" "${digest_ref}" >/dev/null
      cosign verify-attestation --type slsaprovenance \
        --certificate-identity "${certificate_identity}" \
        --certificate-oidc-issuer "${oidc_issuer}" "${digest_ref}" >/dev/null

      cosign sign --yes "${platform_ref}"
      cosign attest --yes --type spdxjson --predicate "${sbom_target}" "${platform_ref}"
      cosign verify \
        --certificate-identity "${certificate_identity}" \
        --certificate-oidc-issuer "${oidc_issuer}" "${platform_ref}" >/dev/null
      cosign verify-attestation --type spdxjson \
        --certificate-identity "${certificate_identity}" \
        --certificate-oidc-issuer "${oidc_issuer}" "${platform_ref}" >/dev/null
    fi

    platform_entry="$(jq -n \
      --arg platform "linux/${arch}" \
      --arg digest_ref "${platform_ref}" \
      --arg sbom "$(basename "${sbom_target}")" \
      --arg sbom_sha256 "${sbom_sha256}" \
      '{platform: $platform, digest_ref: $digest_ref, sbom: $sbom, sbom_sha256: $sbom_sha256}')"
    platforms_json="$(jq --argjson item "${platform_entry}" '. + [$item]' <<<"${platforms_json}")"
  done

  image_entry="$(jq -n \
    --arg name "${image_name}" \
    --arg digest_ref "${digest_ref}" \
    --arg provenance "$(basename "${provenance}")" \
    --arg provenance_sha256 "${provenance_sha256}" \
    --argjson platforms "${platforms_json}" \
    '{
      name: $name,
      digest_ref: $digest_ref,
      provenance: $provenance,
      provenance_sha256: $provenance_sha256,
      platforms: $platforms
    }')"
  jq --argjson image "${image_entry}" '.images += [$image]' \
    "${RELEASE_OUTPUT_DIR}/release-manifest.json" > "${RELEASE_OUTPUT_DIR}/release-manifest.tmp"
  mv "${RELEASE_OUTPUT_DIR}/release-manifest.tmp" "${RELEASE_OUTPUT_DIR}/release-manifest.json"
done

expected_provenance=(
  "${RELEASE_OUTPUT_DIR}/provenance-api.json"
  "${RELEASE_OUTPUT_DIR}/provenance-worker.json"
  "${RELEASE_OUTPUT_DIR}/provenance-mcp.json"
  "${RELEASE_OUTPUT_DIR}/provenance-jbrowse.json"
)
for provenance_file in "${expected_provenance[@]}"; do
  test -s "${provenance_file}"
done
jq -r '.images[].digest_ref' "${RELEASE_OUTPUT_DIR}/release-manifest.json" | sort \
  > "${RELEASE_OUTPUT_DIR}/oci-image-refs.txt"

(
  cd "${RELEASE_OUTPUT_DIR}"
  jq -e '
    .schema_version == 1 and
    .platforms == ["linux/amd64", "linux/arm64"] and
    (.images | length == 4) and
    ([.images[].name] | sort) == ["api", "jbrowse", "mcp", "worker"] and
    all(.images[];
      (.digest_ref | test("@sha256:[0-9a-f]{64}$")) and
      (.provenance_sha256 | test("^[0-9a-f]{64}$")) and
      ([.platforms[].platform] | sort) == ["linux/amd64", "linux/arm64"]
    )
  ' release-manifest.json >/dev/null
  sha256sum oci-image-refs.txt > OCI_SHA256SUMS
  sha256sum release-manifest.json oci-image-refs.txt provenance-*.json sbom-*.spdx.json > SHA256SUMS
  if [[ "${RELEASE_SKIP_SIGNING:-0}" != "1" ]]; then
    cosign sign-blob --yes --bundle release-manifest.sigstore.json release-manifest.json
    cosign verify-blob \
      --bundle release-manifest.sigstore.json \
      --certificate-identity "${certificate_identity}" \
      --certificate-oidc-issuer "${oidc_issuer}" release-manifest.json
  fi
  contract_sha="$(sha256sum release-manifest.json | cut -d ' ' -f 1)"
  echo "sha256=${contract_sha}" >> "${CNB_OUTPUT_FILE:-/dev/null}"
  printf '%s\n' "${contract_sha}" > release-contract.sha256
  echo "Upload signed OCI release contract"
  echo "release-contract-sha256=${contract_sha}"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo "## Signed multi-architecture OCI release contract"
      echo
      echo '```text'
      cat oci-image-refs.txt
      echo '```'
      echo
      echo "Contract SHA-256: \`${contract_sha}\`"
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
)

printf '\nrelease contract ready in %s\n' "${RELEASE_OUTPUT_DIR}"

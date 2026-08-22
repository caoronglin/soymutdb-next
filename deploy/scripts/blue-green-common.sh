#!/usr/bin/env bash
# Shared fail-closed verification and state helpers for blue/green operations.
# This file is sourced by blue-green-deploy.sh and blue-green-rollback.sh.
set -euo pipefail

BLUE_GREEN_STATE_FILE="${BLUE_GREEN_STATE_FILE:-/var/lib/soymutdb/blue-green-state.json}"
BLUE_GREEN_LOCK_FILE="${BLUE_GREEN_LOCK_FILE:-/var/lock/soymutdb-blue-green.lock}"
SOYMUTDB_RELEASE_OIDC_ISSUER="${SOYMUTDB_RELEASE_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

bg_fail() {
    echo "[blue-green] ERROR: $*" >&2
    exit 1
}

require_blue_green_runtime() {
    for command in cosign jq sha256sum flock mktemp mv; do
        command -v "${command}" >/dev/null 2>&1 || bg_fail "required command not found: ${command}"
    done
    [[ -n "${BLUE_GREEN_ADAPTER:-}" ]] || bg_fail "BLUE_GREEN_ADAPTER is required"
    [[ "${BLUE_GREEN_ADAPTER}" == /* ]] || bg_fail "BLUE_GREEN_ADAPTER must be an absolute path"
    [[ -x "${BLUE_GREEN_ADAPTER}" ]] || bg_fail "BLUE_GREEN_ADAPTER is not executable"
    [[ -n "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY:-}" ]] || \
        bg_fail "SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY is required"
}

acquire_blue_green_lock() {
    mkdir -p "$(dirname "${BLUE_GREEN_LOCK_FILE}")"
    exec 9>"${BLUE_GREEN_LOCK_FILE}"
    flock -w "${BLUE_GREEN_LOCK_TIMEOUT:-30}" 9 || bg_fail "another slot operation holds the lock"
}

run_adapter() {
    "${BLUE_GREEN_ADAPTER}" "$@"
}

validate_release_contract() {
    local manifest="$1"
    local expected_sha256="$2"
    local signature_bundle="$3"
    local contract_dir actual_sha256 digest_ref provenance_ref provenance_sha256
    local platform_ref sbom_name sbom_sha256

    [[ -f "${manifest}" ]] || bg_fail "release manifest not found: ${manifest}"
    [[ -f "${signature_bundle}" ]] || bg_fail "release signature bundle not found: ${signature_bundle}"
    [[ "${expected_sha256}" =~ ^[0-9a-f]{64}$ ]] || bg_fail "release manifest SHA-256 is malformed"
    actual_sha256="$(sha256sum "${manifest}" | cut -d ' ' -f 1)"
    [[ "${actual_sha256}" == "${expected_sha256}" ]] || bg_fail "release manifest SHA-256 mismatch"

    cosign verify-blob \
        --bundle "${signature_bundle}" \
        --certificate-identity "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY}" \
        --certificate-oidc-issuer "${SOYMUTDB_RELEASE_OIDC_ISSUER}" \
        "${manifest}" >/dev/null

    jq -e '
      .schema_version == 1 and
      .platforms == ["linux/amd64", "linux/arm64"] and
      (.images | length == 4) and
      ([.images[].name] | sort) == ["api", "jbrowse", "mcp", "worker"] and
      all(.images[];
        (.digest_ref | test("@sha256:[0-9a-f]{64}$")) and
        (.provenance | type == "string") and
        (.provenance_sha256 | test("^[0-9a-f]{64}$")) and
        ([.platforms[].platform] | sort) == ["linux/amd64", "linux/arm64"]
      )
    ' "${manifest}" >/dev/null || bg_fail "release manifest schema or platform contract is invalid"

    contract_dir="$(cd "$(dirname "${manifest}")" && pwd)"
    while IFS=$'\t' read -r digest_ref provenance_ref provenance_sha256; do
        [[ "${digest_ref}" =~ @sha256:[0-9a-f]{64}$ ]] || bg_fail "image is not digest pinned: ${digest_ref}"
        [[ "${provenance_ref}" =~ ^provenance-[a-z0-9-]+\.json$ ]] || \
            bg_fail "unsafe provenance filename: ${provenance_ref}"
        [[ "${provenance_sha256}" =~ ^[0-9a-f]{64}$ ]] || bg_fail "provenance SHA-256 is malformed"
        [[ -f "${contract_dir}/${provenance_ref}" ]] || bg_fail "provenance missing: ${provenance_ref}"
        actual_sha256="$(sha256sum "${contract_dir}/${provenance_ref}" | cut -d ' ' -f 1)"
        [[ "${actual_sha256}" == "${provenance_sha256}" ]] || \
            bg_fail "provenance SHA-256 mismatch: ${provenance_ref}"
        cosign verify \
            --certificate-identity "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY}" \
            --certificate-oidc-issuer "${SOYMUTDB_RELEASE_OIDC_ISSUER}" \
            "${digest_ref}" >/dev/null
        cosign verify-attestation --type slsaprovenance \
            --certificate-identity "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY}" \
            --certificate-oidc-issuer "${SOYMUTDB_RELEASE_OIDC_ISSUER}" \
            "${digest_ref}" >/dev/null
    done < <(jq -r '.images[] | [.digest_ref, .provenance, .provenance_sha256] | @tsv' "${manifest}")

    while IFS=$'\t' read -r platform_ref sbom_name sbom_sha256; do
        [[ "${platform_ref}" =~ @sha256:[0-9a-f]{64}$ ]] || bg_fail "platform image is not digest pinned"
        [[ "${sbom_name}" =~ ^sbom-[a-z0-9-]+-(amd64|arm64)\.spdx\.json$ ]] || \
            bg_fail "unsafe SBOM filename: ${sbom_name}"
        [[ "${sbom_sha256}" =~ ^[0-9a-f]{64}$ ]] || bg_fail "SBOM SHA-256 is malformed"
        [[ -f "${contract_dir}/${sbom_name}" ]] || bg_fail "SBOM missing: ${sbom_name}"
        actual_sha256="$(sha256sum "${contract_dir}/${sbom_name}" | cut -d ' ' -f 1)"
        [[ "${actual_sha256}" == "${sbom_sha256}" ]] || bg_fail "SBOM SHA-256 mismatch: ${sbom_name}"
        cosign verify \
            --certificate-identity "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY}" \
            --certificate-oidc-issuer "${SOYMUTDB_RELEASE_OIDC_ISSUER}" \
            "${platform_ref}" >/dev/null
        cosign verify-attestation --type spdxjson \
            --certificate-identity "${SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY}" \
            --certificate-oidc-issuer "${SOYMUTDB_RELEASE_OIDC_ISSUER}" \
            "${platform_ref}" >/dev/null
    done < <(jq -r '.images[].platforms[] | [.digest_ref, .sbom, .sbom_sha256] | @tsv' "${manifest}")
}

load_slot_state() {
    [[ -f "${BLUE_GREEN_STATE_FILE}" ]] || bg_fail "slot state is not bootstrapped: ${BLUE_GREEN_STATE_FILE}"
    jq -e '
      .schema_version == 1 and
      (.active_slot == "blue" or .active_slot == "green") and
      (.active_release_manifest_sha256 | test("^[0-9a-f]{64}$")) and
      (
        (.previous_slot == null and .previous_release_manifest_sha256 == null) or
        ((.previous_slot == "blue" or .previous_slot == "green") and
         (.previous_slot != .active_slot) and
         (.previous_release_manifest_sha256 | test("^[0-9a-f]{64}$")))
      )
    ' "${BLUE_GREEN_STATE_FILE}" >/dev/null || bg_fail "slot state is invalid"
}

write_slot_state() {
    local active_slot="$1"
    local active_sha256="$2"
    local previous_slot="$3"
    local previous_sha256="$4"
    local state_dir temporary_state

    state_dir="$(dirname "${BLUE_GREEN_STATE_FILE}")"
    mkdir -p "${state_dir}"
    temporary_state="$(mktemp "${BLUE_GREEN_STATE_FILE}.tmp.XXXXXX")"
    jq -n \
        --arg active_slot "${active_slot}" \
        --arg active_sha256 "${active_sha256}" \
        --arg previous_slot "${previous_slot}" \
        --arg previous_sha256 "${previous_sha256}" \
        --arg promoted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        '{
          schema_version: 1,
          active_slot: $active_slot,
          active_release_manifest_sha256: $active_sha256,
          previous_slot: $previous_slot,
          previous_release_manifest_sha256: $previous_sha256,
          promoted_at: $promoted_at
        }' > "${temporary_state}"
    chmod 0600 "${temporary_state}"
    mv "${temporary_state}" "${BLUE_GREEN_STATE_FILE}"
}

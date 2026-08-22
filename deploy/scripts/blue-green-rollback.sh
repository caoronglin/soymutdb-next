#!/usr/bin/env bash
# Switch traffic back to the retained previous slot after re-verifying its
# signed release contract and slot-reported release identity.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/blue-green-common.sh
source "${SCRIPT_DIR}/blue-green-common.sh"

if [[ "$#" -ne 3 ]]; then
    echo "Usage: $0 PREVIOUS_RELEASE_MANIFEST EXPECTED_SHA256 SIGSTORE_BUNDLE" >&2
    exit 2
fi

release_manifest="$1"
release_sha256="$2"
signature_bundle="$3"

require_blue_green_runtime
acquire_blue_green_lock
validate_release_contract "${release_manifest}" "${release_sha256}" "${signature_bundle}"
load_slot_state

active_slot="$(jq -r '.active_slot' "${BLUE_GREEN_STATE_FILE}")"
active_sha256="$(jq -r '.active_release_manifest_sha256' "${BLUE_GREEN_STATE_FILE}")"
observed_active_slot="$(run_adapter "current")"
[[ "${observed_active_slot}" == "${active_slot}" ]] || \
    bg_fail "adapter current slot does not match recorded active slot ${active_slot}"
previous_slot="$(jq -r '.previous_slot // empty' "${BLUE_GREEN_STATE_FILE}")"
previous_release_manifest_sha256="$(jq -r '.previous_release_manifest_sha256 // empty' "${BLUE_GREEN_STATE_FILE}")"
[[ -n "${previous_slot}" && -n "${previous_release_manifest_sha256}" ]] || bg_fail "no previous slot is recorded"
[[ "${release_sha256}" == "${previous_release_manifest_sha256}" ]] || \
    bg_fail "supplied release contract is not the recorded previous release"

switch_attempted=false
rollback_complete=false
restore_active_slot() {
    local status=$?
    trap - EXIT
    if [[ "${switch_attempted}" == "true" && "${rollback_complete}" != "true" ]]; then
        run_adapter "switch" "${active_slot}" || true
        restored_slot="$(run_adapter "current" 2>/dev/null || true)"
        [[ "${restored_slot}" == "${active_slot}" ]] || \
            echo "[blue-green] CRITICAL: failed to restore active slot ${active_slot}" >&2
    fi
    exit "${status}"
}
trap restore_active_slot EXIT

run_adapter "verify" "${previous_slot}" "${previous_release_manifest_sha256}"
switch_attempted=true
run_adapter "switch" "${previous_slot}"
observed_slot="$(run_adapter "current")"
[[ "${observed_slot}" == "${previous_slot}" ]] || bg_fail "rollback switch did not select ${previous_slot}"

write_slot_state "${previous_slot}" "${previous_release_manifest_sha256}" "${active_slot}" "${active_sha256}"
rollback_complete=true
trap - EXIT
echo "[blue-green] rolled back to ${previous_slot} with release ${previous_release_manifest_sha256}"

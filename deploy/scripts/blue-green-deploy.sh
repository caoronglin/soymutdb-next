#!/usr/bin/env bash
# Stage a signed release in the inactive slot, verify it, then atomically ask
# the site-specific adapter to switch traffic. The old slot stays available.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/blue-green-common.sh
source "${SCRIPT_DIR}/blue-green-common.sh"

if [[ "$#" -ne 3 ]]; then
    echo "Usage: $0 RELEASE_MANIFEST EXPECTED_SHA256 SIGSTORE_BUNDLE" >&2
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
[[ "${release_sha256}" != "${active_sha256}" ]] || bg_fail "release is already active"
if [[ "${active_slot}" == "blue" ]]; then
    target_slot="green"
else
    target_slot="blue"
fi

switch_attempted=false
promotion_complete=false
restore_active_slot() {
    local status=$?
    trap - EXIT
    if [[ "${switch_attempted}" == "true" && "${promotion_complete}" != "true" ]]; then
        run_adapter "switch" "${active_slot}" || true
        restored_slot="$(run_adapter "current" 2>/dev/null || true)"
        [[ "${restored_slot}" == "${active_slot}" ]] || \
            echo "[blue-green] CRITICAL: failed to restore active slot ${active_slot}" >&2
    fi
    exit "${status}"
}
trap restore_active_slot EXIT

run_adapter "stage" "${target_slot}" "${release_manifest}" "${release_sha256}"
run_adapter "verify" "${target_slot}" "${release_sha256}"
switch_attempted=true
run_adapter "switch" "${target_slot}"
observed_slot="$(run_adapter "current")"
[[ "${observed_slot}" == "${target_slot}" ]] || bg_fail "traffic switch did not select ${target_slot}"

write_slot_state "${target_slot}" "${release_sha256}" "${active_slot}" "${active_sha256}"
promotion_complete=true
trap - EXIT
echo "[blue-green] promoted ${target_slot} with release ${release_sha256}"

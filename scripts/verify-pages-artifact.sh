#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — verify a Pages artifact before publication
# =============================================================================
# Publication is a byte copy, never a rebuild. This script is the only thing
# standing between "some directory" and "the verified site", so it is strict:
#
#   1. the required entry points exist (root, JBrowse sub-app, hidden files)
#   2. SHA256SUMS covers every published file (hidden files included)
#   3. every checksum matches
#   4. when MANIFEST_DIGEST/publication inputs are provided, the artifact URL's
#      digest is checked BEFORE any publication step runs
#
# Usage:
#   bash scripts/verify-pages-artifact.sh <artifact-dir>
# Env:
#   ARTIFACT_URL      optional immutable artifact URL (downloaded when set)
#   MANIFEST_DIGEST   optional expected sha256 of the artifact archive
#   PUBLICATION_ID    optional publication identifier for the log trail
# =============================================================================
set -euo pipefail

ARTIFACT_DIR="${1:-pages-dist}"
ARTIFACT_URL="${ARTIFACT_URL:-}"
MANIFEST_DIGEST="${MANIFEST_DIGEST:-}"
PUBLICATION_ID="${PUBLICATION_ID:-}"

log() { printf '[verify-pages-artifact] %s\n' "$*" >&2; }

if [[ -n "${MANIFEST_DIGEST}" ]]; then
  [[ -n "${ARTIFACT_URL}" ]] || {
    echo "MANIFEST_DIGEST requires ARTIFACT_URL; refusing an unverifiable digest" >&2
    exit 2
  }
  log "Verify immutable artifact digest ${PUBLICATION_ID:+(${PUBLICATION_ID})}"
  tmp_archive="$(mktemp)"
  trap 'rm -f "${tmp_archive}"' EXIT
  curl --fail --silent --show-error --location --output "${tmp_archive}" "${ARTIFACT_URL}"
  observed="$(sha256sum "${tmp_archive}" | cut -d ' ' -f 1)"
  expected="${MANIFEST_DIGEST#sha256:}"
  if [[ "${observed}" != "${expected}" ]]; then
    echo "artifact digest mismatch: expected ${expected}, got ${observed}" >&2
    exit 1
  fi
  mkdir -p "${ARTIFACT_DIR}"
  tar -xzf "${tmp_archive}" -C "${ARTIFACT_DIR}"
fi

log "Verify exact Pages artifact tree"
test -f "${ARTIFACT_DIR}/index.html"
if [[ -f "${ARTIFACT_DIR}/.no-jbrowse" ]]; then
  log "core-only artifact: JBrowse sub-app is deliberately absent (.no-jbrowse)"
else
  test -f "${ARTIFACT_DIR}/soymutdb-jbrowse/index.html"
fi
test -f "${ARTIFACT_DIR}/SHA256SUMS"

log "Verify checksums (hidden files included)"
(
  cd "${ARTIFACT_DIR}"
  sha256sum -c SHA256SUMS
)

log "Verify published tree is byte-identical to the manifest"
expected_files="$(mktemp)"
actual_files="$(mktemp)"
trap 'rm -f "${expected_files}" "${actual_files}"' EXIT
(
  cd "${ARTIFACT_DIR}"
  awk '{print $2}' SHA256SUMS | sed 's#^\./##' | LC_ALL=C sort
) > "${expected_files}"
(
  cd "${ARTIFACT_DIR}"
  find . -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort
) > "${actual_files}"
diff -u "${expected_files}" "${actual_files}"
(
  cd "${ARTIFACT_DIR}"
  sha256sum -c SHA256SUMS
)

log "Pages artifact verified"

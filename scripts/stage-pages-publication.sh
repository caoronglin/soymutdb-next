#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — stage the verified static tree for publication
# =============================================================================
# Publication is a byte copy of the artifact the verify pipeline built and
# checksummed. This script never installs a JS toolchain and never rebuilds the
# bundle, so the published tree always equals the verified bytes.
#
# It exists as a script (rather than stage bodies in .cnb.yml /
# .cnb/pipelines/pages-publish.yml) for one concrete reason: a CNB stage script
# is executed with `sh`, and `sh` rejects the bash syntax the inline bodies used
# (`set -o pipefail`, `[[ ]]`, `source`). Pinning the interpreter through this
# script's shebang makes the stage shell-independent, and lets
# scripts/test_ci_job_contracts.py lint the interpreter of every stage.
#
# Usage
#   bash scripts/stage-pages-publication.sh verify    # verify + stage the tree
#   bash scripts/stage-pages-publication.sh publish   # hand the tree to the adapter
#
# Environment
#   PAGES_ARTIFACT_DIR            built + checksummed artifact (default pages-dist)
#   PAGES_PUBLISH_DIR             staged output tree  (default pages-publish)
#   SOYMUTDB_PAGES_PUBLISH_ADAPTER
#       optional script exposing `publish_pages_tree <dir>`. Without it the
#       verified tree is staged and left for manual publication — reported as
#       SKIPPED, never as a successful publish.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

ARTIFACT_DIR="${PAGES_ARTIFACT_DIR:-pages-dist}"
PUBLISH_DIR="${PAGES_PUBLISH_DIR:-pages-publish}"

log() { printf '[stage-pages-publication] %s\n' "$*" >&2; }

verify_and_stage() {
  # verify-pages-artifact.sh enforces entry points, full checksum coverage
  # (hidden files included), an exact byte-tree match, and — when a publication
  # id and manifest digest are supplied — the artifact digest BEFORE anything is
  # published.
  test -d "${ARTIFACT_DIR}" || {
    log "pages artifact ${ARTIFACT_DIR} missing; the verify pipeline must run first"
    exit 1
  }
  bash "${REPO_ROOT}/scripts/verify-pages-artifact.sh" "${ARTIFACT_DIR}"

  rm -rf "${PUBLISH_DIR}"
  mkdir -p "${PUBLISH_DIR}"
  cp -a "${ARTIFACT_DIR}/." "${PUBLISH_DIR}/"

  test -f "${PUBLISH_DIR}/index.html"
  if [[ ! -f "${PUBLISH_DIR}/.no-jbrowse" ]]; then
    test -f "${PUBLISH_DIR}/soymutdb-jbrowse/index.html"
  fi
  test -f "${PUBLISH_DIR}/SHA256SUMS"
  ( cd "${PUBLISH_DIR}" && sha256sum -c SHA256SUMS )

  log "staged ${ARTIFACT_DIR} -> ${PUBLISH_DIR}"
}

publish() {
  test -d "${PUBLISH_DIR}" || {
    log "${PUBLISH_DIR} missing; run the verify stage first"
    exit 1
  }

  # The publication target (object storage / static host) is deliberately
  # adapter-driven: this script records what was published and leaves the
  # transport to the environment's configured adapter.
  if [[ -z "${SOYMUTDB_PAGES_PUBLISH_ADAPTER:-}" ]]; then
    # A missing adapter is a missing prerequisite, not a success: report it the
    # way scripts/smoke.sh reports a skipped layer.
    log "SKIPPED: no SOYMUTDB_PAGES_PUBLISH_ADAPTER configured."
    log "Verified tree staged at ${PUBLISH_DIR} for manual publication."
    return 0
  fi

  # shellcheck disable=SC1090
  source "${SOYMUTDB_PAGES_PUBLISH_ADAPTER}"
  declare -F publish_pages_tree >/dev/null || {
    log "adapter ${SOYMUTDB_PAGES_PUBLISH_ADAPTER} defines no publish_pages_tree()"
    exit 1
  }
  publish_pages_tree "${PUBLISH_DIR}"
  log "published ${PUBLISH_DIR}"
}

main() {
  case "${1:-}" in
    verify) verify_and_stage ;;
    publish) publish ;;
    publish-tree)
      verify_and_stage
      publish
      ;;
    *) log "usage: $0 {verify|publish|publish-tree}"; exit 2 ;;
  esac
}

main "$@"

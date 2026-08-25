#!/usr/bin/env bash
set -euo pipefail
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; fi
ROOT="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
PREVIOUS="$(readlink -f "${ROOT}/current" 2>/dev/null || true)"
if (( DRY_RUN )); then echo "DRY-RUN: would back up, install a new release, migrate, restart, and health-check"; exit 0; fi
"$(dirname "${BASH_SOURCE[0]}")/baseline-backup.sh"
"${ROOT}/current/deploy/linux/install.sh"
"$(dirname "${BASH_SOURCE[0]}")/baseline-healthcheck.sh" || { echo "health failed; previous release was ${PREVIOUS}" >&2; exit 1; }
printf 'Upgrade completed: %s\\n' "${ROOT}/current"

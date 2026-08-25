#!/usr/bin/env bash
set -euo pipefail
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; fi
API_URL="${SOYMUTDB_BASELINE_API_URL:-http://127.0.0.1:8000}"
if (( DRY_RUN )); then echo "DRY-RUN: would check ${API_URL}/health and /api/v1/health/ready"; exit 0; fi
curl --fail --silent --show-error "${API_URL}/health" >/dev/null
curl --fail --silent --show-error "${API_URL}/api/v1/health/live" >/dev/null
curl --fail --silent --show-error "${API_URL}/api/v1/health/ready" >/dev/null
printf 'SoyMutDB baseline API is healthy: %s\\n' "${API_URL}"

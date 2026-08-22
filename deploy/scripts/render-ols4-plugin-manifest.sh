#!/usr/bin/env bash
# Render the canonical, signed OLS4 deployment manifest with the API image.
#
# Usage:
#   OLS4_PLUGIN_ENABLED=1 OLS4_PLUGIN_CONFIGURED=1 OLS4_PLUGIN_HEALTHY=1 \
#     bash deploy/scripts/render-ols4-plugin-manifest.sh > /secure/ols4-manifest.json
#
# The signing key is read from SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY in the
# compose .env file. This script never prints the key; stdout is exactly the
# compact JSON value for SOYMUTDB_PLUGIN_MANIFESTS_JSON.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"

if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
COMPOSE=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")

OLS4_PLUGIN_ENABLED="${OLS4_PLUGIN_ENABLED:-0}"
OLS4_PLUGIN_CONFIGURED="${OLS4_PLUGIN_CONFIGURED:-0}"
OLS4_PLUGIN_HEALTHY="${OLS4_PLUGIN_HEALTHY:-0}"
OLS4_PLUGIN_HEALTH_REASON="${OLS4_PLUGIN_HEALTH_REASON:-}"

for boolean_name in OLS4_PLUGIN_ENABLED OLS4_PLUGIN_CONFIGURED OLS4_PLUGIN_HEALTHY; do
    case "${!boolean_name}" in
        0|1) ;;
        *)
            echo "${boolean_name} must be 0 or 1" >&2
            exit 2
            ;;
    esac
done

if [[ "${OLS4_PLUGIN_CONFIGURED}" == "1" && "${OLS4_PLUGIN_ENABLED}" != "1" ]]; then
    echo "OLS4_PLUGIN_CONFIGURED=1 requires OLS4_PLUGIN_ENABLED=1" >&2
    exit 2
fi
if [[ "${OLS4_PLUGIN_HEALTHY}" == "1" && "${OLS4_PLUGIN_CONFIGURED}" != "1" ]]; then
    echo "OLS4_PLUGIN_HEALTHY=1 requires OLS4_PLUGIN_CONFIGURED=1" >&2
    exit 2
fi
if [[ "${OLS4_PLUGIN_HEALTHY}" == "1" && -n "${OLS4_PLUGIN_HEALTH_REASON}" ]]; then
    echo "OLS4_PLUGIN_HEALTH_REASON must be empty when OLS4_PLUGIN_HEALTHY=1" >&2
    exit 2
fi

"${COMPOSE[@]}" run --rm --no-deps -T \
    -e "OLS4_PLUGIN_ENABLED=${OLS4_PLUGIN_ENABLED}" \
    -e "OLS4_PLUGIN_CONFIGURED=${OLS4_PLUGIN_CONFIGURED}" \
    -e "OLS4_PLUGIN_HEALTHY=${OLS4_PLUGIN_HEALTHY}" \
    -e "OLS4_PLUGIN_HEALTH_REASON=${OLS4_PLUGIN_HEALTH_REASON}" \
    --entrypoint python api -c '
import json
import os
import sys

from app.plugins.ols4 import official_ols4_manifest, sign_official_ols4_manifest


def as_bool(name: str) -> bool:
    return os.environ[name] == "1"


signing_key = os.environ.get("SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY", "")
if not signing_key:
    print("SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY is required", file=sys.stderr)
    raise SystemExit(2)

manifest = official_ols4_manifest(
    enabled=as_bool("OLS4_PLUGIN_ENABLED"),
    configured=as_bool("OLS4_PLUGIN_CONFIGURED"),
    healthy=as_bool("OLS4_PLUGIN_HEALTHY"),
    health_reason=os.environ.get("OLS4_PLUGIN_HEALTH_REASON") or None,
)
signed = sign_official_ols4_manifest(manifest, signing_key)
print(json.dumps([signed.model_dump(mode="json")], separators=(",", ":"), sort_keys=True))
'

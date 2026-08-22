#!/usr/bin/env bash
# Verify the public Cloudflare Tunnel path without handling its token.
# Usage:
#   CLOUDFLARE_TUNNEL_HEALTH_URL=https://api.example.com/api/v1/health/live \
#     bash deploy/scripts/verify-cloudflare-tunnel.sh
set -euo pipefail

health_url="${CLOUDFLARE_TUNNEL_HEALTH_URL:-}"
base_url="${CLOUDFLARE_TUNNEL_BASE_URL:-}"
timeout_seconds="${CLOUDFLARE_TUNNEL_HEALTH_TIMEOUT:-15}"

if [[ -z "${health_url}" ]]; then
    echo "CLOUDFLARE_TUNNEL_HEALTH_URL is required" >&2
    exit 2
fi

if [[ "${health_url}" != https://* ]]; then
    echo "CLOUDFLARE_TUNNEL_HEALTH_URL must use https://" >&2
    exit 2
fi

if [[ -z "${base_url}" ]]; then
    # Derive only from the documented fixed health suffix. A typo must not
    # silently turn a partial URL into an access-control probe target.
    health_suffix="/api/v1/health/live"
    if [[ "${health_url}" != *"${health_suffix}" ]]; then
        echo "CLOUDFLARE_TUNNEL_BASE_URL is required when health URL does not end in ${health_suffix}" >&2
        exit 2
    fi
    base_url="${health_url%${health_suffix}}"
fi

base_url="${base_url%/}"
if [[ "${base_url}" != https://* ]]; then
    echo "CLOUDFLARE_TUNNEL_BASE_URL must use https://" >&2
    exit 2
fi

if ! [[ "${timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
    echo "CLOUDFLARE_TUNNEL_HEALTH_TIMEOUT must be a positive integer" >&2
    exit 2
fi

curl --fail --silent --show-error --location --max-time "${timeout_seconds}" "${health_url}"
echo "Cloudflare Tunnel health check passed: ${health_url}"

echo "Verify forbidden public paths"
for path in \
    "/api/v1/admin" \
    "/api/v1/admin/users" \
    "/minio/" \
    "/metrics" \
    "/mcp" \
    "/__tunnel-negative-probe__"; do
    status_code="$(
        curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
            --max-time "${timeout_seconds}" "${base_url}${path}"
    )"
    if [[ "${status_code}" != "404" ]]; then
        echo "${base_url}${path}: expected HTTP 404, got ${status_code}" >&2
        exit 1
    fi
done

echo "Cloudflare Tunnel negative probes passed: ${base_url}"

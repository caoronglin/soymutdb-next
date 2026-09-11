#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — MCP authenticated transport smoke (single source for CI)
# =============================================================================
# Builds the MCP image, runs it behind an nginx reverse proxy configured exactly
# like production (nginx/conf.d/mcp.conf semantics), and asserts the auth
# contract:
#
#   1. no Authorization header           -> 401
#   2. trailing-slash canonical redirect -> 308 (with a valid token)
#   3. wrong bearer token                -> 401
#   4. correct bearer token              -> 2xx from the canonical /mcp endpoint
#
# The readiness wait tolerates the streamable-HTTP startup race: the proxy can
# answer 401 before the upstream is listening, so only the authorized request
# proves the server is up.
#
# Usage: bash scripts/mcp-transport-smoke.sh
# Env:   SOYMUTDB_MCP_SMOKE_PORT (default 8081)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

IMAGE="soymutdb-mcp:ci-smoke"
NETWORK="soymutdb-mcp-smoke"
SERVER_CONTAINER="soymutdb-mcp-smoke-server"
PROXY_CONTAINER="soymutdb-mcp-smoke-nginx"
PROXY_CONFIG=""
TOKEN="ci-test-token"
PORT="${SOYMUTDB_MCP_SMOKE_PORT:-8081}"

cleanup() {
  docker rm -f "${PROXY_CONTAINER}" >/dev/null 2>&1 || true
  docker rm -f "${SERVER_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
  [[ -n "${PROXY_CONFIG}" ]] && rm -f "${PROXY_CONFIG}" || true
  return 0
}
trap cleanup EXIT

echo "1) build MCP image"
docker build -t "${IMAGE}" apps/mcp-server

echo "2) start MCP server + authenticated reverse proxy"
docker network create "${NETWORK}" >/dev/null 2>&1 || true
docker run -d --network "${NETWORK}" --name "${SERVER_CONTAINER}" \
  -e "SOYMUTDB_MCP_API_TOKEN=${TOKEN}" "${IMAGE}" >/dev/null

PROXY_CONFIG="$(mktemp)"
cat > "${PROXY_CONFIG}" <<'NGINX'
worker_processes 1;
events {}
http {
  resolver 127.0.0.11 valid=30s ipv6=off;
  limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/s;
  server {
    listen 80;
    location = /mcp/ {
      if ($http_authorization = "") { return 401; }
      return 308 /mcp;
    }
    location = /mcp {
      if ($http_authorization = "") { return 401; }
      limit_req zone=auth burst=10 nodelay;
      set $mcp_upstream http://soymutdb-mcp-smoke-server:9000;
      proxy_pass $mcp_upstream;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_set_header X-Request-ID $request_id;
      proxy_buffering off;
      proxy_cache off;
      proxy_read_timeout 600s;
      proxy_send_timeout 600s;
      proxy_connect_timeout 10s;
    }
  }
}
NGINX

docker run -d --network "${NETWORK}" --name "${PROXY_CONTAINER}" \
  -p "127.0.0.1:${PORT}:80" \
  -v "${PROXY_CONFIG}:/etc/nginx/nginx.conf:ro" \
  nginx:1.27-alpine >/dev/null

PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"ci","version":"1"}}}'
BASE="http://127.0.0.1:${PORT}/mcp"

post_status() {
  # $1 = url, rest = extra curl args
  local url="$1"; shift
  curl --silent --output /dev/null --write-out '%{http_code}' \
    -X POST "${url}" -H 'Content-Type: application/json' "$@" -d "${PAYLOAD}" || true
}

echo "3) wait for the authenticated upstream"
code=000
for _ in $(seq 1 60); do
  code="$(post_status "${BASE}" -H 'Accept: application/json, text/event-stream' \
    -H "Authorization: Bearer ${TOKEN}")"
  if [[ "${code}" -ge 200 && "${code}" -lt 300 ]]; then break; fi
  sleep 2
done
if [[ ! "${code}" -ge 200 || ! "${code}" -lt 300 ]]; then
  docker logs "${SERVER_CONTAINER}" >&2 || true
  docker logs "${PROXY_CONTAINER}" >&2 || true
  echo "MCP server never became ready (last status: ${code})" >&2
  exit 1
fi

echo "4) assert auth contract"
unauthenticated="$(post_status "${BASE}")"
[[ "${unauthenticated}" == "401" ]] || {
  echo "expected 401 without Authorization, got ${unauthenticated}" >&2; exit 1
}

slash="$(post_status "${BASE}/" -H "Authorization: Bearer ${TOKEN}")"
[[ "${slash}" == "308" ]] || {
  echo "expected 308 for the trailing-slash form, got ${slash}" >&2; exit 1
}

wrong="$(post_status "${BASE}" -H 'Authorization: Bearer wrong')"
[[ "${wrong}" == "401" ]] || {
  echo "expected 401 for a wrong bearer token, got ${wrong}" >&2; exit 1
}

echo "MCP transport smoke passed"

#!/usr/bin/env bash
set -euo pipefail

# Load the deliberately legacy schema into the CI ClickHouse instance.  The
# migration runner is kept separate so this fixture exercises its real entry
# point rather than a test-only implementation.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
HOST="${SOYMUTDB_CLICKHOUSE_HOST:-127.0.0.1}"
PORT="${SOYMUTDB_CLICKHOUSE_PORT:-8123}"
USER="${SOYMUTDB_CLICKHOUSE_USER:-default}"
PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-}" 

curl --fail --silent --show-error \
  "http://${HOST}:${PORT}/?query=CREATE%20DATABASE%20IF%20NOT%20EXISTS%20soymutdb" \
  -u "${USER}:${PASSWORD}" >/dev/null

curl --fail --silent --show-error \
  "http://${HOST}:${PORT}/?database=soymutdb&multiquery=1" \
  -u "${USER}:${PASSWORD}" \
  --data-binary @"${ROOT}/infra/clickhouse/fixture_legacy.sql" >/dev/null

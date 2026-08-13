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
DATABASE="${SOYMUTDB_CLICKHOUSE_DATABASE:-soymutdb}"

run_query() {
  local query_file="$1"
  local query_database="${2:-}"
  local response_file
  local http_code
  local query_url="http://${HOST}:${PORT}/"

  if [[ -n "${query_database}" ]]; then
    query_url="${query_url}?database=${query_database}"
  fi

  response_file="$(mktemp)"
  set +e
  http_code="$(curl --silent --show-error \
    --output "${response_file}" --write-out '%{http_code}' \
    "${query_url}" \
    -u "${USER}:${PASSWORD}" --data-binary @"${query_file}")"
  local curl_status=$?
  set -e

  if (( curl_status != 0 )); then
    printf 'ClickHouse request failed (curl status %s); response body:\n' "${curl_status}" >&2
    cat "${response_file}" >&2
    rm -f "${response_file}"
    return "${curl_status}"
  fi
  if [[ "${http_code}" -ge 400 ]]; then
    printf 'ClickHouse returned HTTP %s; response body:\n' "${http_code}" >&2
    cat "${response_file}" >&2
    rm -f "${response_file}"
    return 1
  fi
  rm -f "${response_file}"
}

database_query="$(mktemp)"
printf 'CREATE DATABASE IF NOT EXISTS %s\n' "${DATABASE}" > "${database_query}"
run_query "${database_query}"
rm -f "${database_query}"

statement_dir="$(mktemp -d)"
awk -v prefix="${statement_dir}/statement-" '
  BEGIN { statement = 0; output = prefix statement }
  {
    print > output
    if ($0 ~ /;[[:space:]]*$/) {
      close(output)
      statement++
      output = prefix statement
    }
  }
' "${ROOT}/infra/clickhouse/fixture_legacy.sql"

for statement in "${statement_dir}"/statement-*; do
  [[ -s "${statement}" ]] || continue
  run_query "${statement}" "${DATABASE}"
done
rm -rf "${statement_dir}"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0

for project in api worker; do
  lock="${ROOT}/apps/${project}/uv.lock"
  if [[ ! -s "${lock}" ]] || ! grep -q '^version = 1$' "${lock}"; then
    echo "FAIL: apps/${project}/uv.lock is missing, empty, or not a uv lockfile" >&2
    fail=1
  fi
done

if grep -RInE 'touch apps/(api|worker)/uv\.lock|uv\.lock\*' "${ROOT}/.github" "${ROOT}/infra" "${ROOT}/apps" 2>/dev/null; then
  echo "FAIL: Docker/CI still relies on uv.lock placeholders or globs" >&2
  fail=1
fi

# Only non-empty fallbacks for credential-bearing variables are secret defaults.
# Empty fallbacks retain the application-level fail-fast validation, and values
# such as JBROWSE_BIND_ADDRESS or *_FILE paths are operational configuration.
if grep -nE '\$\{([A-Z0-9_]+_)?(SECRET|PASSWORD|PASSWD|TOKEN|KEY|CREDENTIAL):-[^}]+' "${ROOT}/docker-compose.yml"; then
  echo "FAIL: production compose contains insecure secret defaults" >&2
  fail=1
fi

if grep -nE 'GF_SECURITY_ADMIN_PASSWORD: .*:-' "${ROOT}/docker-compose.yml"; then
  echo "FAIL: Grafana admin password falls back to a default" >&2
  fail=1
fi

if grep -nE '^[[:space:]]*- "[0-9]+:[0-9]+' "${ROOT}/docker-compose.yml"; then
  echo "FAIL: production compose publishes ports without an explicit bind address" >&2
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "OK: supply-chain checks passed"

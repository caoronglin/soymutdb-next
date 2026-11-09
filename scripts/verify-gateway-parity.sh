#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — Go gateway / Python API contract parity
# =============================================================================
# Fetches GET /api/v1/stats/homepage from both the authoritative Python API and
# the staged Go gateway and fails unless the parsed JSON bodies are identical.
# Key order is irrelevant (both are JSON objects), but every key must match,
# including null release metadata and the Indel fold.
#
# Usage:
#   bash scripts/verify-gateway-parity.sh
#
# Env:
#   SOYMUTDB_PARITY_PYTHON_URL   default http://127.0.0.1:18010/api/v1/stats/homepage
#   SOYMUTDB_PARITY_GATEWAY_URL  default http://127.0.0.1:18020/api/v1/stats/homepage
# =============================================================================
set -euo pipefail

PYTHON_URL="${SOYMUTDB_PARITY_PYTHON_URL:-http://127.0.0.1:18010/api/v1/stats/homepage}"
GATEWAY_URL="${SOYMUTDB_PARITY_GATEWAY_URL:-http://127.0.0.1:18020/api/v1/stats/homepage}"

python3 - "${PYTHON_URL}" "${GATEWAY_URL}" <<'PY'
import json
import sys
import urllib.error
import urllib.request

python_url, gateway_url = sys.argv[1], sys.argv[2]


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read().decode("utf-8")
    except Exception as error:  # noqa: BLE001 - network errors are the failure
        raise SystemExit(f"FAIL cannot reach {url}: {error}")
    return status, json.loads(body)


status_a, body_a = fetch(python_url)
status_b, body_b = fetch(gateway_url)

print(f"python  {status_a} {python_url}")
print(json.dumps(body_a, sort_keys=True))
print(f"gateway {status_b} {gateway_url}")
print(json.dumps(body_b, sort_keys=True))

if status_a != status_b:
    raise SystemExit(f"FAIL status mismatch: python={status_a} gateway={status_b}")
if body_a != body_b:
    raise SystemExit("FAIL body mismatch between the Python API and the Go gateway")
print("OK gateway parity holds")
PY
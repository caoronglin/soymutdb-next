#!/usr/bin/env bash
# Byte/semantic parity check for a read endpoint the Go gateway answers locally.
#
# The gateway is published-only by design: with no active published release it
# answers an empty list, while the Python dev API may fall back to a draft when
# SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED is on. That difference is intentional and
# is NOT a parity failure. To compare like with like this script temporarily
# publishes the release, asks both servers, then restores the exact original
# state -- including the case where there was no active release at all.
#
# Usage:
#   SOYMUTDB_GATEWAY_URL=http://127.0.0.1:18099 \
#   SOYMUTDB_API_URL=http://127.0.0.1:18010 \
#   bash apps/gateway-go/scripts/check-read-parity.sh /api/v1/genes/assemblies
set -euo pipefail

ROUTE="${1:-/api/v1/genes/assemblies}"
GATEWAY="${SOYMUTDB_GATEWAY_URL:?set SOYMUTDB_GATEWAY_URL}"
API="${SOYMUTDB_API_URL:?set SOYMUTDB_API_URL}"
# scripts/ -> gateway-go/ -> apps/ -> repository root
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
API_PYTHON="${SOYMUTDB_API_PYTHON:-$REPO_ROOT/apps/api/.venv/bin/python}"

export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# The DSN comes from the running API's environment when available, otherwise
# from the operator. Never hard-code a credential in the script.
if [[ -z "${SOYMUTDB_DATABASE_URL:-}" ]]; then
  api_pid="$(pgrep -f 'uvicorn app.main:app.*--port 18010' | head -1 || true)"
  if [[ -n "$api_pid" ]]; then
    SOYMUTDB_DATABASE_URL="$(tr '\0' '\n' <"/proc/$api_pid/environ" |
      grep '^SOYMUTDB_DATABASE_URL=' | head -1 | cut -d= -f2- || true)"
  fi
fi
: "${SOYMUTDB_DATABASE_URL:?set SOYMUTDB_DATABASE_URL (or run the API locally)}"
export SOYMUTDB_DATABASE_URL

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The gateway is published-only by design. With no active published release it
# correctly answers an empty list while the Python dev API may fall back to a
# draft. That is an intentional difference, not a parity failure. This script
# compares the two servers under the SAME published scope and never mutates the
# database: the operator sets up the release (in a throwaway database) first.
#
# Verify the precondition instead of changing data behind the operator's back.
"$API_PYTHON" - <<'PY'
import asyncio, os
import asyncpg

async def main():
    dsn = os.environ["SOYMUTDB_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    db = await asyncpg.connect(dsn)
    try:
        row = await db.fetchrow(
            "SELECT r.id, r.status FROM active_release a "
            "JOIN releases r ON r.id = a.release_id WHERE a.id = 1 AND r.status = 'published'"
        )
        if row is None:
            raise SystemExit(
                "no active published release: set one in a throwaway database "
                "before running the parity check"
            )
        print(f"published release {row['id']} is active")
    finally:
        await db.close()

asyncio.run(main())
PY

# Clear cache-aside entries so the API reads the same published scope.
if [[ -n "${SOYMUTDB_REDIS_URL:-}" ]] && [[ -n "${api_pid:-}" ]]; then
  SOYMUTDB_REDIS_URL="$(tr '\0' '\n' <"/proc/$api_pid/environ" |
    grep '^SOYMUTDB_REDIS_URL=' | head -1 | cut -d= -f2- || true)"
fi
if [[ -n "${SOYMUTDB_REDIS_URL:-}" ]]; then
  export SOYMUTDB_REDIS_URL
  "$API_PYTHON" - <<'PY'
import os, redis
r = redis.Redis.from_url(os.environ["SOYMUTDB_REDIS_URL"])
for pattern in ("cache:genes:assemblies:*", "cache:release-context:*", "cache:stats:homepage:*"):
    for key in list(r.scan_iter(match=pattern)):
        r.delete(key)
PY
fi

sleep 1

# 4) Compare parsed JSON. Whitespace is not a contract difference: Go's
#    encoder pretty-spaces while FastAPI emits compact JSON.
curl -fsS "$GATEWAY$ROUTE" >"$TMP/gateway.json"
curl -fsS "$API$ROUTE" >"$TMP/api.json"
"$API_PYTHON" - "$TMP/gateway.json" "$TMP/api.json" "$ROUTE" <<'PY'
import json, sys
a, b, route = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]
if a != b:
    print(f"FAIL {route}: gateway and API bodies differ")
    print("gateway:", json.dumps(a, ensure_ascii=False)[:400])
    print("api    :", json.dumps(b, ensure_ascii=False)[:400])
    raise SystemExit(1)
print(f"OK {route}: parsed JSON is identical")
PY

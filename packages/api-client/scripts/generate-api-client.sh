#!/usr/bin/env bash
# Regenerate the typed API client from the backend OpenAPI schema.
#
#  1. Exports the FastAPI OpenAPI document to packages/api-client/openapi.json
#     (committed as the contract snapshot).
#  2. Runs openapi-typescript to produce src/generated/openapi.d.ts.
#
# The generated file is NEVER edited by hand — re-run this script after any
# backend contract change.  Run from anywhere: pnpm --filter @soymutdb/api-client generate:api-client
set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/../.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
API_PYTHON="${SOYMUTDB_API_PYTHON:-$API_DIR/.venv/bin/python}"

echo ">> exporting OpenAPI from backend..."
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$API_PYTHON" "$API_DIR/scripts/export_openapi.py" \
  --output "$PKG_DIR/openapi.json" \
  --error-codes-output "$PKG_DIR/error-codes.json"

echo ">> generating TypeScript client types..."
pnpm exec openapi-typescript "$PKG_DIR/openapi.json" \
  -o "$PKG_DIR/src/generated/openapi.d.ts"

echo ">> done: packages/api-client/src/generated/openapi.d.ts"

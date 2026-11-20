#!/usr/bin/env bash
# Regenerate the typed API client from the backend OpenAPI schema.
#
#  1. Exports the FastAPI OpenAPI document to packages/api-client/openapi.json
#     (committed as the contract snapshot), normalizing the pydantic
#     serialization details that are not contract changes. See
#     scripts/export_contract.py.
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
"$API_PYTHON" "$PKG_DIR/scripts/export_contract.py" \
  --openapi "$PKG_DIR/openapi.json" \
  --error-codes "$PKG_DIR/error-codes.json"

echo ">> generating TypeScript client types..."
pnpm exec openapi-typescript "$PKG_DIR/openapi.json" \
  -o "$PKG_DIR/src/generated/openapi.d.ts"

# Quote interface property names that collide with TypeScript *modifiers*.
# The API schema legitimately publishes an `abstract` field (publication
# metadata); openapi-typescript emits `abstract: string | null`, which is valid
# TypeScript and passes `tsc`, but opengrep's TS parser reads it as a class
# modifier and aborts parsing the whole file. That leaves an entire scanner
# lane silently incomplete in pi-lens. A quoted property name is exactly the
# same type and the same runtime shape -- only the parser stops guessing.
# Keep this in the generator: the generated file is never hand-edited.
# Keep this in the generator: the generated file is never hand-edited.
"$API_PYTHON" "$PKG_DIR/scripts/quote_reserved_properties.py" \
  "$PKG_DIR/src/generated/openapi.d.ts"

echo ">> done: packages/api-client/src/generated/openapi.d.ts"

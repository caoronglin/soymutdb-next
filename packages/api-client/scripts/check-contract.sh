#!/usr/bin/env bash
# Contract check: the committed generated client must match the CURRENT
# backend OpenAPI document exactly.
#
# Exports a fresh OpenAPI schema, regenerates the client types into a temp
# dir, and diffs against the committed src/generated/openapi.d.ts.
# Exits non-zero (CI failure) when they differ.
set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/../.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
API_PYTHON="${SOYMUTDB_API_PYTHON:-$API_DIR/.venv/bin/python}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo ">> exporting OpenAPI from backend..."
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
"$API_PYTHON" "$PKG_DIR/scripts/export_contract.py" \
  --openapi "$TMP_DIR/openapi.json"

# Which committed file moved. "CONTRACT DEBT" alone compares a file nobody can
# read in a log (the temp regeneration) against one nobody edited, so it names
# neither the cause nor the fix. Diffing the *documents* first separates the two
# states: a snapshot that disagrees, which is what a backend change looks like,
# versus a snapshot that matches while only the generated client went stale.
if ! diff -q "$TMP_DIR/openapi.json" "$PKG_DIR/openapi.json" >/dev/null; then
  echo "CONTRACT DEBT: packages/api-client/openapi.json is out of sync with app.main:app."
  # Names, not text: both files are single-line JSON exports, so a plain diff
  # would print the whole API description as line 1 and bury the actual change.
  python3 "${PKG_DIR}/scripts/summarize_contract_drift.py" \
    "$PKG_DIR/openapi.json" "$TMP_DIR/openapi.json" || true
  echo "Run: pnpm --filter @soymutdb/api-client generate:api-client"
  exit 1
fi

echo ">> regenerating client types in temp dir..."
(cd "$PKG_DIR" && pnpm exec openapi-typescript "$TMP_DIR/openapi.json" \
  -o "$TMP_DIR/openapi.d.ts"
)

if ! diff -q "$TMP_DIR/openapi.d.ts" "$PKG_DIR/src/generated/openapi.d.ts" >/dev/null; then
  echo "CONTRACT DEBT: packages/api-client/openapi.json matches the backend, but"
  echo "packages/api-client/src/generated/openapi.d.ts does not match the snapshot."
  echo "Run: pnpm --filter @soymutdb/api-client generate:api-client"
  exit 1
else
  echo "OK: client schema in sync with backend OpenAPI."
fi

echo ">> checking handwritten route visibility..."
python3 "$REPO_ROOT/scripts/contract_visibility.py" \
  --schema "$TMP_DIR/openapi.json" \
  --client-root "$PKG_DIR/src" \
  --baseline "$PKG_DIR/contract-visibility-baseline.json"

# A stale-base branch once reverted BOTH the router and the generated
# snapshot, so the document diff above compared a reverted backend with a
# reverted document and stayed green. Pin the endpoint set in source; this
# needs no API venv and cannot be co-reverted with the snapshot.
# The export above runs first because it is the check that names the cause when
# both moved; this one names the defect when only source moved.
echo ">> checking sequence-tools endpoints against committed source..."
python3 "$REPO_ROOT/scripts/check_sequence_tools_endpoints.py"

# The pin is only as good as its own configuration: deleting one route from
# REQUIRED_ENDPOINTS lets a stale-base rebase pass while the guard above and
# every other assertion stay green. These tests pin the pin from a second file.
python3 "$REPO_ROOT/scripts/test_check_sequence_tools_endpoints.py"

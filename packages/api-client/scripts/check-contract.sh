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
"$API_PYTHON" "$API_DIR/scripts/export_openapi.py" \
  --output "$TMP_DIR/openapi.json"

echo ">> regenerating client types in temp dir..."
(cd "$PKG_DIR" && pnpm exec openapi-typescript "$TMP_DIR/openapi.json" \
  -o "$TMP_DIR/openapi.d.ts"
)

if ! diff -q "$TMP_DIR/openapi.d.ts" "$PKG_DIR/src/generated/openapi.d.ts" >/dev/null; then
  # TEMPORARY DIAGNOSTIC: the committed snapshot matches a local export of the
  # same models, so print what the CI interpreter actually emits.
  echo "=== DIAGNOSTIC d.ts diff ==="
  diff -u "$PKG_DIR/src/generated/openapi.d.ts" "$TMP_DIR/openapi.d.ts" | head -120 || true
  echo "=== DIAGNOSTIC json head ==="
  head -c 400 "$TMP_DIR/openapi.json" || true
  echo
  echo "=== DIAGNOSTIC GeneDetail ==="
  "$API_PYTHON" - "$TMP_DIR/openapi.json" <<'DIAG' || true
import json, sys
doc = json.load(open(sys.argv[1]))
for name in ("GeneDetail", "EvidenceTag", "SequenceAvailability"):
    print(name, json.dumps(doc["components"]["schemas"].get(name), indent=1)[:1500])
DIAG
  echo "=== DIAGNOSTIC committed ==="
  "$API_PYTHON" - "$PKG_DIR/openapi.json" <<'DIAG' || true
import json, sys
doc = json.load(open(sys.argv[1]))
for name in ("GeneDetail", "EvidenceTag", "SequenceAvailability"):
    print(name, json.dumps(doc["components"]["schemas"].get(name), indent=1)[:1500])
DIAG
  echo "CONTRACT DEBT: generated client is out of sync with the backend OpenAPI."
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

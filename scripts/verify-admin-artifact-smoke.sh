#!/usr/bin/env bash
# Offline browser smoke for the emitted admin production artifact.
# Shared entry point for CI/local runs; no credentials or mock admin login.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v pnpm >/dev/null || { echo "pnpm is required" >&2; exit 2; }
[[ -d e2e/node_modules ]] || { echo "Run npm ci --prefix e2e first" >&2; exit 2; }

# Build the actual Umi/AntD bundle; a dev server would mask missing assets.
# This is a throwaway, loopback-only smoke artifact, never a release build.
# No VITE_API_BASE_URL: the runtime keeps same-origin /api/v1.
SOYMUTDB_ADMIN_API_URL=http://127.0.0.1:4174 SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=1 VITE_API_BASE_URL= VITE_BASE_URL=/ pnpm --filter @soymutdb/admin build
[[ -f apps/admin/dist/index.html ]] || {
  echo "Missing apps/admin/dist/index.html after build" >&2
  exit 1
}
(
  cd e2e
  CI=1 ./node_modules/.bin/playwright test -c playwright-admin-production.config.ts
)

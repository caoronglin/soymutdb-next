#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — frontend verification (single source for CI and local runs)
# =============================================================================
# Owns the ordered, blocking frontend gates:
#   i18n key parity → offline demo build → placeholder scan → bundle budget →
#   unit tests → lint → typecheck → page/query/admin architecture checks →
#   OpenAPI client contract.
#
# Every gate is hard: a failure exits non-zero immediately with the failing gate
# named. No gate may be skipped to make a pipeline green.
#
# Requirements: pnpm 12.5.1, Node 24.x, Python 3.14 (OpenAPI export).
# Usage: bash scripts/verify-frontend-artifacts.sh
# Env:    SOYMUTDB_CI_SKIP_CONTRACT=1 skips only the OpenAPI client check, which
#         requires the API virtualenv; used by build-only callers.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SOYMUTDB_CI_DEMO_MODE="${SOYMUTDB_CI_DEMO_MODE:-demo}"
SOYMUTDB_CI_DEMO_API_URL="${SOYMUTDB_CI_DEMO_API_URL:-https://api.soymutdb.test}"
SOYMUTDB_CI_DEMO_JBROWSE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL:-https://jbrowse.soymutdb.test}"
# JBrowse's `_headers` injector refuses to publish a policy whose frame-ancestors
# cannot name the embedding origins, because `'self'` alone blocks the portal and
# the admin console on their own hostnames. Production must name the real
# origins; this offline fixture uses the same `.test` convention as the two
# origins above so the gate stays runnable without network access.
SOYMUTDB_CI_DEMO_PORTAL_URL="${SOYMUTDB_CI_DEMO_PORTAL_URL:-https://portal.soymutdb.test}"
SOYMUTDB_CI_DEMO_ADMIN_URL="${SOYMUTDB_CI_DEMO_ADMIN_URL:-https://admin.soymutdb.test}"

step() { printf '\n==> %s\n' "$*"; }

step "i18n locale key parity"
# `pnpm run <script> -- <args>` forwards the FIRST `--` as its own end-of-options
# marker and passes everything after it verbatim, so `-- --self-test` reached the
# script as a literal ["--", "--self-test"]: `node` then tried to open a file
# named "--" (observed on a real CNB build). Pass the flag alone.
pnpm --filter @soymutdb/i18n check:locale-keys --self-test
pnpm --filter @soymutdb/i18n check:locale-keys

step "Build all apps (offline demo fixture)"
VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}" \
VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}" \
SOYMUTDB_PORTAL_ORIGIN="${SOYMUTDB_CI_DEMO_PORTAL_URL}" \
SOYMUTDB_ADMIN_ORIGIN="${SOYMUTDB_CI_DEMO_ADMIN_URL}" \
  pnpm build

step "Scan demo artifact for placeholder origins"
bash "${REPO_ROOT}/scripts/check-production-artifact.sh" apps/web/dist --allow-demo

# `_headers` is copied verbatim into `dist/`, so a comment there is published
# text. Both of these read the emitted trees rather than the sources, and both
# were written but never called by any shared script — the artifact contract in
# `.github/workflows/baseline-validation.yml` was the only thing checking the
# published header files, and it reported a build with no build error to explain
# it. Run them here, after the build that produces their input.
step "Artifact header contract (CSP, placeholders, build-variable names)"
python3 scripts/check_artifact_headers.py

step "nginx security-header fragments"
python3 scripts/check_nginx_security_headers.py

step "Bundle size budget gate"
bash "${REPO_ROOT}/scripts/check-bundle-size.sh"

step "Workspace JS unit tests"
pnpm turbo run test

step "Lint"
pnpm turbo run lint

step "Typecheck"
pnpm turbo run typecheck

step "Page Builder registry contract"
python3 scripts/check_page_registry.py

step "Web query-key architecture"
python3 scripts/check_web_query_keys.py

step "Admin transport and session boundary"
python3 scripts/check_admin_content_architecture.py

if [[ "${SOYMUTDB_CI_SKIP_CONTRACT:-0}" != "1" ]]; then
  step "API client contract"
  pnpm --filter @soymutdb/api-client check:contract
fi

printf '\nfrontend verification passed\n'

#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — frontend verification (single source for CI and local runs)
# =============================================================================
# Owns the ordered, blocking frontend gates:
#   i18n key parity → offline demo build → placeholder scan → bundle budget →
#   unit tests → lint → typecheck → page/query/admin architecture checks →
#   OpenAPI client contract.
#
# The bundle stage runs twice over: scripts/check-bundle-size.sh keeps the
# per-cache-group caps for the external portal, and the chart dependency closure
# gate runs for external, internal and admin through one shared checker so all
# three built trees are held to the same 370 KiB complete-dependency budget.
#
# Every gate is hard: a failure exits non-zero immediately with the failing gate
# named. No gate may be skipped to make a pipeline green.
#
# Requirements: pnpm 12.11.2, Node 26.13.0, Python 3.15 (OpenAPI export).
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
pnpm --filter @soymutdb/i18n-core check:locale-keys --self-test
pnpm --filter @soymutdb/i18n-core check:locale-keys

step "Build workspace packages and the single-tree apps (admin, jbrowse)"
# The portal is built once per site variant below; a third build through a
# full `pnpm build` pass was pure duplication (web built 3x per gate). Turbo
# still builds the shared workspace packages both paths import.
VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}" \
VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}" \
SOYMUTDB_PORTAL_ORIGIN="${SOYMUTDB_CI_DEMO_PORTAL_URL}" \
SOYMUTDB_ADMIN_ORIGIN="${SOYMUTDB_CI_DEMO_ADMIN_URL}" \
  pnpm turbo run build --filter='!@soymutdb/web'

step "Build the portal site variants (external + internal)"
# Both variants are complete builds; the external tree is the one the artifact
# checks below run against. `verify-site-variant-artifacts.sh` later reuses
# these trees (SOYMUTDB_SITE_VARIANTS_PREBUILT=1) instead of rebuilding them.
VITE_DEPLOYMENT_MODE="${SOYMUTDB_CI_DEMO_MODE}" \
VITE_API_BASE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
VITE_JBROWSE_BASE_URL="${SOYMUTDB_CI_DEMO_JBROWSE_URL}" \
SOYMUTDB_PORTAL_ORIGIN="${SOYMUTDB_CI_DEMO_PORTAL_URL}" \
SOYMUTDB_ADMIN_ORIGIN="${SOYMUTDB_CI_DEMO_ADMIN_URL}" \
SOYMUTDB_SITE_URL="${SOYMUTDB_CI_DEMO_API_URL}" \
  pnpm --filter @soymutdb/web build:sites

step "Scan demo artifact for placeholder origins"
bash "${REPO_ROOT}/scripts/check-production-artifact.sh" apps/web/dist/external --allow-demo

# `_headers` is copied verbatim into `dist/`, so a comment there is published
# text. Both of these read the emitted trees rather than the sources, and both
# were written but never called by any shared script — the artifact contract in
# `.github/workflows/baseline-validation.yml` was the only thing checking the
# published header files, and it reported a build with no build error to explain
# it. Run them here, after the build that produces their input.
step "Artifact header contract (CSP, placeholders, build-variable names)"
python3 scripts/check_artifact_headers.py

step "Artifact build-path guard (no build-machine paths in emitted bytes)"
python3 scripts/check_artifact_build_paths.py

step "App shell assets (favicon declared and present in built trees)"
python3 scripts/check_app_shell_assets.py

step "Visible i18n contract (hardcoded text budget)"
python3 scripts/check_visible_i18n.py
node scripts/check_visible_i18n_react.mjs --self-test
node scripts/check_visible_i18n_react.mjs

# The visible-text guard catches hardcoded copy; it cannot catch the opposite
# failure — a `t()` key that was never registered. i18next then falls back to
# `defaultValue`, so a zh console prints English and every gate stays green.
step "Admin i18n key guard (every referenced key exists in zh and en)"
node scripts/test_admin_i18n_keys_guard.mjs
node scripts/check-admin-i18n-keys.mjs

# A call site may pass a different option name than the catalog placeholder
# (`conds` vs `{{conditions}}`); i18next then renders the raw braces and no other
# gate notices. exppattern shipped exactly that, so check the call sites.
step "i18n interpolation guard (t() options cover catalog placeholders)"
python3 scripts/check_i18n_interpolation.py

step "nginx security-header fragments"
python3 scripts/check_nginx_security_headers.py

step "Chart dependency closure budget (portal external + internal, admin)"
# Every tree reports, then the gate decides: a failure in any of them fails this
# script. This step runs BEFORE the cache-group budgets on purpose, so a chart
# closure failure cannot hide the internal and admin results behind an early exit.
# `check-bundle-size.sh` re-runs the same checker for the external tree, which is
# what makes that script a complete gate on its own.
chart_closure_fail=0
for closure_dist in apps/web/dist/external apps/web/dist/internal apps/admin/dist; do
  if ! python3 "${REPO_ROOT}/scripts/chart_closure_budget.py" --dist "${closure_dist}"; then
    chart_closure_fail=1
  fi
done
if [[ "${chart_closure_fail}" -ne 0 ]]; then
  echo "frontend verification: chart dependency closure budget FAILED" >&2
  exit 1
fi

step "Bundle size budget gate"
bash "${REPO_ROOT}/scripts/check-bundle-size.sh" apps/web/dist/external/assets

step "Workspace JS unit tests"
pnpm turbo run test

step "Lint"
pnpm turbo run lint

step "Typecheck"
pnpm turbo run typecheck

step "Vue retirement (shipped entry graphs + workspace scan)"
# Assert each app's *shipped* React/Umi entry graph is free of Vue, then scan
# the whole workspace for any remaining Vue source, manifest, catalog or
# lockfile residue. A React file re-importing a .vue component, or a leftover
# Vue dependency, fails the gate instead of only misbehaving at runtime.
node scripts/check-react-entry-graph.mjs
node scripts/check-vue-retirement.mjs

step "Page Builder registry contract"
python3 scripts/check_page_registry.py

step "Web query-key architecture"
python3 scripts/check_web_query_keys.py

step "Variants row-key source and regression-suite contract"
python3 scripts/check_variant_row_key_contract.py

step "Backend-editable content key contract"
python3 scripts/check_content_key_contract.py

step "Admin transport and session boundary"
python3 scripts/check_admin_content_architecture.py

if [[ "${SOYMUTDB_CI_SKIP_CONTRACT:-0}" != "1" ]]; then
  step "API client contract"
  pnpm --filter @soymutdb/api-client check:contract
fi

printf '\nfrontend verification passed\n'

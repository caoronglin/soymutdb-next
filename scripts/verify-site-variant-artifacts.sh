#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — dual-site artifact build + isolation verification
# =============================================================================
# AGENTS.md requires the external and internal site variants to be separate
# build/deployment boundaries, and `docs/adr/0001` treats the published artifact
# as the unit of verification. The two variants were only ever built by hand
# (deploy/cloudflare.md), so the isolation contract had no regression gate.
#
# This script builds both variants offline (demo mode, reserved origins), then
# asserts the properties the release procedure documents:
#
#   * internal HTML carries `noindex, nofollow, noarchive`;
#   * internal does not embed the public content snapshot;
#   * external embeds none of the internal-only values (checked with the
#     repository's own artifact isolation checker).
#
# It is deliberately part of the frontend gate: the variants are built from the
# same commit as the public artifact, so a leak cannot ride a later deploy.
#
# Usage: bash scripts/verify-site-variant-artifacts.sh
# Env:   SOYMUTDB_INTERNAL_SITE_URL  internal canonical origin (default: a
#                                    reserved .invalid host, never a real one)
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# `build-sites.ts` treats CI=true as a production build and demands
# SOYMUTDB_SITE_URL / SOYMUTDB_INTERNAL_SITE_URL; this gate is an offline
# verification, so CI is cleared for the child process only.
unset CI

# The site variants default to internal noindex; the sentinel is the marker the
# external artifact must never contain.
NOINDEX_MARKER="noindex, nofollow, noarchive"
INTERNAL_SITE_URL="${SOYMUTDB_INTERNAL_SITE_URL:-https://internal.soymutdb.invalid}"

export VITE_DEPLOYMENT_MODE="demo"
export VITE_API_BASE_URL="${SOYMUTDB_SITE_VARIANT_API_URL:-https://api.soymutdb.test}"
export VITE_JBROWSE_BASE_URL="${SOYMUTDB_SITE_VARIANT_JBROWSE_URL:-https://jbrowse.soymutdb.test}"
export SOYMUTDB_INTERNAL_SITE_URL="${INTERNAL_SITE_URL}"

if [[ "${SOYMUTDB_SITE_VARIANTS_PREBUILT:-0}" == "1" ]]; then
  # The frontend gate already built both variants from the same commit; reuse
  # them instead of paying for two more Vite builds in the same pipeline run.
  echo "[site-variants] reusing the prebuilt external + internal artifacts"
  if [[ ! -d apps/web/dist/external || ! -d apps/web/dist/internal ]]; then
    echo "FAIL: SOYMUTDB_SITE_VARIANTS_PREBUILT=1 but apps/web/dist/{external,internal} is missing" >&2
    exit 1
  fi
else
  echo "[site-variants] building external + internal artifacts (demo, offline)"
  pnpm --filter @soymutdb/web build:sites
fi

echo "[site-variants] internal artifact must be noindex"
if ! grep -Rq "${NOINDEX_MARKER}" apps/web/dist/internal/*.html; then
  echo "FAIL: internal HTML does not carry '${NOINDEX_MARKER}'" >&2
  exit 1
fi

echo "[site-variants] internal artifact must not embed the public snapshot"
if [[ -e apps/web/dist/internal/data/content.json ]]; then
  echo "FAIL: internal artifact contains the public content snapshot" >&2
  exit 1
fi

echo "[site-variants] external artifact must not contain internal-only values"
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel "${NOINDEX_MARKER}"

echo "[site-variants] portal dual-site artifacts are built and isolated"

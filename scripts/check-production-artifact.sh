#!/usr/bin/env bash
# =============================================================================
# SoyMutDB — Production artifact scan hard gate
#
# Scans a built static tree and FAILS (exit 1) if any forbidden placeholder /
# demo marker that must never reach a production artifact is detected. Used as
# a hard gate after a production build so a demo/fallback build cannot be
# promoted as a real release.
#
# Forbidden markers (default):
#   * placeholder origins — api.example.com / example.com / change-me
#   * loopback binds baked into the artifact — localhost / 127.0.0.1
#   * demo fixture data — SMDB-00001
#   * demo fallback markers — Demo fixture / demonstration data / VITE_DEMO_MODE
#
# That set of surface markers is deliberately broad: these strings have no
# legitimate occurrence in a production release static tree.
#
# Usage:
#   bash scripts/check-production-artifact.sh [dist-dir] [--allow-demo]
#
#   dist-dir     default apps/web/dist   the static tree to scan
#   --allow-demo permit demo/flagship markers (use for the gh-pages DEMO
#                artifact, never for a production release). Still rejects
#                placeholder origins / loopback binds.
#
# Env:
#   CHECK_PRODUCTION_EXTRA_PATTERNS  (optional, comma-separated) extra regexes
#   CHECK_PRODUCTION_SKIP_PATTERN   (optional, comma-separated) regexes to skip
# =============================================================================
set -uo pipefail

DIST_DIR="${1:-apps/web/dist}"
ALLOW_DEMO=0
for arg in "$@"; do
  case "$arg" in
    --allow-demo) ALLOW_DEMO=1 ;;
  esac
done

if [ ! -d "$DIST_DIR" ]; then
  echo "FAIL: production artifact directory not found ($DIST_DIR) — build first" >&2
  exit 1
fi

# Always-blocked surface — placeholder origins / placeholder markers that must
# not be baked into ANY published artifact (a deployment mistake even on the
# gh-pages demo). Scanned across every file type.
# `api.example.com` / `jbrowse.example.com` are the two placeholder origins the
# portal is configured to replace; the generic `example.com` is intentionally
# NOT blocked because the Admin analytics help text legitimately references
# `www.example.com` as an example in its documentation string.
PATTERNS=(
  'api\.example\.com'
  'jbrowse\.example\.com'
  'change-me'
)

# Demo-only surface — real release copy never contains these. They are expected
# in the gh-pages DEMO artifact (which legitimately pre-renders SMDB-00001
# fixtures), so `--allow-demo` permits them, while the STRICT production gate
# rejects them outright.
if [ "$ALLOW_DEMO" -eq 0 ]; then
  PATTERNS+=(
    'SMDB-00001'
    'Demo fixture'
    'demonstration data'
    'VITE_DEMO_MODE'
  )
fi

# Loopback binds — only meaningful in deployment-facing text files (the SSG
# HTML meta CSP, _headers, nginx.conf). Skip emitted .js/.mjs bundles where a
# runtime fallback literal ("http://localhost:5175") legitimately survives
# minification even when a real origin is configured at build time.
LOOPBACK_PATTERNS=(
  'localhost'
  '127\.0\.0\.1'
)

# Optional extra / skip patterns from env (comma-separated).
if [ -n "${CHECK_PRODUCTION_EXTRA_PATTERNS:-}" ]; then
  IFS=',' read -r -a extra <<< "$CHECK_PRODUCTION_EXTRA_PATTERNS"
  PATTERNS+=("${extra[@]}")
fi

SKIP_RE=''
if [ -n "${CHECK_PRODUCTION_SKIP_PATTERN:-}" ]; then
  SKIP_RE="(${CHECK_PRODUCTION_SKIP_PATTERN})"
fi

fail=0
matched=0

scan_pattern() { # $1 = regex
  local regex="$1"
  # Use -r (recursive), -I (skip binary), -l (files only) so a single match
  # per file is reported once; skip the manifest itself which embeds the
  # concatenated file list by design.
  local files
  files=$(grep -rIl --exclude='manifest.json' --exclude='SHA256SUMS' -E "$regex" "$DIST_DIR" 2>/dev/null || true)
  [ -z "$files" ] && return 0
  matched=1
  while IFS= read -r f; do
    # Apply optional skip regex.
    if [ -n "$SKIP_RE" ] && grep -qE "$SKIP_RE" <<< "$f"; then
      continue
    fi
    fail=1
    echo "  FAIL  [$regex]  ${f#"$DIST_DIR"/}"
  done <<< "$files"
}

# Loopback scan: restrict to deployment-facing text files (not emitted JS).
scan_loopback() { # $1 = regex
    local regex="$1"
    local files
    files=$(grep -rIl \
      --exclude='manifest.json' \
      --exclude='SHA256SUMS' \
      --exclude='*.js' \
      --exclude='*.mjs' \
      --exclude='*.map' \
      -E "$regex" "$DIST_DIR" 2>/dev/null || true)
    [ -z "$files" ] && return 0
    matched=1
    while IFS= read -r f; do
        if [ -n "$SKIP_RE" ] && grep -qE "$SKIP_RE" <<< "$f"; then
            continue
        fi
        fail=1
        echo "  FAIL  [$regex]  ${f#"$DIST_DIR"/}"
    done <<< "$files"
}

echo "Production artifact scan:"
echo "  dir  = $DIST_DIR"
echo "  mode = $([ "$ALLOW_DEMO" -eq 1 ] && echo 'demo-allowed' || echo 'STRICT (no demo)' )"
for p in "${PATTERNS[@]}"; do
  scan_pattern "$p"
done
for p in "${LOOPBACK_PATTERNS[@]}"; do
  scan_loopback "$p"
done

if [ "$matched" -eq 0 ]; then
  echo "  (no forbidden placeholder / demo markers found)"
fi

if [ "$fail" -ne 0 ]; then
  echo "Production artifact scan: FAILED — placeholder/demo markers present; this must not be promoted as a release" >&2
  exit 1
fi
echo "Production artifact scan: OK"
exit 0

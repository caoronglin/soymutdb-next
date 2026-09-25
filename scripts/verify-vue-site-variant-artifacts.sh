#!/usr/bin/env bash
# =============================================================================
# Verify that the Vue portal builds separate external/internal artifacts and
# that static indexing metadata and internal origins stay in the right build.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

unset CI

NOINDEX_MARKER="noindex, nofollow, noarchive"
EXTERNAL_ORIGIN="https://external.soymutdb.invalid"
INTERNAL_ORIGIN="${SOYMUTDB_INTERNAL_SITE_URL:-https://internal.soymutdb.invalid}"
EXTERNAL_API_URL="https://api.external.soymutdb.test"
INTERNAL_API_URL="https://api.internal.soymutdb.test"
EXTERNAL_JBROWSE_URL="https://jbrowse.external.soymutdb.test"
INTERNAL_JBROWSE_URL="https://jbrowse.internal.soymutdb.test"

export VITE_DEPLOYMENT_MODE="demo"
export SOYMUTDB_EXTERNAL_API_URL="${EXTERNAL_API_URL}"
export SOYMUTDB_INTERNAL_API_URL="${INTERNAL_API_URL}"
export SOYMUTDB_EXTERNAL_JBROWSE_URL="${EXTERNAL_JBROWSE_URL}"
export SOYMUTDB_INTERNAL_JBROWSE_URL="${INTERNAL_JBROWSE_URL}"
export SOYMUTDB_SITE_URL="${EXTERNAL_ORIGIN}"
export SOYMUTDB_INTERNAL_SITE_URL="${INTERNAL_ORIGIN}"

echo "[site-variants] building both variants"
pnpm --filter @soymutdb/web build:sites

EXTERNAL_ROOT="apps/web/dist/external"
INTERNAL_ROOT="apps/web/dist/internal"
test -s "${EXTERNAL_ROOT}/index.html"
test -s "${INTERNAL_ROOT}/index.html"
test -s "${EXTERNAL_ROOT}/robots.txt"
test -s "${INTERNAL_ROOT}/robots.txt"
test -s "${EXTERNAL_ROOT}/sitemap.xml"
test ! -e "${INTERNAL_ROOT}/sitemap.xml"
test ! -e "${INTERNAL_ROOT}/data/content.json"

grep -Fq 'Allow: /' "${EXTERNAL_ROOT}/robots.txt"
grep -Fq 'Disallow: /' "${INTERNAL_ROOT}/robots.txt"
grep -Fq "${EXTERNAL_ORIGIN}" "${EXTERNAL_ROOT}/sitemap.xml"
grep -Rq "${INTERNAL_ORIGIN}" "${INTERNAL_ROOT}"
grep -Rq "${EXTERNAL_API_URL}" "${EXTERNAL_ROOT}"
grep -Rq "${INTERNAL_API_URL}" "${INTERNAL_ROOT}"
grep -Rq "${EXTERNAL_JBROWSE_URL}" "${EXTERNAL_ROOT}"
grep -Rq "${INTERNAL_JBROWSE_URL}" "${INTERNAL_ROOT}"
if grep -Rq "${EXTERNAL_ORIGIN}\|${EXTERNAL_API_URL}\|${EXTERNAL_JBROWSE_URL}" "${INTERNAL_ROOT}"; then
  echo "FAIL: internal Vue artifact contains an external origin" >&2
  exit 1
fi
if grep -Rq "${INTERNAL_API_URL}\|${INTERNAL_JBROWSE_URL}" "${EXTERNAL_ROOT}"; then
  echo "FAIL: external Vue artifact contains an internal service origin" >&2
  exit 1
fi

while IFS= read -r -d '' html_file; do
  if ! grep -Fq "${NOINDEX_MARKER}" "${html_file}"; then
    echo "FAIL: internal Vue document is missing noindex metadata: ${html_file}" >&2
    exit 1
  fi
done < <(find "${INTERNAL_ROOT}" -type f -name '*.html' -print0)

python3 - "${EXTERNAL_ROOT}/routes.json" "${INTERNAL_ROOT}/routes.json" \
  "${EXTERNAL_ORIGIN}" "${INTERNAL_ORIGIN}" <<'PY'
import json
import sys
from pathlib import Path

external = json.loads(Path(sys.argv[1]).read_text())
internal = json.loads(Path(sys.argv[2]).read_text())
if external.get("siteVariant") != "external":
    raise SystemExit("FAIL: external route manifest has the wrong site variant")
if internal.get("siteVariant") != "internal":
    raise SystemExit("FAIL: internal route manifest has the wrong site variant")
if external.get("origin") != sys.argv[3]:
    raise SystemExit("FAIL: external route manifest has the wrong canonical origin")
if internal.get("origin") != sys.argv[4]:
    raise SystemExit("FAIL: internal route manifest has the wrong canonical origin")
for label, manifest in (("external", external), ("internal", internal)):
    if not any(entry.get("path") == "/tools/exppattern" for entry in manifest.get("entries", [])):
        raise SystemExit(f"FAIL: ExpPattern is absent from the {label} static route manifest")
    if not any(entry.get("path") == "/tools/enrichment" for entry in manifest.get("entries", [])):
        raise SystemExit(f"FAIL: Enrichment is absent from the {label} static route manifest")
if any(entry.get("includeInSitemap") for entry in internal.get("entries", [])):
    raise SystemExit("FAIL: internal routes must not be indexable")
print("[site-variants] route manifests verified")
PY

python3 scripts/check_site_artifact_isolation.py \
  --external-root "${EXTERNAL_ROOT}" \
  --internal-root "${INTERNAL_ROOT}" \
  --sentinel "${INTERNAL_ORIGIN}" \
  --sentinel "${SOYMUTDB_INTERNAL_API_URL}" \
  --sentinel "${SOYMUTDB_INTERNAL_JBROWSE_URL}" \
  --sentinel "${NOINDEX_MARKER}"

echo "[site-variants] external/internal artifacts are isolated"

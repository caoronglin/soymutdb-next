#!/usr/bin/env bash
# =============================================================================
# SoyMutDB Web — Umi/Webpack bundle budgets (gzip sizes).
#
# The Umi build uses stable cache groups (react/ui/pro/query/charts) instead of
# Vite's former Vue-specific manualChunks names. Route-only groups may be absent
# after tree-shaking; every emitted group is still size-checked. Initial scripts
# referenced by index.html and every individual JS asset have independent caps.
#
# A cache-group budget measures ONE named chunk, which under-reports the chart
# engine: during the ECharts -> AntV transition the engine also landed in an
# unnamed vendor chunk (lodash, html2canvas, gl-matrix, d3-*) and partly in `ui`.
# The complete chart dependency cost is therefore gated separately, by
# scripts/chart_closure_budget.py, over the manifest that
# scripts/webpack/chart-closure-plugin.cjs writes during the build. It walks the
# real moduleGraph closure of packages/charts/src/index.ts and charges every JS
# chunk carrying it at its full actual gzip. That step is mandatory: there is no
# flag that turns it off, because a chart budget that can be skipped is not one.
#
# Usage: bash scripts/check-bundle-size.sh [dist/assets directory]
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-apps/web/dist/external/assets}"
ARTIFACT_ROOT="$(cd "$(dirname "$DIST_DIR")" && pwd)"
INDEX_HTML="${ARTIFACT_ROOT}/index.html"
UI_MAX_KB="${UI_MAX_KB:-320}"
PRO_MAX_KB="${PRO_MAX_KB:-180}"
REACT_MAX_KB="${REACT_MAX_KB:-100}"
# Router stack (react-router + @tanstack/router) is its own Umi cache group so a
# routing change and a React upgrade fail different budgets.
ROUTER_MAX_KB="${ROUTER_MAX_KB:-100}"
QUERY_MAX_KB="${QUERY_MAX_KB:-35}"
CHARTS_MAX_KB="${CHARTS_MAX_KB:-370}"
ENTRY_MAX_KB="${ENTRY_MAX_KB:-750}"
CHUNK_MAX_KB="${CHUNK_MAX_KB:-600}"

if ! command -v gzip >/dev/null 2>&1; then
  echo "Umi bundle check: gzip is required to measure compressed artifact sizes" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Umi bundle check: python3 is required to read index.html script references" >&2
  exit 1
fi
if [[ ! -d "$DIST_DIR" ]]; then
  echo "Umi bundle check: assets directory is missing: $DIST_DIR" >&2
  exit 1
fi
if [[ ! -s "$INDEX_HTML" ]]; then
  echo "Umi bundle check: index.html is missing: $INDEX_HTML" >&2
  exit 1
fi

shopt -s nullglob
JS_ASSETS=("$DIST_DIR"/*.js)
if [[ ${#JS_ASSETS[@]} -eq 0 ]]; then
  echo "Umi bundle check: no JavaScript assets under $DIST_DIR" >&2
  exit 1
fi

size_kb() {
  local bytes
  bytes=$(gzip -c -9 "$1" | wc -c)
  echo $(((bytes + 1023) / 1024))
}

fail=0
check_group() { # $1=label $2=glob $3=limit KB $4=required|optional
  local label="$1" glob="$2" max_kb="$3" required="$4"
  local files=("$DIST_DIR"/$glob)
  if [[ ${#files[@]} -eq 0 ]]; then
    if [[ "$required" == "required" ]]; then
      printf '  FAIL  %-8s no %s chunk emitted\n' "$label" "$glob"
      fail=1
    else
      printf '  SKIP  %-8s no %s chunk emitted (tree-shaken/not used)\n' "$label" "$glob"
    fi
    return
  fi

  local total=0 file kb
  for file in "${files[@]}"; do
    [[ -f "$file" ]] || continue
    kb=$(size_kb "$file")
    total=$((total + kb))
    printf '  INFO  %-8s %sKB  %s\n' "$label" "$kb" "$(basename "$file")"
  done
  if [[ "$total" -le "$max_kb" ]]; then
    printf '  PASS  %-8s total %sKB/%sKB\n' "$label" "$total" "$max_kb"
  else
    printf '  FAIL  %-8s total %sKB exceeds %sKB\n' "$label" "$total" "$max_kb"
    fail=1
  fi
}

# Resolve script tags from the built HTML rather than guessing Umi's entry name.
INITIAL_OUTPUT=$(python3 - "$INDEX_HTML" "$ARTIFACT_ROOT" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import sys

html_path = Path(sys.argv[1])
root = Path(sys.argv[2])

class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            src = dict(attrs).get("src", "")
            if src:
                self.sources.append(src)

parser = Scripts()
parser.feed(html_path.read_text(encoding="utf-8"))
found = []
for source in parser.sources:
    url = urlsplit(source)
    if url.scheme or url.netloc:
        continue
    basename = Path(url.path).name
    if not basename:
        continue
    direct = root / url.path.lstrip("/")
    candidates = [direct] if direct.is_file() else list(root.rglob(basename))
    candidates = [path.resolve() for path in candidates if path.is_file()]
    if candidates:
        found.append(candidates[0])
    else:
        print(f"index.html references a missing local script: {source}", file=sys.stderr)
        sys.exit(2)
for path in dict.fromkeys(found):
    print(path)
PY
)
mapfile -t INITIAL_FILES <<<"$INITIAL_OUTPUT"
if [[ ${#INITIAL_FILES[@]} -eq 0 || -z "${INITIAL_FILES[0]}" ]]; then
  echo "Umi bundle check: index.html contains no resolvable local script entry" >&2
  exit 1
fi

INITIAL_TOTAL=0
for file in "${INITIAL_FILES[@]}"; do
  kb=$(size_kb "$file")
  INITIAL_TOTAL=$((INITIAL_TOTAL + kb))
  printf '  INFO  entry    %sKB  %s\n' "$kb" "$(basename "$file")"
done
if [[ "$INITIAL_TOTAL" -le "$ENTRY_MAX_KB" ]]; then
  printf '  PASS  entry    total %sKB/%sKB\n' "$INITIAL_TOTAL" "$ENTRY_MAX_KB"
else
  printf '  FAIL  entry    total %sKB exceeds %sKB\n' "$INITIAL_TOTAL" "$ENTRY_MAX_KB"
  fail=1
fi

printf 'Umi bundle size budgets (gzip): dir=%s\n' "$DIST_DIR"
check_group "react"   'react.*.js'   "$REACT_MAX_KB" required
check_group "router"  'router.*.js'  "$ROUTER_MAX_KB" required
check_group "ui"      'ui.*.js'      "$UI_MAX_KB" required
check_group "query"   'query.*.js'   "$QUERY_MAX_KB" required
check_group "pro"     'pro.*.js'     "$PRO_MAX_KB" optional
check_group "charts"  'charts.*.js'  "$CHARTS_MAX_KB" required

for file in "${JS_ASSETS[@]}"; do
  kb=$(size_kb "$file")
  if [[ "$kb" -le "$CHUNK_MAX_KB" ]]; then
    printf '  PASS  chunk    %sKB/%sKB  %s\n' "$kb" "$CHUNK_MAX_KB" "$(basename "$file")"
  else
    printf '  FAIL  chunk    %sKB exceeds %sKB  %s\n' "$kb" "$CHUNK_MAX_KB" "$(basename "$file")"
    fail=1
  fi
done

# Complete chart dependency closure. Runs against the built tree, resolves its
# own manifest through the shared dist -> manifest table, and exits non-zero on
# schema / path-safety / seed / attribution / engine-census / budget failure.
# `lazy` vs `initial` is reported as INFO here; it is not a separate budget.
printf 'Umi chart closure budgets (gzip recomputed from the built tree): dist=%s\n' "$ARTIFACT_ROOT"
# Its exit code folds into the same `fail` flag as every other budget here, so a
# single run still prints the whole picture before failing. That is not an escape
# hatch: the script still exits non-zero, and the gate has no skip flag.
if ! python3 "${REPO_ROOT}/scripts/chart_closure_budget.py" --dist "$ARTIFACT_ROOT"; then
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "Umi bundle check: FAILED — split or optimize the oversized bundle(s), or read the failing gate above" >&2
  exit 1
fi

echo "Umi bundle check: OK"

#!/usr/bin/env bash
# =============================================================================
# SoyMutDB Web — G2 体积分块预算门禁 (docs/design/upgrade-plan.md §七)
#
# 构建后检测 apps/web/dist/assets 下各 chunk 的 gzip 大小（硬门禁）：
#   ui     (Antdv Next runtime) ≤ 120 KB  (UI_MAX_KB)
#   vue    (Vue + Router + Pinia) ≤ 45 KB  (VUE_MAX_KB)
#   query  (TanStack Vue Query)    ≤ 20 KB  (QUERY_MAX_KB)
#   charts (TanStack Charts)       ≤ 60 KB  (CHARTS_MAX_KB)
#   主入口 index  ≤ 160 KB  (ENTRY_MAX_KB)
#
# 超限 exit 1（CI frontend job 硬门禁；本地也可直接跑）。
# 未生成的 chunk（如试点期未 import pro-components）打印 SKIP，不计失败。
# 阈值可用环境变量覆盖（ANTD_MAX_KB / PRO_MAX_KB / ENTRY_MAX_KB）。
#
#
# 用法: bash scripts/check-bundle-size.sh [dist/assets 目录]
# =============================================================================
set -uo pipefail

DIST_DIR="${1:-apps/web/dist/assets}"
UI_MAX_KB="${UI_MAX_KB:-120}"
VUE_MAX_KB="${VUE_MAX_KB:-45}"
QUERY_MAX_KB="${QUERY_MAX_KB:-20}"
CHARTS_MAX_KB="${CHARTS_MAX_KB:-60}"
ENTRY_MAX_KB="${ENTRY_MAX_KB:-160}"

fail=0

size_kb() { # $1 = file
  local bytes
  bytes=$(gzip -c -9 "$1" | wc -c)
  # ceil(bytes / 1024)
  echo $(((bytes + 1023) / 1024))
}

check_chunk() { # $1 = 标签  $2 = glob  $3 = 阈值KB  $4 = chunk 名（输出用）
  local label="$1" glob="$2" max_kb="$3" name="$4"
  local matched=0
  for f in "$DIST_DIR"/$glob; do
    [ -e "$f" ] || continue
    matched=1
    local kb
    kb=$(size_kb "$f")
    local base
    base=$(basename "$f")
    if [ "$kb" -le "$max_kb" ]; then
      printf '  PASS  %-4s %-6sKB/%s  %s\n' "$label" "$kb" "${max_kb}KB" "$base"
    else
      printf '  FAIL  %-4s %-6sKB/%s  %s\n' "$label" "$kb" "${max_kb}KB" "$base"
      fail=1
    fi
  done
  if [ "$matched" -eq 0 ]; then
    printf '  SKIP  %-4s (no %s chunk emitted — 页面尚未引用该库)\n' "$label" "$name"
  fi
}


# Guard the vendor/entry split the Vite config enforces. Splitting the design
# system and the framework runtimes out of the entry is what keeps the entry
# budget meaningful; a regression that folds everything back into index-*.js is
# visible here without changing module assignment.
require_single_chunk() { # $1 = label  $2 = glob
  local label="$1" glob="$2" count=0
  local f
  for f in "$DIST_DIR"/$glob; do
    [ -e "$f" ] || continue
    count=$((count + 1))
  done
  if [ "$count" -eq 1 ]; then
    printf '  PASS  %-8s single runtime chunk\n' "$label"
  else
    printf '  FAIL  %-8s expected exactly one %s chunk, found %s\n' "$label" "$glob" "$count"
    fail=1
  fi
}

if ! command -v gzip >/dev/null 2>&1; then
  echo "G2 bundle check: gzip is required to measure compressed artifact sizes"
  exit 1
fi

if [ ! -d "$DIST_DIR" ]; then
  echo "G2 bundle check: dist 目录不存在（$DIST_DIR）— 请先构建 apps/web"
  exit 1
fi

echo "G2 bundle size budget (gzip):"
echo "  dir = $DIST_DIR"
echo "  thresholds: ui<=${UI_MAX_KB}KB  vue<=${VUE_MAX_KB}KB  query<=${QUERY_MAX_KB}KB  charts<=${CHARTS_MAX_KB}KB  entry<=${ENTRY_MAX_KB}KB"

require_single_chunk "ui-runtime"     "ui-*.js"
require_single_chunk "vue-runtime"    "vue-*.js"
require_single_chunk "query-runtime"  "query-*.js"
require_single_chunk "charts-runtime" "charts-*.js"

check_chunk "ui"     "ui-*.js"     "$UI_MAX_KB"    "design system"
check_chunk "vue"    "vue-*.js"    "$VUE_MAX_KB"   "framework runtime"
check_chunk "query"  "query-*.js"  "$QUERY_MAX_KB"  "vue-query"
check_chunk "charts" "charts-*.js" "$CHARTS_MAX_KB" "charts"
check_chunk "entry"  "index-*.js"  "$ENTRY_MAX_KB" "app entry"

if [ "$fail" -ne 0 ]; then
  echo "G2 bundle check: FAILED — 超阈值的 chunk 见上，需拆分或优化（阈值可用环境变量覆盖）"
  exit 1
fi
echo "G2 bundle check: OK"
exit 0

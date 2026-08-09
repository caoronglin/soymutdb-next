#!/usr/bin/env bash
# =============================================================================
# SoyMutDB Web — G2 体积分块预算门禁 (docs/design/upgrade-plan.md §七)
#
# 构建后检测 apps/web/dist/assets 下各 chunk 的 gzip 大小（硬门禁）：
#   antd          ≤ 280 KB  (ANTD_MAX_KB)
#   pro-components≤ 180 KB  (PRO_MAX_KB)
#   主入口 index  ≤ 200 KB  (ENTRY_MAX_KB)
#
# 超限 exit 1（CI frontend job 硬门禁；本地也可直接跑）。
# 未生成的 chunk（如试点期未 import pro-components）打印 SKIP，不计失败。
# 阈值可用环境变量覆盖（ANTD_MAX_KB / PRO_MAX_KB / ENTRY_MAX_KB）。
#
# 注：pro chunk 的产物命名按 manualChunks 返回值为 "pro"（pro-*.js），
# 与 antd/index 一致，故用 pro-*.js 匹配；web 侧未引用 pro-components
# 时仍打印 SKIP。
#
# 用法: bash scripts/check-bundle-size.sh [dist/assets 目录]
# =============================================================================
set -uo pipefail

DIST_DIR="${1:-apps/web/dist/assets}"
ANTD_MAX_KB="${ANTD_MAX_KB:-280}"
PRO_MAX_KB="${PRO_MAX_KB:-180}"
ENTRY_MAX_KB="${ENTRY_MAX_KB:-200}"

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
      printf '  PASS  %-4s %-6sKB/%sKB  %s\n' "$label" "$kb" "${max_kb}KB" "$base"
    else
      printf '  FAIL  %-4s %-6sKB/%sKB  %s\n' "$label" "$kb" "${max_kb}KB" "$base"
      fail=1
    fi
  done
  if [ "$matched" -eq 0 ]; then
    printf '  SKIP  %-4s (no %s chunk emitted — 页面尚未引用该库)\n' "$label" "$name"
  fi
}

if [ ! -d "$DIST_DIR" ]; then
  echo "G2 bundle check: dist 目录不存在（$DIST_DIR）— 请先构建 apps/web"
  exit 1
fi

echo "G2 bundle size budget (gzip):"
echo "  dir = $DIST_DIR"
echo "  thresholds: antd<=${ANTD_MAX_KB}KB  pro-components<=${PRO_MAX_KB}KB  entry<=${ENTRY_MAX_KB}KB"

check_chunk "antd" "antd-*.js"        "$ANTD_MAX_KB"  "antd"
check_chunk "pro"  "pro-*.js"             "$PRO_MAX_KB" "pro-components"
check_chunk "entry" "index-*.js"      "$ENTRY_MAX_KB" "index"

if [ "$fail" -ne 0 ]; then
  echo "G2 bundle check: FAILED — 超阈值的 chunk 见上，需拆分或优化（阈值可用环境变量覆盖）"
  exit 1
fi
echo "G2 bundle check: OK"
exit 0

#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Route B —— 受控真实数据种子脚本（CLI 契约入口）
# =====================================================================
# 目标：把权威真实数据（FASTA/GFF3/VCF/mutants）幂等写入门户读取表：
#   PostgreSQL: assemblies / chromosomes / genes / transcripts / exons /
#               gene_aliases / mutant_lines / data_sets / provenance /
#               release_data_sets
#   ClickHouse: variant_facts (canonical schema, release_key + assembly_key)
#
# 红线：绝不注入示例/演示数据。对源数据做真实性校验，命中 Demo 标记
#   （SMDB-* / Wm82.a4.v1 / legacy fixture 特征）或缺失/格式不符时 fail-closed。
#
# 真实解析/校验/plan/emit 由 scripts/seed_release_data.py 实现；本脚本为 CLI 契约入口，
# 预检+Demo 拒绝后把 --check/--plan/--emit-sql 委托给 python loader。
#   --apply (--write) 需 SOYMUTDB_SEED_ENABLED=1 且 loader 写库适配器已启用（见设计 §11），
# 否则 fail-closed（不写库、不注入示例数据）。设计见 docs/ops/route-b-seed-data-design.md。
#
# 用法：
#   bash scripts/seed-release-data.sh --source-dir /data/soy-wm82 --release-id 7 --check
#   bash scripts/seed-release-data.sh --source-dir /data/soy-wm82 --release-id 7 --dry-run
#   bash scripts/seed-release-data.sh --source-dir /data/soy-wm82 --create-release \
#        --version 0.1.0 --assembly Wm82v4.0 --apply        # 需 SOYMUTDB_SEED_ENABLED=1
# =====================================================================
set -uo pipefail

# ---- defaults ----------------------------------------------------------
SOURCE_DIR=""
RELEASE_ID=""
CREATE_RELEASE=0
VERSION="0.1.0"
NAME="SoyMutDB 0.1.0 — Glycine max (Williams 82) Wm82v4.0"
ASSEMBLY="Wm82v4.0"
SPECIES="Glycine max"
TOOL="soymutdb-seed"
TOOL_VERSION="0.1.0"
BATCH_SIZE_PG=10000
BATCH_SIZE_CH=50000
DRY_RUN=0
CHECK_ONLY=0
APPLY=0
MANIFEST_OUT=""
LOG_OUT=""

PG_DSN="${SOYMUTDB_PG_DSN:-${SOYMUTDB_DATABASE_URL:-}}"
CH_HOST="${SOYMUTDB_CLICKHOUSE_HOST:-127.0.0.1}"
CH_PORT="${SOYMUTDB_CLICKHOUSE_PORT:-8123}"
CH_USER="${SOYMUTDB_CLICKHOUSE_USER:-soymutdb}"
CH_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-}"
CH_DATABASE="${SOYMUTDB_CLICKHOUSE_DATABASE:-soymutdb}"
SEED_ENABLED="${SOYMUTDB_SEED_ENABLED:-0}"

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
fail() { printf '%s[FAIL]%s %s\n' "$RED" "$NC" "$1" >&2; exit "${2:-1}"; }
info() { printf '%s[INFO]%s %s\n' "$GREEN" "$NC" "$1"; }

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'
Options:
  --source-dir <DIR>        真实数据源目录（必需）
  --release-id <N>          已存在 draft release id（与 --create-release 二选一）
  --create-release          以 --version/--name/--assembly 新建 draft release
  --version <V>             release.version（默认 0.1.0）
  --name <S>                release.name
  --assembly <A>            默认 Wm82v4.0（禁止 Demo 值）
  --species <S>             默认 Glycine max
  --tool <T>                provenance 工具名
  --tool-version <V>        provenance 工具版本
  --batch-size <N>          PG/CH 分批大小
  --dry-run                 只预检 + 打印 plan，不动库
  --check                   只做输入/格式/checksum/真实性校验，不写库
  --plan                    解析并写 seed-manifest.json，不写库
  --apply                   实际写入（需 SOYMUTDB_SEED_ENABLED=1）
  --manifest-out <PATH>     seed-manifest.json 输出路径
  --log-out <PATH>          运行日志输出路径
  --emit-sql <DIR>      解析真实文件并生成可回放 INSERT SQL 到目录

Env: SOYMUTDB_EVIDENCE_DIR 覆盖默认证据目录 artifacts/acceptance/data-query（gitignored）；QA 建议设为 docs/ops/evidence/（受跟踪）。
  -h|--help                 帮助
Exit codes: 0 ok | 2 input/真实性 fail | 3 release 非 draft/不存在 | 4 write fail | 5 bad arg
EOF
}

# ---- arg parse ---------------------------------------------------------
SOURCE_DIR=""; RELEASE_ID=""; CREATE_RELEASE=0; VERSION="0.1.0"; NAME=""; ASSEMBLY="Wm82v4.0"
SPECIES="Glycine max"; TOOL="soymutdb-seed"; TOOL_VERSION="0.1.0"; BATCH_SIZE_PG=10000; BATCH_SIZE_CH=50000
DRY_RUN=0; CHECK_ONLY=0; APPLY=0; PLAN_ONLY=0; MANIFEST_OUT=""; LOG_OUT=""; EMIT_SQL_DIR=""; EVIDENCE_DIR="${SOYMUTDB_EVIDENCE_DIR:-artifacts/acceptance/data-query}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source-dir)     SOURCE_DIR="$2"; shift 2 ;;
    --release-id)     RELEASE_ID="$2"; shift 2 ;;
    --create-release) CREATE_RELEASE=1; shift ;;
    --version)        VERSION="$2"; shift 2 ;;
    --name)           NAME="$2"; shift 2 ;;
    --assembly)       ASSEMBLY="$2"; shift 2 ;;
    --species)        SPECIES="$2"; shift 2 ;;
    --tool)           TOOL="$2"; shift 2 ;;
    --tool-version)   TOOL_VERSION="$2"; shift 2 ;;
    --batch-size)     BATCH_SIZE_PG="$2"; BATCH_SIZE_CH="$2"; shift 2 ;;
    --dry-run)        DRY_RUN=1; shift ;;
    --check)          CHECK_ONLY=1; shift ;;
    --plan)           PLAN_ONLY=1; shift ;;
    --apply)          APPLY=1; shift ;;
    --manifest-out)   MANIFEST_OUT="$2"; shift 2 ;;
    --log-out)        LOG_OUT="$2"; shift 2 ;;
    --emit-sql)       EMIT_SQL_DIR="$2"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *)                printf '未知参数: %s\n' "$1" >&2; usage >&2; exit 5 ;;
  esac
done
[[ -z "${NAME}" ]] && NAME="SoyMutDB ${VERSION} — ${SPECIES} (Williams 82) ${ASSEMBLY}"

# ---- reality / demo guards ----------------------------------------------
DEMO_PATTERNS=("SMDB-" "Wm82.a4.v1" "referenceGenome")

reject_demo_fixtures() {
  local f="$1"
  for pat in "${DEMO_PATTERNS[@]}"; do
    if grep -a -q "$pat" "$f" 2>/dev/null; then
      fail "输入 ${f} 命中 Demo 标记 '$pat' —— 拒绝导入（禁止示例数据冒充真实数据）" 2
    fi
  done
  return 0
}

# NOTE: never call this inside $(...) — the nested fail/exit must terminate the
# main script, so we read the result from a global instead of stdout.
__req_path=""
require_file() {
  local rel="$1"
  local path="$SOURCE_DIR/$rel"
  if [[ ! -f "$path" ]]; then fail "缺少必需输入文件: $rel (在 $SOURCE_DIR)" 2; fi
  [[ -s "$path" ]] || fail "输入文件为空: $rel" 2
  reject_demo_fixtures "$path" || exit 2
  __req_path="$path"
}

# ---- required inputs ----------------------------------------------------
FASTA=""; FASTA_FAI=""; ASSEMBLY_META=""; GFF3=""; VCF=""; MUTANTS=""
preflight() {
  [[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR" ]] || fail "--source-dir 缺失或不是目录" 5
  local has_create=0 has_rid=0
  [[ "$CREATE_RELEASE" == "1" ]] && has_create=1
  [[ -n "$RELEASE_ID" ]] && has_rid=1
  if [[ "$has_create" == "1" && "$has_rid" == "1" ]]; then fail "--create-release 与 --release-id 二选一" 5; fi
  if [[ "$has_create" == "0" && "$has_rid" == "0" ]]; then fail "需要 --release-id 或 --create-release" 5; fi

  # assembly name normalization: reject Wm82.a4.v1 (demo)
  case "$ASSEMBLY" in
    *a4*|*Wm82.a4.v1*) fail "assembly '$ASSEMBLY' 是 Demo 符号，需归一为 Wm82v4.0" 2 ;;
  esac

  require_file genome.fa;            FASTA="$__req_path"
  [[ -f "$SOURCE_DIR/genome.fa.fai" ]] && FASTA_FAI="$SOURCE_DIR/genome.fa.fai"
  require_file assembly.meta;        ASSEMBLY_META="$__req_path"
  require_file annotations.gff3;     GFF3="$__req_path"
  require_file variants.vcf;         VCF="$__req_path"
  [[ -f "$SOURCE_DIR/mutants.tsv" ]] && MUTANTS="$SOURCE_DIR/mutants.tsv"

  info "源目录检查通过（真实源文件存在 + 无 Demo 标记）"
}

# ---- loader gates -------------------------------------------------------
# 真实解析+写入已由 scripts/seed_release_data.py 落地（通用实现）。本 shell 仍为
# CLI 契约入口：把实际解析/plan/manifest/写库委托给 Python loader，并保持
# fail-closed（--apply 需 SOYMUTDB_SEED_ENABLED=1；Python --write 当前仍 fail-closed，
# 待数据源/版本冻结并授权后再放开）。
_apply_guard() {
  if [[ "$APPLY" != "1" ]]; then return 0; fi
  if [[ "$SEED_ENABLED" != "1" ]]; then
    fail "--apply 需要 SOYMUTDB_SEED_ENABLED=1（且需先备份/冻结数据源）。本次不动库。" 4
  fi
  # Python --write 适配器（PG asyncpg / CH clickhouse_connect）在数据源冻结前 fail-closed。
  fail "--apply 已禁用：真实 loader 的 --write 适配器待数据源冻结后启用（见 route-b-seed-data-design.md §11）。本次不动库。" 4
}

# 将 shell 已解析的 CLI 参数转发给 Python loader。
run_python_loader() {
  local py_script="scripts/seed_release_data.py"
  local mode="$1"; shift
  local args=(--source-dir "$SOURCE_DIR" --assembly "$ASSEMBLY" --species "$SPECIES"
              --tool "$TOOL" --tool-version "$TOOL_VERSION" --batch-size "$BATCH_SIZE_PG")
  if [[ "$CREATE_RELEASE" == "1" ]]; then args+=(--create-release --version "$VERSION" --name "$NAME");
  else args+=(--release-id "$RELEASE_ID"); fi
  case "$mode" in
    check) args+=(--check --manifest-out "${MANIFEST_OUT:-${EVIDENCE_DIR}/seed-manifest.json}") ;;
    plan)  args+=(--plan --manifest-out "${MANIFEST_OUT:-${EVIDENCE_DIR}/seed-manifest.json}") ;;
    emit)  args+=(--emit-sql "${EMIT_SQL_DIR:-${EVIDENCE_DIR}}") ;;
    write) args+=(--write) ;;
    *)     return 1 ;;
  esac
  [[ -x "$py_script" ]] || py_script="python3 $py_script"
  "$py_script" "${args[@]}"
}


# =====================================================================
echo "== SoyMutDB Route B 受控真实数据种子 =="
echo "  source-dir: ${SOURCE_DIR:-<none>} ; assembly: $ASSEMBLY ; mode: $([ "$CHECK_ONLY" == 1 ] && echo check || echo plan)"
echo "  PG: $([ -n "${PG_DSN}" ] && echo set || echo 'SOYMUTDB_PG_DSN 未设置') ; CH: ${CH_USER}@${CH_HOST}:${CH_PORT}/${CH_DATABASE}"
echo ""

preflight

# --check / --plan / --emit-sql：委托真实 Python loader（解析真实文件，fail-closed）。
# --apply：由 _apply_guard 把关；数据源冻结前 fail-closed（不注入任何数据）。
if [[ "$CHECK_ONLY" == "1" ]]; then
  info "运行真实 loader 校验（--check）..."
  run_python_loader check || exit $?
  exit 0
fi

if [[ -n "$EMIT_SQL_DIR" ]]; then
  info "运行真实 loader 生成可回放 SQL（--emit-sql）..."
  run_python_loader emit || exit $?
  exit 0
fi

echo "--- 写入计划（真实解析）---"
run_python_loader plan || exit $?

if [[ "$APPLY" == "1" ]]; then
  _apply_guard || exit $?
  run_python_loader write || exit $?
  info "写入完成（如需，随后可手工调用 validate_release/mark_release_ready）。"
else
  info "plan-only（无写库）。要实际写入: --apply + SOYMUTDB_SEED_ENABLED=1（且 loader --write 已按设计 §11 启用）。"
fi
echo ""
info "完成。请用 scripts/validate-release-data.sh 做 G12 查询验收。"
exit 0

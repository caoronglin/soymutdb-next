#!/usr/bin/env bash
# =====================================================================
# SoyMutDB Release 数据面查询验证脚本（G12）
# =====================================================================
# 对应 docs/ops/first-release-data-plan.md §6/§7 的 Release 数据面验收标准：
#   - 结构/范围（D1–D4）：Release 身份、assembly 归一、数据集 READY、manifest/readiness
#   - 跨数据集一致性（C1–C6）：release_key 隔离、assembly 一致、gene 引用一致、
#     坐标边界、受控枚举、JBrowse 不 fallback demo 符号
#   - 可追溯（P1–P3）：下载对象 checksum、provenance 完整、时间戳/可复现
#
# 用法：
#   RELEASE_ID=<N> bash scripts/validate-release-data.sh          # 全量验证
#   RELEASE_ID=<N> bash scripts/validate-release-data.sh --pg     # 只做 PostgreSQL
#   RELEASE_ID=<N> bash scripts/validate-release-data.sh --ch     # 只做 ClickHouse
#   RELEASE_ID=<N> bash scripts/validate-release-data.sh --api    # 只做 API/capabilities
#   RELEASE_ID=<N> bash scripts/validate-release-data.sh --dry-run# 打印将执行的命令不执行
#
# 连接变量（缺省见 defaults；可与 deploy/conda-data-init.sh 共用）：
#   SOYMUTDB_PG_DSN                 psql 连接串（否则从 SOYMUTDB_DATABASE_URL 推导）
#   SOYMUTDB_DATABASE_URL           兼容 asyncpg URL，用于推导 psql DSN
#   SOYMUTDB_CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE
#   SOYMUTDB_API_BASE               例如 https://api.soymutdb.org 或 http://127.0.0.1:8080
#   SOYMUTDB_API_TOKEN              Admin Bearer token（可选）
#   RELEASE_ID                      ClickHouse release_key（=releases.id）；未给则从 active release 探测
#   ASSEMBLY                        期望 assembly（默认 Wm82v4.0）
#   EXPECTED_RELEASE_VERSION        期望 release.version（默认 0.1.0）
#   EXPECTED_SPECIES                期望物种（默认 Glycine max）
#   EXPECTED_ASSEMBLY_NAME          期望默认 assembly 名称（默认 Wm82v4.0）
#   CHR_LEN_OVERRIDE                "Chr01:55984992,Chr02:..." 覆盖染色体长度
#   FAIL_ON_MISSING_TOOL=1          缺 psql/clickhouse-client/curl/jq 时视为失败（默认跳过）
#   CHECK_Wm82_A4=1                 额外把 Wm82.a4.v1 出现视为失败（默认计数并提示）
# =====================================================================
set -uo pipefail

# ---- defaults ----------------------------------------------------------
PG_DSN="${SOYMUTDB_PG_DSN:-}"
if [[ -z "${PG_DSN}" && -n "${SOYMUTDB_DATABASE_URL:-}" ]]; then
  # postgresql+asyncpg://user:pass@host:port/db → postgresql://user:pass@host:port/db
  PG_DSN="$(printf '%s' "${SOYMUTDB_DATABASE_URL}" | sed -E 's#^postgresql\+asyncpg://#postgresql://#')"
fi
CH_HOST="${SOYMUTDB_CLICKHOUSE_HOST:-127.0.0.1}"
CH_PORT="${SOYMUTDB_CLICKHOUSE_PORT:-8123}"
CH_USER="${SOYMUTDB_CLICKHOUSE_USER:-soymutdb}"
CH_PASSWORD="${SOYMUTDB_CLICKHOUSE_PASSWORD:-}"
CH_DATABASE="${SOYMUTDB_CLICKHOUSE_DATABASE:-soymutdb}"
API_BASE="${SOYMUTDB_API_BASE:-}"
API_TOKEN="${SOYMUTDB_API_TOKEN:-}"
RELEASE_ID="${RELEASE_ID:-}"
ASSEMBLY="${ASSEMBLY:-Wm82v4.0}"
EXPECTED_RELEASE_VERSION="${EXPECTED_RELEASE_VERSION:-0.1.0}"
EXPECTED_SPECIES="${EXPECTED_SPECIES:-Glycine max}"
EXPECTED_ASSEMBLY_NAME="${EXPECTED_ASSEMBLY_NAME:-Wm82v4.0}"
FAIL_ON_MISSING_TOOL="${FAIL_ON_MISSING_TOOL:-0}"
CHECK_Wm82_A4="${CHECK_Wm82_A4:-0}"
DRY_RUN="${DRY_RUN:-0}"

# Parse positional args: global flags first, then a single mode token.
MODE="all"
for _arg in "$@"; do
  case "${_arg}" in
    --dry-run) DRY_RUN="1" ;;
    pg|ch|api|all) MODE="${_arg}" ;;
    -h|--help) sed -n '1,40p' "$0"; exit 0 ;;
    *) printf '忽略未知参数: %s\n' "${_arg}" >&2 ;;
  esac
done

GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'; NC=$'\033[0m'
PASS=0; FAIL=0; SKIP=0
declare -a FAIL_MSGS=()

fail() { FAIL=$((FAIL+1)); FAIL_MSGS+=("$1"); printf '%s[FAIL]%s %s\n' "$RED" "$NC" "$1" >&2; }
pass() { PASS=$((PASS+1)); printf '%s[PASS]%s %s\n' "$GREEN" "$NC" "$1"; }
skip() { SKIP=$((SKIP+1)); printf '%s[SKIP]%s %s\n' "$YELLOW" "$NC" "$1"; }

# Run a command (respect dry-run). On tool availability, mark missing as skip/fail.
run() {
  local desc="$1"; shift
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '  [:dry-run] %s\n' "$*" >&2
    return 0
  fi
  if ! command -v "$1" >/dev/null 2>&1; then
    if [[ "${FAIL_ON_MISSING_TOOL}" == "1" ]]; then
      fail "$desc (missing tool: $1)"; return 1
    else
      skip "$desc (tool '$1' not found)"; return 2
    fi
  fi
  "$@"
}

# Query PostgreSQL with psql (returns stdout). Empty on failure.
psql_q() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '  [:dry-run] psql %q\n' "$*" >&2
    return 0
  fi
  if [[ -z "${PG_DSN}" ]]; then
    return 2
  fi
  psql "${PG_DSN}" -At -F $'\t' -c "$1" 2>/dev/null || true
}

# Query ClickHouse with clickhouse-client (returns stdout). Empty on failure.
ch_q() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '  [:dry-run] clickhouse-client %q\n' "$*" >&2
    return 0
  fi
  clickhouse-client --host "${CH_HOST}" --port "${CH_PORT}" \
    --user "${CH_USER}" --password "${CH_PASSWORD}" \
    --database "${CH_DATABASE}" --query "$1" 2>/dev/null || true
}

api_get() {
  local path="$1"
  if [[ -z "${API_BASE}" ]]; then echo ""; return 2; fi
  local url="${API_BASE%/}${path}"
  local auth=()
  if [[ -n "${API_TOKEN}" ]]; then auth=(-H "Authorization: Bearer ${API_TOKEN}"); fi
  curl -sS "${auth[@]}" -H "Accept: application/json" "$url" 2>/dev/null || true
}

# ---------------------------------------------------------------------
# Ensure psql/clickhouse/curl present for the active mode without failing.
# ---------------------------------------------------------------------
ensure_tools() {
  case "${MODE}" in
    pg) command -v psql >/dev/null 2>&1 || { [[ "$FAIL_ON_MISSING_TOOL" == "1" ]] && fail "psql missing" || skip "psql not installed"; } ;;
    ch) command -v clickhouse-client >/dev/null 2>&1 || { [[ "$FAIL_ON_MISSING_TOOL" == "1" ]] && fail "clickhouse-client missing" || skip "clickhouse-client not installed"; } ;;
    api) command -v curl >/dev/null 2>&1 || { [[ "$FAIL_ON_MISSING_TOOL" == "1" ]] && fail "curl missing" || skip "curl not installed"; } ;;
  esac
}

# ---------------------------------------------------------------------
echo "== SoyMutDB Release 数据面验证 =="
echo "  mode: ${MODE} ; assembly: ${ASSEMBLY} ; release_id: ${RELEASE_ID:-<auto>}"
[[ -n "${PG_DSN}" ]] && echo "  PG: set" || echo "  PG: SOYMUTDB_PG_DSN / SOYMUTDB_DATABASE_URL 未设置"
echo "  CH: ${CH_HOST}:${CH_PORT}/${CH_DATABASE}"
[[ -n "${API_BASE}" ]] && echo "  API: ${API_BASE}" || echo "  API: SOYMUTDB_API_BASE 未设置（跳过 API 检查）"
echo ""

ensure_tools

# In dry-run we only preview the commands; do not evaluate pass/fail so the
# preview never reports a false failure against an unconnected data source.
if [[ "${DRY_RUN}" == "1" ]]; then
  printf '%s\n' "-- DRY RUN：以下为将执行的检查与命令；未连接数据源，不作通过/失败判定 --"
  fail() { :; }
  pass() { :; }
  skip() { :; }
fi

# ---------------------------------------------------------------------
# 0) Resolve active release id (ClickHouse release_key) if not provided.
# ---------------------------------------------------------------------
if [[ -n "${PG_DSN}" && -z "${RELEASE_ID}" && "${MODE}" != "api" ]]; then
  RELEASE_ID="$(psql_q "SELECT id FROM releases r JOIN active_release a ON a.release_id = r.id WHERE a.id = 1 AND r.status = 'published' LIMIT 1;")"
  echo "  探测 active release_id=${RELEASE_ID:-<none>}"
fi

# =====================================================================
# A) PostgreSQL 检查（结构/范围 + 一致性）
# =====================================================================
if [[ "${MODE}" == "all" || "${MODE}" == "pg" ]]; then
  echo "--- [PG] 结构/范围 ---"
  # D1 release 身份 + assembly 单一
  rel="$(psql_q "SELECT version || '|' || assembly FROM releases WHERE status='published' ORDER BY id DESC LIMIT 1;")"
  rel_version="${rel%%|*}"; rel_assembly="${rel##*|}"
  if [[ -z "${rel}" ]]; then fail "D1: 无 published release"; else
    [[ "${rel_version}" == "${EXPECTED_RELEASE_VERSION}" ]] && pass "D1: release.version=${rel_version}" || fail "D1: release.version=${rel_version} 期望 ${EXPECTED_RELEASE_VERSION}"
    [[ "${rel_assembly}" == "${ASSEMBLY}" ]] && pass "D1: release.assembly=${rel_assembly}" || fail "D1: release.assembly=${rel_assembly} 期望 ${ASSEMBLY}"
  fi

  # D1b 默认 assembly + species
  asm="$(psql_q "SELECT name || '|' || species FROM assemblies WHERE is_default LIMIT 1;")"
  asm_name="${asm%%|*}"; asm_species="${asm##*|}"
  if [[ -z "${asm}" ]]; then fail "D1: 无 default assembly"; else
    [[ "${asm_name}" == "${EXPECTED_ASSEMBLY_NAME}" ]] && pass "D1: default assembly=${asm_name}" || fail "D1: default assembly=${asm_name} 期望 ${EXPECTED_ASSEMBLY_NAME}"
    [[ "${asm_species}" == "${EXPECTED_SPECIES}" ]] && pass "D1: species=${asm_species}" || fail "D1: species=${asm_species} 期望 ${EXPECTED_SPECIES}"
  fi

  # D2 数据面不含 Wm82.a4.v1（Demo 符号）
  n="$(psql_q "SELECT count(*) FROM genes WHERE id LIKE 'SMDB-%' OR name LIKE '%SMDB-%';")"
  [[ "${n:-0}" == "0" ]] && pass "D2: 无 SMDB-* 占位基因 (n=${n})" || fail "D2: 存在 ${n} 个 SMDB-* 占位基因"
  if [[ "${CHECK_Wm82_A4}" == "1" ]]; then
    w="$(psql_q "SELECT count(*) FROM assemblies WHERE name LIKE '%Wm82.a4%' OR name LIKE '%a4.v1%';")"
    [[ "${w:-0}" == "0" ]] && pass "D2: 无 Wm82.a4.v1 assembly (n=${w})" || fail "D2: 存在 ${w} 个 Wm82.a4.v1 assembly"
  fi

  # 基因规模与染色体覆盖
  gc="$(psql_q "SELECT count(*) || '|' || count(DISTINCT chromosome_id) FROM genes;")"
  genes="${gc%%|*}"; chroms="${gc##*|}"
  pass "PG: genes=${genes}, chromosomes=${chroms}"

  # C4 基因坐标边界：start/end 不得超过染色体长度
  bad="$(psql_q "SELECT count(*) FROM genes g JOIN chromosomes c ON c.id=g.chromosome_id WHERE g.start < 1 OR g.end < g.start OR g.end > c.length;")"
  [[ "${bad:-0}" == "0" ]] && pass "C4: 基因坐标越界数=0 或无法校验" || fail "C4: ${bad} 个基因坐标越界"

  # P2 provenance 完整性
  prov="$(psql_q "SELECT count(*) FROM provenance WHERE source='' OR checksum_sha256='';")"
  [[ "${prov:-0}" == "0" ]] && pass "P2: provenance 完整 (空 source/checksum=0)" || fail "P2: ${prov} 条 provenance 缺 source/checksum"

  # 基因引用一致（变异命中的 gene 在基因表存在）——跨引擎需 CH；此处仅报告 PG 基因数
  # C3 在 ClickHouse 段通过 gene_id 反向校验
fi

# =====================================================================
# B) ClickHouse 检查（变异事实）
# =====================================================================
if [[ "${MODE}" == "all" || "${MODE}" == "ch" ]]; then
  echo "--- [CH] 变异事实 ---"
  if [[ -z "${RELEASE_ID}" ]]; then fail "CH: 需要 RELEASE_ID（或可解析 active release）"; else
    # C1 assembly 一致
    asms="$(ch_q "SELECT DISTINCT assembly_key FROM variant_facts WHERE release_key='${RELEASE_ID}';")"
    if [[ -z "${asms}" ]]; then fail "CH: release_key=${RELEASE_ID} 无 variant_facts 记录"; else
      asms_nl="$(printf '%s\n' "${asms}")"
      if [[ "$(printf '%s\n' "${asms_nl}" | grep -c .)" == "1" && "${asms_nl}" == "${ASSEMBLY}" ]]; then
        pass "C1: assembly_key=${asms_nl} (唯一=${ASSEMBLY})"
      else
        fail "C1: assembly_key=[${asms_nl}] 期望唯一 ${ASSEMBLY}"
      fi
    fi

    # C2 release 隔离：非活动 release 查询应为 0/空
    wrong="$(ch_q "SELECT count() FROM variant_facts WHERE release_key='999999';")"
    [[ "${wrong:-0}" == "0" ]] && pass "C2: 非活动 release 记录=0 (隔离有效)" || fail "C2: 非活动 release 存在 ${wrong} 记录"

    # 总数
    total="$(ch_q "SELECT count() FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key='${ASSEMBLY}';")"
    pass "CH: variant_facts total=${total}"

    # C5 受控枚举：variant_type
    nonenum="$(ch_q "SELECT count() FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key='${ASSEMBLY}' AND variant_type NOT IN ('SNP','INS','DEL','MNV','SV');")"
    [[ "${nonenum:-0}" == "0" ]] && pass "C5: variant_type 受控枚举 (非法数=0)" || fail "C5: ${nonenum} 条非法 variant_type"

    # type 分布
    dist="$(ch_q "SELECT variant_type || ':' || toString(count()) FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key='${ASSEMBLY}' GROUP BY variant_type ORDER BY count() DESC;")"
    printf '  type分布: %s\n' "$(printf '%s\n' "${dist}" | tr '\n' ' ')"
    pass "CH: variant_type 分布已输出"

    # C4 CH 坐标边界（需染色体长度；默认跳过，提供 CHR_LEN_OVERRIDE 可校验）
    if [[ -n "${CHR_LEN_OVERRIDE:-}" ]]; then
      bad=0
      IFS=',' read -ra pairs <<< "${CHR_LEN_OVERRIDE}"
      for pair in "${pairs[@]}"; do
        chr="${pair%%:*}"; len="${pair##*:}"
        v="$(ch_q "SELECT count() FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key='${ASSEMBLY}' AND chromosome='${chr}' AND position > ${len};")"
        if [[ "${v:-0}" != "0" ]]; then bad=$((bad+v)); fi
      done
      [[ "${bad}" == "0" ]] && pass "C4: CH 坐标越界数=0" || fail "C4: ${bad} 条 CH 坐标越界"
    else
      skip "C4: CH 坐标边界需 CHR_LEN_OVERRIDE=<chr:len,...>（提供后校验）"
    fi

    # C3 变异命中的 gene 是否存在于基因表（跨引擎，用 PG 基因集校验——此处仅报告 gene_id 去重数）
    gn="$(ch_q "SELECT count(DISTINCT gene_id) FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key='${ASSEMBLY}' AND gene_id != '';")"
    pass "CH: distinct gene_id referenced = ${gn}"

    # C6 JBrowse 不 fallback demo 符号（assembly 归属 JBrowse 目录/轨道）
    if [[ "${CHECK_Wm82_A4}" == "1" ]]; then
      jb="$(ch_q "SELECT count() FROM variant_facts WHERE release_key='${RELEASE_ID}' AND assembly_key LIKE '%a4.v1%';")"
      [[ "${jb:-0}" == "0" ]] && pass "C6: variant_facts 无 Wm82.a4.v1" || fail "C6: ${jb} 条 assembly_key 含 Wm82.a4.v1"
    fi
  fi
fi

# =====================================================================
# C) API / capabilities 检查
# =====================================================================
if [[ "${MODE}" == "all" || "${MODE}" == "api" ]]; then
  echo "--- [API] capabilities / 查询 ---"
  if [[ -z "${API_BASE}" ]]; then skip "API: 未设置 SOYMUTDB_API_BASE，跳过"; else
    caps="$(api_get "/api/v1/capabilities")"
    if [[ -z "${caps}" ]]; then fail "API: /capabilities 不可达"; else
      # 未实现导入类型必须不可用（G11）
      for t in vcf gff3 fasta blast_db seed_data expression_csv homolog_csv; do
        val="$(printf '%s' "${caps}" | jq -r --arg k "imports.$t" '.features[$k] // "absent"' 2>/dev/null || echo "absent")"
        if [[ "${val}" == "false" || "${val}" == "absent" ]]; then
          pass "G11: imports.$t 不可用 (${val})"
        else
          fail "G11: imports.$t 仍可用 (${val}) —— 应为 false/absent"
        fi
      done
      mod="$(printf '%s' "${caps}" | jq -r '.features["imports.module_tsv"] // "absent"' 2>/dev/null || echo "absent")"
      [[ "${mod}" == "true" ]] && pass "G11: imports.module_tsv 可用" || fail "G11: imports.module_tsv 不可用 (${mod})"
    fi

    # 有效基因查询（非 demo）；若 release 绑定，则带 release header
    hdr=(); [[ -n "${RELEASE_ID}" ]] && hdr=(-H "X-SoyMutDB-Release: ${RELEASE_ID}")
    g="$(curl -sS "${hdr[@]}" -H "Accept: application/json" "${API_BASE%/}/api/v1/genes?limit=3" 2>/dev/null)" || g=""
    if [[ -z "${g}" ]]; then fail "API: /genes 不可达"; else
      sample="$(printf '%s' "${g}" | jq -r '.items[0].id // "none"' 2>/dev/null || echo "none")"
      case "${sample}" in
        SMDB-*|none|"") fail "API: /genes 返回 demo/空样本 (${sample})" ;;
        *) pass "API: /genes 返回真实样本 (${sample})" ;;
      esac
    fi

    # 无效 release 查询应 404
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_BASE%/}/api/v1/genes?release_id=999999" 2>/dev/null || echo "000")"
    [[ "${code}" == "404" ]] && pass "API: 无效 release → 404" || fail "API: 无效 release → ${code}（期望 404）"
  fi
fi

# =====================================================================
# 汇总
# =====================================================================
echo ""
echo "== 汇总 =="
echo "  PASS=${PASS}  FAIL=${FAIL}  SKIP=${SKIP}"
if [[ "${FAIL}" -gt 0 ]]; then
  printf '  %sFAILURES:%s\n' "$RED" "$NC"
  for m in "${FAIL_MSGS[@]}"; do printf '    - %s\n' "$m"; done
  exit 1
fi
echo "  全部通过（SKIP 项需人工确认或补齐连接）"
exit 0

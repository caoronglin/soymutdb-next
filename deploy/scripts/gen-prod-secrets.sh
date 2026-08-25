#!/usr/bin/env bash
# =====================================================================
# SoyMutDB — 生产密钥生成与环境文件引导 (gen-prod-secrets)
# =====================================================================
# 作用：从 deploy/.env.example（或已有 .env）引导出可上线 .env：
#   1. 为仍是占位/开发默认值的必填凭据自动生成强随机值；
#   2. 校验 CORS / 必填项与「不得使用默认/示例值」规则；
#   3. 以 0600 权限写回目标文件（默认 /opt/soymutdb/.env）。
# 已属于操作者真实值的项不会被覆盖（幂等、非破坏）；写入前自动备份
# 原文件为 .env.bak-<timestamp>。
#
# 用法：
#   bash deploy/scripts/gen-prod-secrets.sh                       # 处理 /opt/soymutdb/.env
#   bash deploy/scripts/gen-prod-secrets.sh --env-file ./prod.env  # 指定目标
#   bash deploy/scripts/gen-prod-secrets.sh --template             # 从模板新建（无既有 .env）
#   bash deploy/scripts/gen-prod-secrets.sh --check                # 只校验，不写文件
#   bash deploy/scripts/gen-prod-secrets.sh --compose-preflight    # 校验后追加 docker compose config -q
#   bash deploy/scripts/gen-prod-secrets.sh --help
#
# 始终写入前备份 + chmod 600；仅生成，不提交。校验规则与
# apps/api/app/core/config.py 及 deploy/scripts/upgrade.sh 对齐。
# =====================================================================
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${PROJECT_ROOT}/deploy/.env.example"

ENV_FILE="${SOYMUTDB_ENV_FILE:-/opt/soymutdb/.env}"
MODE="bootstrap"          # bootstrap | check
COMPOSE_PREFLIGHT=0
DO_TEMPLATE=0

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${GREEN}  $*${NC}"; }
warn(){ echo -e "${YELLOW}  [WARN] $*${NC}"; }
err() { echo -e "${RED}[ERROR] $*${NC}" >&2; }
die() { err "$*"; exit 1; }

usage(){ sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) ENV_FILE="${2:?--env-file requires a path}"; shift 2 ;;
        --template) DO_TEMPLATE=1; shift ;;
        --check) MODE="check"; shift ;;
        --compose-preflight) COMPOSE_PREFLIGHT=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "unknown argument: $1 (see --help)" ;;
    esac
done

# ---------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------
hex(){ openssl rand -hex "${1:-32}"; }
# URL-safe base64，去掉可能干扰 shell/env 的特殊字符；用于 JWT / token
b64url(){ openssl rand -base64 80 | tr -dc 'A-Za-z0-9' | head -c "${1:-64}"; }

# ---------------------------------------------------------------------
# 占位/默认值识别（与 upgrade.sh / config.py 对齐）
# ---------------------------------------------------------------------
is_placeholder(){
    case "$1" in
        change-me-*|please-generate-*|minioadmin|admin123|admin|\
        soymutdb_dev_password|replace-with-*)
            return 0 ;;
        *) return 1 ;;
    esac
}

# 读 .env 中 KEY 的值（返回空若未设置）；KEY=value，兼容 export 与无引号
get_env(){
    local key="$1"
    awk -v k="${key}=" '$0 ~ "^"k { sub("^"k,""); print }' "${ENV_FILE}" \
        | tail -n1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}
set_env(){
    local key="$1" value="$2"
    grep -q "^${key}=" "${ENV_FILE}" \
        && sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}" \
        || { [[ -s "${ENV_FILE}" ]] && printf '\n' >> "${ENV_FILE}"; printf '%s=%s\n' "${key}" "${value}" >> "${ENV_FILE}"; }
}

# 校验辅助（在 CORS / 管理员 / 校验段之前定义，供全脚本复用）
validation_failed=0
check_fail(){ err "$1"; validation_failed=1; }

# ---------------------------------------------------------------------
# 引导小写字母 KEY（config 可观测变量同时写入大写 compose 变量；此处只处理 compose 层）
# ---------------------------------------------------------------------
# 需要强随机值的必填凭据（key 及其最小长度）
REQUIRED_SECRETS=(
    "POSTGRES_PASSWORD:32"
    "CLICKHOUSE_PASSWORD:32"
    "REDIS_PASSWORD:32"
    "MINIO_ROOT_USER:16"
    "MINIO_ROOT_PASSWORD:32"
    "GRAFANA_PASSWORD:24"
    "SOYMUTDB_JWT_SECRET:48"
    "SOYMUTDB_ADMIN_PASSWORD:16"
)

[[ -f "${TEMPLATE}" ]] || die "template not found: ${TEMPLATE}"

# ---------------------------------------------------------------------
# --template：从模板新建
# ---------------------------------------------------------------------
if [[ "${DO_TEMPLATE}" == "1" ]]; then
    if [[ -f "${ENV_FILE}" ]]; then
        die "refusing to overwrite existing ${ENV_FILE}; remove it or use --env-file"
    fi
    mkdir -p "$(dirname "${ENV_FILE}")"
    cp "${TEMPLATE}" "${ENV_FILE}"
    info "created ${ENV_FILE} from ${TEMPLATE}"
fi

[[ -f "${ENV_FILE}" ]] || die "env file not found: ${ENV_FILE} (use --template to create, or --env-file)"

if [[ "${MODE}" == "bootstrap" ]]; then
    # 备份当前文件
    BAK="${ENV_FILE}.bak-$(date +%Y%m%d_%H%M%S)"
    cp -- "${ENV_FILE}" "${BAK}"
    info "backed up current env to ${BAK}"
fi

changed=0
for entry in "${REQUIRED_SECRETS[@]}"; do
    key="${entry%%:*}"
    min_len="${entry##*:}"
    cur="$(get_env "${key}")"
    if [[ -z "${cur}" ]] || is_placeholder "${cur}"; then
        if [[ "${MODE}" == "bootstrap" ]]; then
            case "${key}" in
                MINIO_ROOT_USER) val="soymutdb_admin_$(hex 8)" ;;
                SOYMUTDB_JWT_SECRET) val="$(b64url 64)" ;;
                *) val="$(b64url "${min_len}")" ;;
            esac
            set_env "${key}" "${val}"
            info "generated ${key}"
            changed=$((changed+1))
        else
            warn "${key} is placeholder/blank (--check mode, not writing)"
        fi
    else
        info "${key} already set (${#cur} chars, left unchanged)"
    fi
done

# CORS：非秘密，脚本不生成，只校验
cors="$(get_env SOYMUTDB_CORS_ORIGINS)"
if [[ -z "${cors}" ]] || [[ "${cors}" == *'*'* ]]; then
    check_fail "SOYMUTDB_CORS_ORIGINS must be set to explicit comma-separated HTTPS origins (no wildcard)"
else
    info "SOYMUTDB_CORS_ORIGINS = ${cors}"
fi

# 管理员（非秘密部分：email 只校验；password 已在 REQUIRED_SECRETS 生成）
adm_email="$(get_env SOYMUTDB_ADMIN_EMAIL)"
if [[ -z "${adm_email}" || "${adm_email}" == "admin@soymutdb.local" || "${adm_email}" != *@* ]]; then
    check_fail "SOYMUTDB_ADMIN_EMAIL must be set to a valid non-default address"
fi

# ---------------------------------------------------------------------
# 校验（与 config.py / upgrade.sh 对齐；check_fail/validation_failed 已在上方定义）
# ---------------------------------------------------------------------
jwt="$(get_env SOYMUTDB_JWT_SECRET)"
if [[ -z "${jwt}" || "${#jwt}" -lt 32 ]]; then check_fail "SOYMUTDB_JWT_SECRET must be >= 32 chars"; fi
case "${jwt,,}" in
    dev_jwt_secret_change_in_production|your-secret-key|your-secret-key-change-me|change-me-in-production|change-me)
        check_fail "SOYMUTDB_JWT_SECRET is an example value" ;;
esac

for c in POSTGRES_PASSWORD CLICKHOUSE_PASSWORD REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD; do
    v="$(get_env "${c}")"
    case "${v}" in
        change-me-*|soymutdb_dev_password|minioadmin|admin|''|admin123)
            check_fail "${c} still uses a default/placeholder value" ;;
    esac
done

graf="$(get_env GRAFANA_PASSWORD)"
if [[ -z "${graf}" || "${graf}" == "admin" || "${graf}" == change-me-* ]]; then
    check_fail "GRAFANA_PASSWORD must be set and not 'admin'"
fi

adm_pw="$(get_env SOYMUTDB_ADMIN_PASSWORD)"
if [[ -z "${adm_pw}" || "${#adm_pw}" -lt 12 ]]; then
    check_fail "SOYMUTDB_ADMIN_PASSWORD must be >= 12 chars"
fi
case "${adm_pw,,}" in
    admin123|change-me|change-me-*|password|admin) check_fail "SOYMUTDB_ADMIN_PASSWORD is an example/default value" ;;
esac

pg="$(get_env POSTGRES_PASSWORD)"; ch="$(get_env CLICKHOUSE_PASSWORD)"
if [[ -n "${pg}" && "${pg}" == "${ch:-}" ]]; then warn "POSTGRES/CLICKHOUSE passwords are identical (consider distinct)"; fi

if [[ "${validation_failed}" -ne 0 ]]; then
    if [[ "${DO_TEMPLATE}" == "1" ]]; then
        warn "template scaffold created, but ${validation_failed} item(s) need operator attention before production (see above)"
    else
        die "production env validation FAILED (${validation_failed} problem(s)); fix the values above"
    fi
fi

if [[ "${MODE}" == "bootstrap" ]]; then
    chmod 600 "${ENV_FILE}"
    info "wrote ${ENV_FILE} (mode 0600), generated ${changed} secret(s)"
elif [[ "${MODE}" == "check" ]]; then
    info "validation OK (check-only, no writes)"
fi

if [[ "${COMPOSE_PREFLIGHT}" == "1" ]]; then
    echo -e "${CYAN}  Running docker compose config -q ...${NC}"
    if (cd "${PROJECT_ROOT}" && SOYMUTDB_ENV_FILE="${ENV_FILE}" docker compose --env-file "${ENV_FILE}" config -q); then
        info "compose config OK"
    else
        die "docker compose config -q failed"
    fi
fi

info "done."

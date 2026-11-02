#!/usr/bin/env bash
# =====================================================================
# Shared runtime routing for the authoritative backup/restore scripts
# =====================================================================
# Sourced by deploy/scripts/backup.sh, deploy/scripts/restore.sh and
# deploy/scripts/verify-restore.sh. Never executed on its own.
#
# The runtime is chosen explicitly with SOYMUTDB_BACKUP_RUNTIME (or the
# --runtime flag, which wins over the environment) and is one of:
#
#   compose  the default, and the only behaviour-change-free option: a
#            PostgreSQL host on loopback is reached through the compose
#            postgres service, and mc may fall back to the minio/mc image.
#   native   a host-level deployment: the PostgreSQL client tools are
#            always invoked directly (psql/pg_dump/pg_restore/dropdb/
#            createdb), mc must exist on PATH, and there is no container
#            fallback of any kind. A missing tool is a hard failure, never
#            a silent downgrade to another runtime.
#
# Every unsupported value fails closed. Nothing here infers the runtime
# from a hostname, an IP, a port, or a file that happens to exist.
# =====================================================================

SOYMUTDB_BACKUP_RUNTIME_DEFAULT="compose"
SOYMUTDB_BACKUP_RUNTIME_VALUES="compose native"
# The declared confirmation the operator must set when the compose service
# table is unavailable (native runtime) and therefore cannot be inspected.
SOYMUTDB_NATIVE_WRITES_STOPPED_VAR="SOYMUTDB_NATIVE_WRITES_STOPPED"
# The quiesced-writes flag is script specific: backup.sh attests
# BACKUP_WRITES_QUIESCED, restore.sh attests RESTORE_WRITES_QUIESCED. A caller
# overrides the name so the gate and its message name the flag that script
# actually requires, instead of failing on a variable it never reads.
SOYMUTDB_RUNTIME_QUIESCED_FLAG_DEFAULT="BACKUP_WRITES_QUIESCED"

backup_runtime_quiesced_flag() {
    printf '%s\n' "${SOYMUTDB_RUNTIME_QUIESCED_FLAG:-${SOYMUTDB_RUNTIME_QUIESCED_FLAG_DEFAULT}}"
}

backup_runtime_fail() {
    printf '[ERROR] %s\n' "$*" >&2
    return 1
}

# Prints the canonical runtime name, or returns 1 for anything else.
backup_runtime_canonical() {
    local raw="${1-}"
    [[ -n "${raw}" ]] || raw="${SOYMUTDB_BACKUP_RUNTIME_DEFAULT}"
    case "${raw}" in
        compose|native) printf '%s\n' "${raw}" ;;
        *) return 1 ;;
    esac
}

# Resolves BACKUP_RUNTIME from an optional --runtime value (which wins over
# the environment) and SOYMUTDB_BACKUP_RUNTIME. Returns 1 and explains itself
# on an unknown value so the caller can abort before touching any data.
backup_runtime_require() {
    local requested="${1-}" resolved
    if [[ -z "${requested}" ]]; then
        requested="${SOYMUTDB_BACKUP_RUNTIME-}"
    fi
    if ! resolved="$(backup_runtime_canonical "${requested}")"; then
        backup_runtime_fail "unsupported SOYMUTDB_BACKUP_RUNTIME='${requested}'; supported runtimes are: ${SOYMUTDB_BACKUP_RUNTIME_VALUES}"
        return 1
    fi
    BACKUP_RUNTIME="${resolved}"
    SOYMUTDB_BACKUP_RUNTIME="${resolved}"
    export SOYMUTDB_BACKUP_RUNTIME
}

backup_runtime_is_native() {
    [[ "${BACKUP_RUNTIME:-${SOYMUTDB_BACKUP_RUNTIME_DEFAULT}}" == "native" ]]
}

# SOYMUTDB_BACKUP_REPO_ENV=0 keeps the repository .env out of the process so an
# isolated drill or an offline contract test cannot inherit operator state.
backup_runtime_repo_env_enabled() {
    case "${SOYMUTDB_BACKUP_REPO_ENV:-1}" in
        1|true|TRUE|yes|YES) return 0 ;;
        0|false|FALSE|no|NO) return 1 ;;
        *)
            backup_runtime_fail "SOYMUTDB_BACKUP_REPO_ENV must be 0 or 1 (got '${SOYMUTDB_BACKUP_REPO_ENV}')"
            return 2 ;;
    esac
}

backup_runtime_load_repo_env() {
    local project_root="$1" enabled
    enabled=0
    backup_runtime_repo_env_enabled || enabled=$?
    if [[ "${enabled}" == "2" ]]; then
        return 1
    fi
    if [[ "${enabled}" != "0" ]]; then
        return 0
    fi
    [[ -f "${project_root}/.env" ]] || return 0
    set -a
    # shellcheck disable=SC1091
    source "${project_root}/.env"
    set +a
}

# Native runs have no container fallback: every client tool must already be
# installed, and a missing one stops the run instead of silently reaching for
# Docker. Compose runs still require the docker CLI they always relied on.
backup_runtime_assert_tools() {
    local tool missing=0
    for tool in "$@"; do
        command -v "${tool}" >/dev/null 2>&1 || {
            backup_runtime_fail "required tool is unavailable: ${tool}"
            missing=1
        }
    done
    [[ "${missing}" == "0" ]]
}

backup_runtime_assert_mc() {
    backup_runtime_is_native || return 0
    if ! command -v mc >/dev/null 2>&1; then
        backup_runtime_fail "the native runtime requires the MinIO client 'mc' on PATH; it never falls back to the minio/mc container"
        return 1
    fi
}

# The compose runtime keeps its historical loopback rule: a loopback PostgreSQL
# host means the compose postgres service. The native runtime never routes
# through compose, whatever the host happens to be.
backup_runtime_pg_uses_compose() {
    backup_runtime_is_native && return 1
    case "${PG_HOST:-}" in
        localhost|127.0.0.1) return 0 ;;
        *) return 1 ;;
    esac
}

backup_runtime_pg_client_mode() {
    if backup_runtime_pg_uses_compose; then
        printf 'compose-postgres-service\n'
    else
        printf 'native-postgres-client\n'
    fi
}

backup_runtime_mc_client_mode() {
    if backup_runtime_is_native; then
        printf 'native-mc\n'
    else
        printf 'mc-or-container\n'
    fi
}

# Records how this run proved the writers were stopped. The compose runtime
# inspects the compose service table; the native runtime can only carry the
# operator's explicit out-of-band confirmation plus a live connection probe.
backup_runtime_writers_attestation() {
    if backup_runtime_is_native; then
        printf 'declared-native-quiescence\n'
    else
        printf 'compose-service-state\n'
    fi
}

runtime_pg_query() {
    local sql="$1"
    if backup_runtime_pg_uses_compose; then
        compose_exec postgres psql -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    fi
}

runtime_pg_dump_to() {
    local target="$1"
    if backup_runtime_pg_uses_compose; then
        compose_exec postgres pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc > "${target}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            pg_dump -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
                -Fc -f "${target}"
    fi
}

runtime_pg_dropdb() {
    if backup_runtime_pg_uses_compose; then
        compose_exec postgres dropdb -U "${PG_USER}" --if-exists --force "${PG_DB}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            dropdb -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
                --if-exists --force "${PG_DB}"
    fi
}

runtime_pg_createdb() {
    if backup_runtime_pg_uses_compose; then
        compose_exec postgres createdb -U "${PG_USER}" --owner "${PG_USER}" "${PG_DB}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            createdb -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
                --owner "${PG_USER}" "${PG_DB}"
    fi
}

# The dump path is a container-local path in the compose runtime and a host
# path otherwise; pg_restore itself is invoked the same way in both cases.
runtime_pg_restore_file() {
    local dump_path="$1"
    if backup_runtime_pg_uses_compose; then
        compose_exec postgres pg_restore -U "${PG_USER}" -d "${PG_DB}" \
            --no-owner --no-privileges "${dump_path}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            pg_restore -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" \
                --no-owner --no-privileges "${dump_path}"
    fi
}

# Compose keeps the container-image fallback it has always had. Native must
# have a real mc and refuses to run anything through a container.
runtime_mc_run() {
    local env_name
    local -a docker_env_args=()
    if command -v mc >/dev/null 2>&1; then
        mc --config-dir "${MC_CFG_DIR}" "$@"
    elif backup_runtime_is_native; then
        backup_runtime_fail "the native runtime requires the MinIO client 'mc' on PATH; it never falls back to the minio/mc container"
        return 1
    else
        for env_name in "${MC_ENV_NAMES[@]}"; do
            docker_env_args+=(--env "${env_name}")
        done
        docker run --rm --network host \
            "${docker_env_args[@]}" \
            -v "${MC_CFG_DIR}:/root/.mc" \
            -v "${BAK_BASE_DIR}:${BAK_BASE_DIR}" \
            minio/mc:RELEASE.2024-01-01T00-00-00Z \
            --config-dir /root/.mc "$@"
    fi
}

# Normalize only the documented no-policy forms; preserve all other fields.
# Nonempty policies remain exact JSON objects for verification and replay.
runtime_policy_json() {
    python3 - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    policy = json.load(handle)
if not isinstance(policy, dict):
    raise SystemExit("S3 policy must be a JSON object")
if not policy or (
    policy.get("Statement") == []
    and set(policy) <= {"Version", "Statement"}
):
    policy = {}
print(json.dumps(policy, sort_keys=True, separators=(",", ":")))
PY
}

runtime_restore_policy() {
    local policy_file="$1" destination="$2" policy
    policy="$(runtime_policy_json "${policy_file}")" || return 1
    if [[ "${policy}" == '{}' ]]; then
        mc_run anonymous set none "${destination}"
    else
        mc_run anonymous set-json "${policy_file}" "${destination}"
    fi
}

# Native runs cannot inspect the compose service table, so the writers-quiesced
# claim has to be an explicit operator attestation, and it is never taken on
# trust alone: an additional live probe fails the run while any non-idle
# session is still attached to the database. The compose runtime keeps its own
# service-table guard, which the calling script defines as assert_writers_stopped.
backup_runtime_assert_writers_stopped() {
    local active quiesced_flag
    if backup_runtime_is_native; then
        quiesced_flag="$(backup_runtime_quiesced_flag)"
        [[ "${!quiesced_flag:-0}" == "1" ]] \
            || {
                backup_runtime_fail "${quiesced_flag}=1 is required after stopping all writers"
                return 1
            }
        [[ "${!SOYMUTDB_NATIVE_WRITES_STOPPED_VAR:-0}" == "1" ]] \
            || {
                backup_runtime_fail "the native runtime cannot inspect compose services; set ${SOYMUTDB_NATIVE_WRITES_STOPPED_VAR}=1 to attest that every writer was stopped out of band"
                return 1
            }
        if ! active="$(runtime_pg_query "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND datname = current_database() AND state IN ('active','idle in transaction')")"; then
            backup_runtime_fail "the native writer probe could not read pg_stat_activity; quiescence cannot be proven"
            return 1
        fi
        active="${active//$'\r'/}"
        [[ "${active}" =~ ^[0-9]+$ ]] \
            || {
                backup_runtime_fail "the native writer probe returned an invalid count: ${active:-empty}"
                return 1
            }
        [[ "${active}" == "0" ]] \
            || {
                backup_runtime_fail "${active} writer session(s) are still connected to ${PG_DB}; stop every writer before an authoritative native backup"
                return 1
            }
        return 0
    fi
    assert_writers_stopped || return 1
}

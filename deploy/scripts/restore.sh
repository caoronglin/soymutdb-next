#!/usr/bin/env bash
# =====================================================================
# SoyMutDB authoritative restore (formats v3 and legacy v2)
# =====================================================================
# Restore is destructive. It performs all archive, component, snapshot,
# bucket-list, and artifact checksum preflight checks before confirmation.
# Format v3 covers the authoritative PostgreSQL database, every listed S3
# bucket, and bucket policies. Format v2 archives additionally carry a
# database-level ClickHouse component and are refused unless the operator asks
# for them explicitly with --allow-legacy-v2; that mode requires a ClickHouse
# service in the target compose file and fails when it is absent.
# Every component declared by the archive is mandatory; no component has an
# implicit fallback, degradation, or skip.
#
#
# The runtime is explicit. SOYMUTDB_BACKUP_RUNTIME (or --runtime, which wins)
# selects compose (the default, unchanged behaviour) or native, which always
# uses the host PostgreSQL client tools and a host 'mc' binary and never falls
# back to a container. An unsupported value fails closed before any data is
# touched. A non-production native target additionally has to attest its
# runtime and its isolated instance in the target config.
#
# Usage:
#   bash deploy/scripts/restore.sh --target drill --target-config /secure/drill.env <backup.tar.gz>
#   bash deploy/scripts/restore.sh --target prod <backup.tar.gz>
#   bash deploy/scripts/restore.sh --runtime native --target drill \
#       --target-config /secure/drill-native.env <backup.tar.gz>
#   bash deploy/scripts/restore.sh --allow-legacy-v2 --target prod <legacy-v2.tar.gz>
#   bash deploy/scripts/restore.sh --no-repo-env --target drill ... <backup.tar.gz>
# =====================================================================
set -Eeuo pipefail
umask 077

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${GREEN}  $*${NC}"; }
err()  { echo -e "${RED}[ERROR] $*${NC}" >&2; }
die()  { err "$*"; exit 1; }

readonly REQUIRED_S3_BUCKETS="genomic-data user-tracks blast-dbs exports gwas analyses"
# Restore proves quiescence with RESTORE_WRITES_QUIESCED, not the backup-side
# flag, so the shared native gate has to check and name this variable.
SOYMUTDB_RUNTIME_QUIESCED_FLAG="RESTORE_WRITES_QUIESCED"
readonly -a QUIESCED_WRITER_SERVICES=(api worker-default worker-analyses worker-blast worker-ingest beat)

TARGET_ARG=""
TARGET_CONFIG=""
RUNTIME_ARG=""
ALLOW_LEGACY_V2=0
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --allow-legacy-v2) ALLOW_LEGACY_V2=1; shift ;;
        --target)
            [[ $# -ge 2 ]] || die "--target requires a value"
            TARGET_ARG="$2"
            shift 2
            ;;
        --target=*) TARGET_ARG="${1#*=}"; shift ;;
        --target-config)
            [[ $# -ge 2 ]] || die "--target-config requires a value"
            TARGET_CONFIG="$2"
            shift 2
            ;;
        --target-config=*) TARGET_CONFIG="${1#*=}"; shift ;;
        --runtime)
            [[ $# -ge 2 ]] || die "--runtime requires a value"
            RUNTIME_ARG="$2"
            shift 2
            ;;
        --runtime=*) RUNTIME_ARG="${1#*=}"; shift ;;
        --no-repo-env)
            SOYMUTDB_BACKUP_REPO_ENV=0
            shift
            ;;
        --help|-h)
            sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        -*) die "unknown option: $1" ;;
        *)
            [[ -z "${BACKUP_FILE}" ]] || die "too many arguments: $1"
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

[[ -n "${BACKUP_FILE}" ]] \
    || die "Usage: bash deploy/scripts/restore.sh --target <name> <backup.tar.gz>"
[[ -f "${BACKUP_FILE}" ]] || die "backup file not found: ${BACKUP_FILE}"
TARGET="${TARGET_ARG:-${TARGET:-}}"
[[ -n "${TARGET}" ]] || die "restore target is required (for example --target drill)"
[[ "${TARGET}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]] \
    || die "restore target contains unsafe characters"
IS_PROD=0
case "${TARGET}" in
    prod|production) IS_PROD=1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=deploy/scripts/mc-auth.sh
source "${SCRIPT_DIR}/mc-auth.sh"
# shellcheck source=deploy/scripts/backup-runtime.sh
source "${SCRIPT_DIR}/backup-runtime.sh"

SOYMUTDB_BACKUP_RUNTIME_REQUESTED=0
[[ -n "${RUNTIME_ARG}" ]] && SOYMUTDB_BACKUP_RUNTIME_REQUESTED=1
# Production restore is the only mode that inherits the repository .env, and
# even there --no-repo-env / SOYMUTDB_BACKUP_REPO_ENV=0 keeps it out.
if [[ "${IS_PROD}" == "1" ]]; then
    backup_runtime_load_repo_env "${PROJECT_ROOT}" || die "repository .env loading was rejected"
fi
if [[ -z "${RUNTIME_ARG}" && -n "${SOYMUTDB_BACKUP_RUNTIME:-}" ]]; then
    SOYMUTDB_BACKUP_RUNTIME_REQUESTED=1
fi
backup_runtime_require "${RUNTIME_ARG}" || exit 1

INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
DEFAULT_COMPOSE_FILE="${COMPOSE_DIR}/docker-compose.yml"
COMPOSE_BIN=(docker compose --project-directory "${COMPOSE_DIR}" -f "${DEFAULT_COMPOSE_FILE}")

BAK_BASE_DIR="${BAK_BASE_DIR:-/opt/soymutdb/backups}"
RESTORE_STATE_FILE="${BAK_BASE_DIR}/restore-${TARGET}.incomplete"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"
CH_HOST=""
CH_USER=""
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"

assert_runtime_tools() {
    # The compose runtime keeps exactly the tool set it always required;
    # the native runtime adds the host PostgreSQL clients it now calls directly.
    local -a runtime_pg_tools=()
    if backup_runtime_is_native; then
        runtime_pg_tools=(dropdb createdb pg_restore psql)
    fi
    backup_runtime_assert_tools python3 sha256sum stat realpath grep \
        "${runtime_pg_tools[@]}" || return 1
    # A missing mc is fatal in the native runtime and never a container fallback.
    backup_runtime_assert_mc || return 1
}
assert_runtime_tools || exit 1

RESTORE_DIR="$(mktemp -d)"
PG_CONTAINER_FILE=""
CH_CONTAINER_FILE=""
cleanup() {
    local rc="$?"
    trap - EXIT
    if [[ -n "${PG_CONTAINER_FILE}" ]]; then
        "${COMPOSE_BIN[@]}" exec -T postgres rm -f "${PG_CONTAINER_FILE}" >/dev/null 2>&1 || true
    fi
    if [[ -n "${CH_CONTAINER_FILE}" ]]; then
        "${COMPOSE_BIN[@]}" exec -T clickhouse rm -f "${CH_CONTAINER_FILE}" >/dev/null 2>&1 || true
    fi
    rm -rf -- "${RESTORE_DIR}"
    exit "${rc}"
}
trap cleanup EXIT

verify_archive_sidecar() {
    local sidecar="${BACKUP_FILE}.sha256" expected name extra actual
    [[ -f "${sidecar}" ]] || die "archive checksum sidecar is required: ${sidecar}"
    IFS=' ' read -r expected name extra < "${sidecar}" \
        || die "archive checksum sidecar cannot be read"
    [[ "${expected}" =~ ^[0-9a-f]{64}$ && "${name}" == "$(basename "${BACKUP_FILE}")" && -z "${extra}" ]] \
        || die "archive checksum sidecar is malformed or names another archive"
    actual="$(sha256sum "${BACKUP_FILE}" | awk '{print $1}')"
    [[ "${actual}" == "${expected}" ]] || die "archive checksum mismatch"
    ARCHIVE_SHA_ACTUAL="${actual}"
}
verify_archive_sidecar

verify_completion_marker() {
    local marker="${BACKUP_FILE}.complete" key value
    COMPLETE_BACKUP_ID=""
    COMPLETE_ARCHIVE_SHA=""
    [[ -f "${marker}" ]] || die "backup completion marker is required: ${marker}"
    while IFS='=' read -r key value; do
        case "${key}" in
            backup_id)
                [[ -z "${COMPLETE_BACKUP_ID}" ]] || die "backup completion marker has duplicate backup_id"
                COMPLETE_BACKUP_ID="${value}"
                ;;
            sha256)
                [[ -z "${COMPLETE_ARCHIVE_SHA}" ]] || die "backup completion marker has duplicate sha256"
                COMPLETE_ARCHIVE_SHA="${value}"
                ;;
            *) die "backup completion marker contains an unknown field" ;;
        esac
    done < "${marker}"
    [[ "${COMPLETE_BACKUP_ID}" =~ ^[A-Za-z0-9._-]+$ ]] \
        || die "backup completion marker has an invalid backup_id"
    [[ "${COMPLETE_ARCHIVE_SHA}" =~ ^[0-9a-f]{64}$ ]] \
        || die "backup completion marker has an invalid sha256"
    [[ "${COMPLETE_ARCHIVE_SHA}" == "${ARCHIVE_SHA_ACTUAL}" ]] \
        || die "backup completion marker checksum mismatch"
}
verify_completion_marker

python3 - "${BACKUP_FILE}" "${RESTORE_DIR}" <<'PY'
import pathlib
import sys
import tarfile

archive, destination = sys.argv[1:]
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()
    if not members:
        raise SystemExit("backup archive is empty")
    roots = set()
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise SystemExit(f"unsafe archive member: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"unsupported archive member type: {member.name}")
        roots.add(path.parts[0])
    if len(roots) != 1:
        raise SystemExit("backup archive must contain exactly one top-level directory")
    handle.extractall(destination)
PY

mapfile -t RESTORE_ROOTS < <(find "${RESTORE_DIR}" -mindepth 1 -maxdepth 1 -type d -print)
[[ ${#RESTORE_ROOTS[@]} -eq 1 ]] || die "backup archive has no unique content directory"
RESTORE_SRC="${RESTORE_ROOTS[0]}"
MANIFEST="${RESTORE_SRC}/manifest.json"
[[ -f "${MANIFEST}" ]] || die "manifest.json is required"

manifest_get() {
    local path="$1"
    python3 - "${MANIFEST}" "${path}" <<'PY'
import json
import sys

filename, dotted_path = sys.argv[1:]
with open(filename, encoding="utf-8") as handle:
    value = json.load(handle)
for key in dotted_path.split("."):
    if not isinstance(value, dict) or key not in value:
        raise SystemExit(f"missing manifest field: {dotted_path}")
    value = value[key]
if isinstance(value, bool) or not isinstance(value, (str, int)):
    raise SystemExit(f"manifest field is not scalar: {dotted_path}")
print(value)
PY
}

validate_relative_path() {
    local value="$1" segment
    [[ -n "${value}" && "${value}" != /* ]] || return 1
    [[ "${value}" != *$'\t'* && "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] || return 1
    IFS='/' read -r -a segments <<< "${value}"
    for segment in "${segments[@]}"; do
        [[ -n "${segment}" && "${segment}" != "." && "${segment}" != ".." ]] || return 1
    done
}

BACKUP_FORMAT_VERSION="$(manifest_get format_version)"
LEGACY_V2=0
case "${BACKUP_FORMAT_VERSION}" in
    3) ;;
    2)
        [[ "${ALLOW_LEGACY_V2}" == "1" ]] \
            || die "archive is legacy format v2; re-run with --allow-legacy-v2 to restore it explicitly (format v3 is the authoritative default)"
        LEGACY_V2=1
        ;;
    *) die "unsupported manifest format_version: ${BACKUP_FORMAT_VERSION}" ;;
esac
[[ "$(manifest_get consistency.mode)" == "writers_quiesced" ]] \
    || die "backup consistency mode is not safe for authoritative restore"
BACKUP_ID="$(manifest_get backup_id)"
[[ "${BACKUP_ID}" == "${COMPLETE_BACKUP_ID}" ]] \
    || die "backup completion marker backup_id mismatch"
declare -a REQUIRED_COMPONENTS=(postgres s3)
if [[ "${LEGACY_V2}" == "1" ]]; then
    REQUIRED_COMPONENTS=(postgres clickhouse s3)
fi
for component in "${REQUIRED_COMPONENTS[@]}"; do
    status="$(manifest_get "components.${component}.status")" \
        || die "missing ${component} component status"
    [[ "${status}" == "ok" ]] \
        || die "${component} component status must be 'ok' (got '${status}')"
done

ARTIFACT_MANIFEST_REL="$(manifest_get artifact_manifest.file)"
ARTIFACT_MANIFEST_SIZE="$(manifest_get artifact_manifest.size)"
ARTIFACT_MANIFEST_SHA="$(manifest_get artifact_manifest.sha256)"
validate_relative_path "${ARTIFACT_MANIFEST_REL}" || die "unsafe artifact manifest path"
[[ "${ARTIFACT_MANIFEST_SIZE}" =~ ^[0-9]+$ && "${ARTIFACT_MANIFEST_SHA}" =~ ^[0-9a-f]{64}$ ]] \
    || die "artifact manifest metadata is invalid"
ARTIFACT_MANIFEST="${RESTORE_SRC}/${ARTIFACT_MANIFEST_REL}"
[[ -s "${ARTIFACT_MANIFEST}" ]] || die "artifact checksum manifest is missing or empty"
[[ "$(stat -c%s "${ARTIFACT_MANIFEST}")" == "${ARTIFACT_MANIFEST_SIZE}" ]] \
    || die "artifact checksum manifest size mismatch"
[[ "$(sha256sum "${ARTIFACT_MANIFEST}" | awk '{print $1}')" == "${ARTIFACT_MANIFEST_SHA}" ]] \
    || die "artifact checksum manifest checksum mismatch"

verify_artifact_manifest() {
    local hash size relative extra path actual count=0
    while IFS=$'\t' read -r hash size relative extra; do
        [[ -n "${hash}${size}${relative}${extra}" ]] || continue
        [[ -z "${extra}" && "${hash}" =~ ^[0-9a-f]{64}$ && "${size}" =~ ^[0-9]+$ ]] \
            || die "artifact checksum manifest contains an invalid row"
        validate_relative_path "${relative}" \
            || die "artifact checksum manifest contains an unsafe path"
        path="${RESTORE_SRC}/${relative}"
        [[ -f "${path}" && ! -L "${path}" ]] || die "artifact is missing: ${relative}"
        [[ "$(stat -c%s "${path}")" == "${size}" ]] \
            || die "artifact size mismatch: ${relative}"
        actual="$(sha256sum "${path}" | awk '{print $1}')"
        [[ "${actual}" == "${hash}" ]] || die "artifact checksum mismatch: ${relative}"
        count=$((count + 1))
    done < "${ARTIFACT_MANIFEST}"
    [[ "${count}" -gt 0 ]] || die "artifact checksum manifest has no rows"
}
verify_artifact_manifest

PG_DUMP_REL="$(manifest_get components.postgres.file)"
PG_ROWS_REL="$(manifest_get components.postgres.row_counts_file)"
PG_TABLES_EXPECTED="$(manifest_get components.postgres.tables)"
S3_MANIFEST_REL="$(manifest_get components.s3.manifest_file)"
# manifest key: "buckets_file"
S3_BUCKETS_REL="$(manifest_get components.s3.buckets_file)"
S3_OBJECTS_EXPECTED="$(manifest_get components.s3.object_count)"
S3_BYTES_EXPECTED="$(manifest_get components.s3.total_bytes)"
S3_CHECKSUM_ALGORITHM="$(manifest_get components.s3.checksum_algorithm)"
declare -a COMPONENT_RELPATHS=("${PG_DUMP_REL}" "${PG_ROWS_REL}" "${S3_MANIFEST_REL}" "${S3_BUCKETS_REL}")
CH_BACKUP_REL=""
CH_ROWS_REL=""
CH_TABLES_EXPECTED=0
if [[ "${LEGACY_V2}" == "1" ]]; then
    CH_BACKUP_REL="$(manifest_get components.clickhouse.file)"
    CH_ROWS_REL="$(manifest_get components.clickhouse.row_counts_file)"
    CH_TABLES_EXPECTED="$(manifest_get components.clickhouse.tables)"
    COMPONENT_RELPATHS+=("${CH_BACKUP_REL}" "${CH_ROWS_REL}")
fi
for relative in "${COMPONENT_RELPATHS[@]}"; do
    validate_relative_path "${relative}" || die "manifest contains an unsafe component path"
done
[[ "${PG_TABLES_EXPECTED}" =~ ^[1-9][0-9]*$ ]] \
    || die "row snapshot table counts must be positive"
[[ "${LEGACY_V2}" != "1" || "${CH_TABLES_EXPECTED}" =~ ^[1-9][0-9]*$ ]] \
    || die "row snapshot table counts must be positive"
[[ "${S3_OBJECTS_EXPECTED}" =~ ^[0-9]+$ && "${S3_BYTES_EXPECTED}" =~ ^[0-9]+$ ]] \
    || die "S3 manifest totals are invalid"
[[ "${S3_CHECKSUM_ALGORITHM}" == "sha256" ]] || die "S3 object checksums must use sha256"

PG_DUMP_FILE="${RESTORE_SRC}/${PG_DUMP_REL}"
PG_ROWS_FILE="${RESTORE_SRC}/${PG_ROWS_REL}"
S3_MANIFEST="${RESTORE_SRC}/${S3_MANIFEST_REL}"
S3_BUCKETS_FILE="${RESTORE_SRC}/${S3_BUCKETS_REL}"
[[ -s "${PG_DUMP_FILE}" ]] || die "mandatory PostgreSQL backup artifact is missing or empty"
CH_BACKUP_FILE=""
CH_ROWS_FILE=""
if [[ "${LEGACY_V2}" == "1" ]]; then
    CH_BACKUP_FILE="${RESTORE_SRC}/${CH_BACKUP_REL}"
    CH_ROWS_FILE="${RESTORE_SRC}/${CH_ROWS_REL}"
    [[ -s "${CH_BACKUP_FILE}" ]] \
        || die "mandatory ClickHouse backup artifact is missing or empty"
fi

validate_pg_snapshot() {
    local table count extra rows=0
    [[ -s "${PG_ROWS_FILE}" ]] || die "PostgreSQL row snapshot is empty"
    while IFS=$'\t' read -r table count extra; do
        [[ "${table}" =~ ^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$ ]] \
            || die "PostgreSQL row snapshot table identifier is unsafe"
        [[ "${count}" =~ ^[0-9]+$ && -z "${extra}" ]] \
            || die "PostgreSQL row snapshot contains an invalid row"
        rows=$((rows + 1))
    done < "${PG_ROWS_FILE}"
    [[ "${rows}" == "${PG_TABLES_EXPECTED}" ]] \
        || die "PostgreSQL row snapshot table count mismatch"
}

validate_ch_snapshot() {
    local table rows parts extra count=0
    [[ -s "${CH_ROWS_FILE}" ]] || die "ClickHouse row snapshot is empty"
    while IFS=$'\t' read -r table rows parts extra; do
        [[ "${table}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
            || die "ClickHouse row snapshot table identifier is unsafe"
        [[ "${rows}" =~ ^[0-9]+$ && "${parts}" =~ ^[0-9]+$ && -z "${extra}" ]] \
            || die "ClickHouse row snapshot contains an invalid row"
        count=$((count + 1))
    done < "${CH_ROWS_FILE}"
    [[ "${count}" == "${CH_TABLES_EXPECTED}" ]] \
        || die "ClickHouse row snapshot table count mismatch"
}
validate_pg_snapshot
if [[ "${LEGACY_V2}" == "1" ]]; then
    validate_ch_snapshot
fi

[[ -s "${S3_BUCKETS_FILE}" ]] || die "S3 bucket manifest is empty"
read -r -a REQUIRED_BUCKET_ARRAY <<< "${REQUIRED_S3_BUCKETS}"
declare -a S3_BUCKETS=()
declare -A LISTED_BUCKETS=()
while IFS= read -r bucket; do
    [[ "${bucket}" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] \
        || die "S3 bucket manifest contains an invalid bucket"
    [[ -z "${LISTED_BUCKETS[${bucket}]:-}" ]] || die "S3 bucket manifest contains a duplicate: ${bucket}"
    LISTED_BUCKETS["${bucket}"]=1
    S3_BUCKETS+=("${bucket}")
done < "${S3_BUCKETS_FILE}"
for bucket in "${REQUIRED_BUCKET_ARRAY[@]}"; do
    [[ -n "${LISTED_BUCKETS[${bucket}]:-}" ]] \
        || die "required bucket missing from manifest: ${bucket}"
done

S3_OBJECT_COUNT=0
S3_TOTAL_BYTES=0
while IFS=$'\t' read -r bucket relative size hash extra; do
    [[ -n "${bucket}${relative}${size}${hash}${extra}" ]] || continue
    [[ -n "${LISTED_BUCKETS[${bucket}]:-}" ]] || die "S3 object names an unlisted bucket: ${bucket}"
    validate_relative_path "${relative}" || die "S3 manifest contains an unsafe object path"
    [[ -z "${extra}" && "${size}" =~ ^[0-9]+$ && "${hash}" =~ ^[0-9a-f]{64}$ ]] \
        || die "S3 manifest contains an invalid object row"
    object="${RESTORE_SRC}/s3_data/${bucket}/${relative}"
    [[ -f "${object}" && ! -L "${object}" ]] || die "S3 backup object is missing: ${bucket}/${relative}"
    [[ "$(stat -c%s "${object}")" == "${size}" ]] \
        || die "S3 backup object size mismatch: ${bucket}/${relative}"
    [[ "$(sha256sum "${object}" | awk '{print $1}')" == "${hash}" ]] \
        || die "S3 backup object checksum mismatch: ${bucket}/${relative}"
    S3_OBJECT_COUNT=$((S3_OBJECT_COUNT + 1))
    S3_TOTAL_BYTES=$((S3_TOTAL_BYTES + size))
done < "${S3_MANIFEST}"
[[ "${S3_OBJECT_COUNT}" == "${S3_OBJECTS_EXPECTED}" && "${S3_TOTAL_BYTES}" == "${S3_BYTES_EXPECTED}" ]] \
    || die "S3 object manifest totals do not match manifest.json"
for bucket in "${S3_BUCKETS[@]}"; do
    [[ -d "${RESTORE_SRC}/s3_data/${bucket}" ]] || die "S3 bucket data directory is missing: ${bucket}"
    [[ -s "${RESTORE_SRC}/s3_policy_${bucket}.json" ]] || die "S3 bucket policy is missing: ${bucket}"
done

configure_restore_target() {
    local target_compose default_compose variable
    if [[ "${IS_PROD}" == "1" ]]; then
        [[ -z "${TARGET_CONFIG}" ]] \
            || die "production restore does not accept --target-config"
        return
    fi

    [[ -n "${TARGET_CONFIG}" && -f "${TARGET_CONFIG}" ]] \
        || die "an explicit target config (--target-config) is required for a non-production target"
    set -a
    # shellcheck disable=SC1090
    source "${TARGET_CONFIG}"
    set +a
    # The target config may itself select the runtime, but only when the
    # operator did not already pin one on the command line or in the
    # environment; the more explicit source always wins.
    if [[ "${SOYMUTDB_BACKUP_RUNTIME_REQUESTED}" == "0" ]]; then
        backup_runtime_require "" || exit 1
    fi
    for variable in \
        RESTORE_TARGET_ID RESTORE_TARGET_ISOLATED \
        RESTORE_POSTGRES_HOST RESTORE_POSTGRES_PORT \
        RESTORE_POSTGRES_USER RESTORE_POSTGRES_DB RESTORE_POSTGRES_PASSWORD \
        RESTORE_S3_ENDPOINT RESTORE_S3_ACCESS_KEY RESTORE_S3_SECRET_KEY; do
        [[ -n "${!variable:-}" ]] || die "target config is missing ${variable}"
    done
    if [[ "${LEGACY_V2}" == "1" ]]; then
        for variable in RESTORE_CLICKHOUSE_HOST RESTORE_CLICKHOUSE_USER; do
            [[ -n "${!variable:-}" ]] || die "target config is missing ${variable} (required by --allow-legacy-v2)"
        done
    fi
    [[ "${RESTORE_TARGET_ID}" == "${TARGET}" && "${RESTORE_TARGET_ISOLATED}" == "1" ]] \
        || die "target config does not attest the requested isolated target"

    PG_HOST="${RESTORE_POSTGRES_HOST}"
    PG_PORT="${RESTORE_POSTGRES_PORT}"
    PG_USER="${RESTORE_POSTGRES_USER}"
    PG_DB="${RESTORE_POSTGRES_DB}"
    POSTGRES_PASSWORD="${RESTORE_POSTGRES_PASSWORD}"
    S3_ENDPOINT="${RESTORE_S3_ENDPOINT}"
    S3_ACCESS_KEY="${RESTORE_S3_ACCESS_KEY}"
    S3_SECRET_KEY="${RESTORE_S3_SECRET_KEY}"
    if [[ "${LEGACY_V2}" == "1" ]]; then
        CH_HOST="${RESTORE_CLICKHOUSE_HOST}"
        CH_USER="${RESTORE_CLICKHOUSE_USER}"
    fi

    if backup_runtime_is_native; then
        # An isolated native target has to say so, and has to name the
        # instance it owns. Production is never reachable through this path:
        # it has no target config at all.
        [[ "${RESTORE_TARGET_RUNTIME:-}" == "native" ]] \
            || die "target config must attest RESTORE_TARGET_RUNTIME=native for a native restore target"
        [[ "${RESTORE_NATIVE_INSTANCE_ID:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] \
            || die "target config must set RESTORE_NATIVE_INSTANCE_ID to the isolated native instance id"
        case "${RESTORE_NATIVE_INSTANCE_ID}" in
            prod|production)
                die "RESTORE_NATIVE_INSTANCE_ID must not name the production instance"
                ;;
        esac
        if [[ -n "${RESTORE_COMPOSE_FILE:-}" ]]; then
            target_compose="$(realpath "${RESTORE_COMPOSE_FILE}")"
            default_compose="$(realpath "${DEFAULT_COMPOSE_FILE}")"
            [[ "${target_compose}" != "${default_compose}" ]] \
                || die "isolated target must not use the default production compose file"
        fi
        return
    fi

    [[ "${RESTORE_COMPOSE_PROJECT}" =~ ^[a-z0-9][a-z0-9_-]{0,62}$ ]] \
        || die "target config compose project name is unsafe"
    [[ -n "${RESTORE_COMPOSE_FILE}" && -f "${RESTORE_COMPOSE_FILE}" ]] \
        || die "target config compose file does not exist"
    target_compose="$(realpath "${RESTORE_COMPOSE_FILE}")"
    default_compose="$(realpath "${DEFAULT_COMPOSE_FILE}")"
    [[ "${target_compose}" != "${default_compose}" ]] \
        || die "isolated target must not use the default production compose file"

    COMPOSE_DIR="$(dirname "${target_compose}")"
    COMPOSE_BIN=(
        docker compose --project-directory "${COMPOSE_DIR}"
        --project-name "${RESTORE_COMPOSE_PROJECT}" -f "${target_compose}"
    )
}

assert_compose_services_present() {
    local service services
    declare -a needed=(postgres)
    if [[ "${LEGACY_V2}" == "1" ]]; then
        needed+=(clickhouse)
    fi
    if ! services="$("${COMPOSE_BIN[@]}" config --services 2>/dev/null)"; then
        die "could not read the compose service list of the restore target"
    fi
    for service in "${needed[@]}"; do
        grep -qx -- "${service}" <<< "${services}" \
            || die "restore target compose file has no ${service} service; a required component is missing and restore cannot continue"
    done
}

assert_writers_stopped() {
    local service running
    [[ "${RESTORE_WRITES_QUIESCED:-0}" == "1" ]] \
        || { die "RESTORE_WRITES_QUIESCED=1 is required after stopping all writers"; return 1; }
    backup_runtime_is_native && return 0
    for service in "${QUIESCED_WRITER_SERVICES[@]}"; do
        if ! running="$("${COMPOSE_BIN[@]}" ps --status running -q "${service}" 2>/dev/null)"; then
            die "could not verify writer state for compose service: ${service}"
            return 1
        fi
        if [[ -n "${running}" ]]; then
            die "writer service must be stopped before restore: ${service}"
            return 1
        fi
    done
}

# Checked before the target config is read: a legacy archive carries a
# ClickHouse component that only the compose runtime can restore, and that
# refusal must not be reported as a missing target setting.
if [[ "${LEGACY_V2}" == "1" ]] && backup_runtime_is_native; then
    die "legacy format v2 carries a ClickHouse component and can only be restored in the compose runtime"
fi

configure_restore_target
if [[ "${LEGACY_V2}" == "1" ]]; then
    legacy_compose="${RESTORE_LEGACY_COMPOSE_FILE:-${COMPOSE_DIR}/docker-compose.legacy-clickhouse.yml}"
    if [[ -n "${RESTORE_LEGACY_COMPOSE_FILE:-}" && ! -f "${legacy_compose}" ]]; then
        die "the explicitly configured legacy compose overlay is missing"
    fi
    if [[ -f "${legacy_compose}" ]]; then
        COMPOSE_BIN+=(-f "${legacy_compose}")
    fi
fi
# The runtime tools are re-checked because a target config may have
# selected the runtime after the first pass.
assert_runtime_tools || exit 1
backup_runtime_assert_writers_stopped || exit 1
if backup_runtime_is_native; then
    # Native targets have no service table to inspect, so reachability is
    # proven by a real connection before anything destructive can start.
    probe="$(runtime_pg_query 'SELECT 1')" || die "restore target PostgreSQL is not reachable at the attested endpoint"
    probe="${probe//$'\r'/}"
    [[ "${probe}" == "1" ]] || die "restore target PostgreSQL did not answer the reachability probe"
else
    assert_compose_services_present
fi

if [[ "${LEGACY_V2}" == "1" ]]; then
    [[ "${CH_HOST}" == "localhost" || "${CH_HOST}" == "127.0.0.1" ]] \
        || die "database-level ClickHouse restore requires the local compose backup disk"
fi

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Authoritative Restore${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Backup: ${BACKUP_FILE}"
echo "  ID:     ${BACKUP_ID}"
echo "  Format: v${BACKUP_FORMAT_VERSION} (components: ${REQUIRED_COMPONENTS[*]})"
echo "  Runtime: ${BACKUP_RUNTIME} (PostgreSQL: $(backup_runtime_pg_client_mode), S3: $(backup_runtime_mc_client_mode))"
echo "  Target: ${TARGET}"
echo "  Preflight: all mandatory components and checksums valid"
echo ""

restore_incomplete() {
    local temp="${RESTORE_STATE_FILE}.tmp.$$"
    mkdir -p "${BAK_BASE_DIR}" || die "cannot create restore state directory"
    {
        printf 'target=%s\n' "${TARGET}"
        printf 'backup_id=%s\n' "${BACKUP_ID}"
        printf 'started_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "${temp}" || die "cannot write restore incomplete state"
    mv -f -- "${temp}" "${RESTORE_STATE_FILE}" \
        || die "cannot publish restore incomplete state"
}

if [[ "${IS_PROD}" == "1" ]]; then
    if [[ "${LEGACY_V2}" == "1" ]]; then
        echo -e "${RED}WARNING: production restore overwrites PostgreSQL, ClickHouse, and S3.${NC}"
    else
        echo -e "${RED}WARNING: production restore overwrites PostgreSQL and S3.${NC}"
    fi
    read -r -p "Type 'restore' to confirm production restore: " CONFIRM
    [[ "${CONFIRM}" == "restore" ]] || die "restore aborted"
else
    read -r -p "Restore over isolated target '${TARGET}'? [y/N]: " CONFIRM
    [[ "${CONFIRM}" == "y" || "${CONFIRM}" == "Y" ]] || die "restore aborted"
fi
restore_incomplete

compose_exec() {
    local service="$1"
    shift
    "${COMPOSE_BIN[@]}" exec -T "${service}" "$@"
}

pg_query() { runtime_pg_query "$1"; }

ch_query() {
    compose_exec clickhouse clickhouse-client --user "${CH_USER}" --database default -q "$1"
}

verify_restored_postgres_rows() {
    local table expected extra actual
    while IFS=$'\t' read -r table expected extra; do
        [[ -n "${table}${expected}${extra}" ]] || continue
        actual="$(pg_query "SELECT count(*) FROM ${table}")" \
            || die "PostgreSQL post-restore count failed for ${table}"
        actual="${actual//$'\r'/}"
        [[ "${actual}" == "${expected}" ]] \
            || die "PostgreSQL post-restore row mismatch for ${table}: expected ${expected}, got ${actual:-empty}"
    done < "${PG_ROWS_FILE}"
}

verify_restored_clickhouse_rows() {
    local table expected_rows expected_parts extra actual_rows actual_parts
    while IFS=$'\t' read -r table expected_rows expected_parts extra; do
        [[ -n "${table}${expected_rows}${expected_parts}${extra}" ]] || continue
        actual_rows="$(ch_query "SELECT count() FROM soymutdb.\`${table}\`")" \
            || die "ClickHouse post-restore count failed for ${table}"
        actual_parts="$(ch_query "SELECT count(DISTINCT partition) FROM system.parts WHERE database='soymutdb' AND table='${table}' AND active=1")" \
            || die "ClickHouse post-restore partition count failed for ${table}"
        actual_rows="${actual_rows//$'\r'/}"
        actual_parts="${actual_parts//$'\r'/}"
        [[ "${actual_rows}" == "${expected_rows}" && "${actual_parts}" == "${expected_parts}" ]] \
            || die "ClickHouse post-restore snapshot mismatch for ${table}"
    done < "${CH_ROWS_FILE}"
}

MC_CFG_DIR="${BAK_BASE_DIR}/.mc"
# The runtime library owns the mc routing: compose may fall back to the
# minio/mc image, native requires a real mc and never starts a container.
mc_run() { runtime_mc_run "$@"; }

echo -e "${CYAN}[1/3] Restoring PostgreSQL...${NC}"
if backup_runtime_pg_uses_compose; then
    # Only the compose runtime needs the dump staged inside the container; the
    # native runtime hands the host path to the host pg_restore.
    PG_CONTAINER_FILE="/tmp/soymutdb_restore_$$.dump"
    "${COMPOSE_BIN[@]}" cp "${PG_DUMP_FILE}" "postgres:${PG_CONTAINER_FILE}" \
        || die "copying PostgreSQL dump into the container failed"
    PG_DUMP_TARGET="${PG_CONTAINER_FILE}"
else
    PG_DUMP_TARGET="${PG_DUMP_FILE}"
fi
runtime_pg_dropdb || die "dropping the existing PostgreSQL database failed"
runtime_pg_createdb || die "creating a clean PostgreSQL database failed"
runtime_pg_restore_file "${PG_DUMP_TARGET}" || die "PostgreSQL restore failed"
if [[ -n "${PG_CONTAINER_FILE}" ]]; then
    compose_exec postgres rm -f "${PG_CONTAINER_FILE}" || die "PostgreSQL restore staging cleanup failed"
    PG_CONTAINER_FILE=""
fi
verify_restored_postgres_rows
info "PostgreSQL restore complete"

if [[ "${LEGACY_V2}" == "1" ]]; then
    echo -e "${CYAN}[2/3] Restoring ClickHouse database...${NC}"
    CH_CONTAINER_FILE="/var/lib/clickhouse-backups/soymutdb_restore_$$.zip"
    "${COMPOSE_BIN[@]}" cp "${CH_BACKUP_FILE}" "clickhouse:${CH_CONTAINER_FILE}" \
        || die "copying ClickHouse backup into the container failed"
    ch_query "DROP DATABASE IF EXISTS soymutdb SYNC" >/dev/null \
        || die "dropping the existing ClickHouse database failed"
    ch_query "RESTORE DATABASE soymutdb FROM Disk('backups', '$(basename "${CH_CONTAINER_FILE}")')" >/dev/null \
        || die "ClickHouse RESTORE DATABASE failed"
    compose_exec clickhouse rm -f "${CH_CONTAINER_FILE}" \
        || die "ClickHouse restore staging cleanup failed"
    CH_CONTAINER_FILE=""
    verify_restored_clickhouse_rows
    info "ClickHouse database restore complete"
    echo -e "${CYAN}[3/3] Restoring S3 buckets and policies...${NC}"
else
    echo -e "${CYAN}[2/2] Restoring S3 buckets and policies...${NC}"
fi
mkdir -p "${MC_CFG_DIR}"
mc_configure_alias_env s3dst "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" \
    || die "S3 destination alias environment configuration failed"
for bucket in "${S3_BUCKETS[@]}"; do
    source_dir="${RESTORE_SRC}/s3_data/${bucket}"
    mc_run mb --ignore-existing "s3dst/${bucket}" >/dev/null 2>&1 \
        || die "creating required destination bucket failed: ${bucket}"
    mc_run mirror --overwrite --remove "${source_dir}" "s3dst/${bucket}" >/dev/null 2>&1 \
        || die "restoring required S3 bucket failed: ${bucket}"
    runtime_restore_policy "${RESTORE_SRC}/s3_policy_${bucket}.json" "s3dst/${bucket}" >/dev/null 2>&1 \
        || die "restoring S3 bucket policy failed: ${bucket}"
done

CHECK_DIR="${RESTORE_DIR}/s3-check"
mkdir -p "${CHECK_DIR}"
for bucket in "${S3_BUCKETS[@]}"; do
    listing="${CHECK_DIR}/${bucket}.jsonl"
    mc_run ls --recursive --json "s3dst/${bucket}/" > "${listing}" 2>/dev/null \
        || die "listing restored S3 bucket failed: ${bucket}"
    read -r actual_count actual_bytes < <(python3 - "${listing}" <<'PY'
import json
import sys

count = 0
size = 0
with open(sys.argv[1], encoding="utf-8") as handle:
    for raw in handle:
        if not raw.strip():
            continue
        item = json.loads(raw)
        if item.get("type") == "folder":
            continue
        value = item.get("size")
        if not isinstance(value, int) or value < 0:
            raise SystemExit("invalid mc listing size")
        count += 1
        size += value
print(count, size)
PY
    )
    expected_count="$(awk -F'\t' -v wanted="${bucket}" '$1 == wanted { count++ } END { print count+0 }' "${S3_MANIFEST}")"
    expected_bytes="$(awk -F'\t' -v wanted="${bucket}" '$1 == wanted { total+=$3 } END { print total+0 }' "${S3_MANIFEST}")"
    [[ "${actual_count}" == "${expected_count}" && "${actual_bytes}" == "${expected_bytes}" ]] \
        || die "restored S3 object count/size mismatch: ${bucket}"
done

while IFS=$'\t' read -r bucket relative size hash extra; do
    [[ -n "${bucket}${relative}${size}${hash}${extra}" ]] || continue
    downloaded="${CHECK_DIR}/object"
    mc_run cp "s3dst/${bucket}/${relative}" "${downloaded}" >/dev/null 2>&1 \
        || die "restored S3 object is missing: ${bucket}/${relative}"
    [[ "$(stat -c%s "${downloaded}")" == "${size}" ]] \
        || die "restored S3 object size mismatch: ${bucket}/${relative}"
    [[ "$(sha256sum "${downloaded}" | awk '{print $1}')" == "${hash}" ]] \
        || die "restored S3 object checksum mismatch: ${bucket}/${relative}"
    rm -f -- "${downloaded}"
done < "${S3_MANIFEST}"
info "S3 restore and object verification complete"

rm -f -- "${RESTORE_STATE_FILE}" || die "could not clear restore incomplete state"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Restore Complete (target: ${TARGET}, runtime: ${BACKUP_RUNTIME})${NC}"
echo -e "${GREEN}========================================${NC}"
VERIFY_COMMAND=(bash deploy/scripts/verify-restore.sh)
[[ "${LEGACY_V2}" != "1" ]] || VERIFY_COMMAND+=(--allow-legacy-v2)
VERIFY_COMMAND+=(--runtime "${BACKUP_RUNTIME}")
[[ "${SOYMUTDB_BACKUP_REPO_ENV:-1}" != "0" ]] || VERIFY_COMMAND+=(--no-repo-env)
VERIFY_COMMAND+=("${BACKUP_FILE}")
echo "  With the restored target's POSTGRES_* and S3_* settings, run:"
printf '  '
printf '%q ' "${VERIFY_COMMAND[@]}"
printf '\n'
echo ""

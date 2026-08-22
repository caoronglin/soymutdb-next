#!/usr/bin/env bash
# =====================================================================
# SoyMutDB restore verification (authoritative format v2)
# =====================================================================
# Validates archive/component integrity, mandatory snapshot rows, restored
# PostgreSQL and ClickHouse counts, and every S3 bucket/object. S3 checks are
# skipped only by the explicit drill flags below; a skipped run is reported as
# such and is never labeled "all checks passed".
#
# Usage:
#   bash deploy/scripts/verify-restore.sh <backup.tar.gz>
#   bash deploy/scripts/verify-restore.sh --skip-s3 <backup.tar.gz>
#   bash deploy/scripts/verify-restore.sh --skip-s3-checksum <backup.tar.gz>
# =====================================================================
set -Eeuo pipefail
umask 077

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${GREEN}  $*${NC}"; }
warn() { echo -e "${YELLOW}  [WARN] $*${NC}"; }
err()  { echo -e "${RED}[ERROR] $*${NC}" >&2; }
die()  { err "$*"; exit 1; }

readonly REQUIRED_S3_BUCKETS="genomic-data user-tracks blast-dbs exports gwas analyses"

SKIP_S3=0
SKIP_S3_CHECKSUM=0
BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-s3) SKIP_S3=1; shift ;;
        --skip-s3-checksum) SKIP_S3_CHECKSUM=1; shift ;;
        --help|-h)
            sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    || die "Usage: bash deploy/scripts/verify-restore.sh [drill skip options] <backup.tar.gz>"
[[ -f "${BACKUP_FILE}" ]] || die "backup file not found: ${BACKUP_FILE}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=deploy/scripts/mc-auth.sh
source "${SCRIPT_DIR}/mc-auth.sh"
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
fi

INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
    COMPOSE_DIR="${INSTALL_DIR}"
else
    COMPOSE_DIR="${PROJECT_ROOT}"
fi
COMPOSE_BIN=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")

BAK_BASE_DIR="${BAK_BASE_DIR:-/opt/soymutdb/backups}"
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"
CH_HOST="${CLICKHOUSE_HOST:-localhost}"
CH_PORT="${CLICKHOUSE_PORT:-8123}"
CH_USER="${CLICKHOUSE_USER:-soymutdb}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-minioadmin}"
S3_SECRET_KEY="${S3_SECRET_KEY:-minioadmin}"

for tool in python3 sha256sum stat; do
    command -v "${tool}" >/dev/null 2>&1 || die "required tool is unavailable: ${tool}"
done

VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf -- "${VERIFY_DIR}"' EXIT

FAIL_COUNT=0
PASS_COUNT=0
SKIP_COUNT=0
check() {
    local description="$1" result="$2"
    if [[ "${result}" == "0" ]]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        info "PASS  ${description}"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        err "FAIL  ${description}"
    fi
}

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
    check "archive checksum" 0
}

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Restore Verification${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Backup: ${BACKUP_FILE}"
echo ""
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

python3 - "${BACKUP_FILE}" "${VERIFY_DIR}" <<'PY'
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

mapfile -t VERIFY_ROOTS < <(find "${VERIFY_DIR}" -mindepth 1 -maxdepth 1 -type d -print)
[[ ${#VERIFY_ROOTS[@]} -eq 1 ]] || die "backup archive has no unique content directory"
VERIFY_SRC="${VERIFY_ROOTS[0]}"
MANIFEST="${VERIFY_SRC}/manifest.json"
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

[[ "$(manifest_get format_version)" == "2" ]] \
    || die "unsupported manifest format_version (authoritative v2 required)"
[[ "$(manifest_get consistency.mode)" == "writers_quiesced" ]] \
    || die "backup consistency mode is not safe for authoritative verification"
BACKUP_ID="$(manifest_get backup_id)"
[[ "${BACKUP_ID}" == "${COMPLETE_BACKUP_ID}" ]] \
    || die "backup completion marker backup_id mismatch"
for component in postgres clickhouse s3; do
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
ARTIFACT_MANIFEST="${VERIFY_SRC}/${ARTIFACT_MANIFEST_REL}"
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
        path="${VERIFY_SRC}/${relative}"
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
check "all archived artifact checksums" 0
info "Manifest backup_id=${BACKUP_ID}"

PG_ROWS_REL="$(manifest_get components.postgres.row_counts_file)"
PG_TABLES_EXPECTED="$(manifest_get components.postgres.tables)"
CH_ROWS_REL="$(manifest_get components.clickhouse.row_counts_file)"
CH_TABLES_EXPECTED="$(manifest_get components.clickhouse.tables)"
S3_MANIFEST_REL="$(manifest_get components.s3.manifest_file)"
# manifest key: "buckets_file"
S3_BUCKETS_REL="$(manifest_get components.s3.buckets_file)"
S3_OBJECTS_EXPECTED="$(manifest_get components.s3.object_count)"
S3_BYTES_EXPECTED="$(manifest_get components.s3.total_bytes)"
S3_CHECKSUM_ALGORITHM="$(manifest_get components.s3.checksum_algorithm)"
for relative in "${PG_ROWS_REL}" "${CH_ROWS_REL}" "${S3_MANIFEST_REL}" "${S3_BUCKETS_REL}"; do
    validate_relative_path "${relative}" || die "manifest contains an unsafe component path"
done
[[ "${PG_TABLES_EXPECTED}" =~ ^[1-9][0-9]*$ && "${CH_TABLES_EXPECTED}" =~ ^[1-9][0-9]*$ ]] \
    || die "row snapshot table counts must be positive"
[[ "${S3_OBJECTS_EXPECTED}" =~ ^[0-9]+$ && "${S3_BYTES_EXPECTED}" =~ ^[0-9]+$ ]] \
    || die "S3 manifest totals are invalid"
[[ "${S3_CHECKSUM_ALGORITHM}" == "sha256" ]] || die "S3 object checksums must use sha256"

PG_ROWS_FILE="${VERIFY_SRC}/${PG_ROWS_REL}"
CH_ROWS_FILE="${VERIFY_SRC}/${CH_ROWS_REL}"
S3_MANIFEST="${VERIFY_SRC}/${S3_MANIFEST_REL}"
S3_BUCKETS_FILE="${VERIFY_SRC}/${S3_BUCKETS_REL}"

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
validate_ch_snapshot

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
    object="${VERIFY_SRC}/s3_data/${bucket}/${relative}"
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
    [[ -d "${VERIFY_SRC}/s3_data/${bucket}" ]] || die "S3 bucket data directory is missing: ${bucket}"
    [[ -s "${VERIFY_SRC}/s3_policy_${bucket}.json" ]] || die "S3 bucket policy is missing: ${bucket}"
done

compose_exec() {
    local service="$1"
    shift
    "${COMPOSE_BIN[@]}" exec -T "${service}" "$@"
}

pg_query() {
    local sql="$1"
    if [[ "${PG_HOST}" == "localhost" || "${PG_HOST}" == "127.0.0.1" ]]; then
        compose_exec postgres psql -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    else
        PGPASSWORD="${POSTGRES_PASSWORD:-soymutdb_dev_password}" \
            psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" -d "${PG_DB}" -At -c "${sql}"
    fi
}

ch_query() {
    local sql="$1"
    if [[ "${CH_HOST}" == "localhost" || "${CH_HOST}" == "127.0.0.1" ]]; then
        compose_exec clickhouse clickhouse-client --user "${CH_USER}" -q "${sql}"
    else
        curl -sf -u "${CH_USER}:${CLICKHOUSE_PASSWORD:-soymutdb_dev_password}" \
            "http://${CH_HOST}:${CH_PORT}/" --data-binary "${sql}"
    fi
}

MC_CFG_DIR="${BAK_BASE_DIR}/.mc"
mc_run() {
    local env_name
    local -a docker_env_args=()
    if command -v mc >/dev/null 2>&1; then
        mc --config-dir "${MC_CFG_DIR}" "$@"
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

echo -e "${CYAN}[1/3] PostgreSQL row counts...${NC}"
while IFS=$'\t' read -r table expected extra; do
    [[ -n "${table}" ]] || continue
    if actual="$(pg_query "SELECT count(*) FROM ${table}" 2>/dev/null)"; then
        actual="${actual//$'\r'/}"
        if [[ "${actual}" == "${expected}" ]]; then
            check "PostgreSQL ${table} rows=${expected}" 0
        else
            check "PostgreSQL ${table} row count (expected ${expected}, got ${actual:-empty})" 1
        fi
    else
        check "PostgreSQL ${table} row query" 1
    fi
done < "${PG_ROWS_FILE}"

echo -e "${CYAN}[2/3] ClickHouse rows and partitions...${NC}"
while IFS=$'\t' read -r table expected_rows expected_parts extra; do
    [[ -n "${table}" ]] || continue
    if actual_rows="$(ch_query "SELECT count() FROM soymutdb.\`${table}\`" 2>/dev/null)"; then
        actual_rows="${actual_rows//$'\r'/}"
        if [[ "${actual_rows}" == "${expected_rows}" ]]; then
            check "ClickHouse ${table} rows=${expected_rows}" 0
        else
            check "ClickHouse ${table} rows (expected ${expected_rows}, got ${actual_rows:-empty})" 1
        fi
    else
        check "ClickHouse ${table} row query" 1
    fi
    if actual_parts="$(ch_query "SELECT count(DISTINCT partition) FROM system.parts WHERE database='soymutdb' AND table='${table}' AND active=1" 2>/dev/null)"; then
        actual_parts="${actual_parts//$'\r'/}"
        if [[ "${actual_parts}" == "${expected_parts}" ]]; then
            check "ClickHouse ${table} partitions=${expected_parts}" 0
        else
            check "ClickHouse ${table} partitions (expected ${expected_parts}, got ${actual_parts:-empty})" 1
        fi
    else
        check "ClickHouse ${table} partition query" 1
    fi
done < "${CH_ROWS_FILE}"

echo -e "${CYAN}[3/3] S3 objects...${NC}"
if [[ "${SKIP_S3}" == "1" ]]; then
    SKIP_COUNT=$((SKIP_COUNT + 1))
    warn "EXPLICIT SKIP: S3 target verification was skipped (--skip-s3); use only for an isolated drill."
else
    mkdir -p "${MC_CFG_DIR}"
    if ! mc_configure_alias_env s3dst "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}"; then
        check "S3 destination alias environment is valid" 1
    else
        CHECK_DIR="${VERIFY_DIR}/s3-check"
        mkdir -p "${CHECK_DIR}"
        for bucket in "${S3_BUCKETS[@]}"; do
            listing="${CHECK_DIR}/${bucket}.jsonl"
            if ! mc_run ls --recursive --json "s3dst/${bucket}/" > "${listing}" 2>/dev/null; then
                check "S3 ${bucket} listing" 1
                continue
            fi
            if counts="$(python3 - "${listing}" <<'PY'
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
            )"; then
                read -r actual_count actual_bytes <<< "${counts}"
                expected_count="$(awk -F'\t' -v wanted="${bucket}" '$1 == wanted { count++ } END { print count+0 }' "${S3_MANIFEST}")"
                expected_bytes="$(awk -F'\t' -v wanted="${bucket}" '$1 == wanted { total+=$3 } END { print total+0 }' "${S3_MANIFEST}")"
                if [[ "${actual_count}" == "${expected_count}" ]]; then
                    check "S3 ${bucket} object count=${expected_count}" 0
                else
                    check "S3 ${bucket} object count (expected ${expected_count}, got ${actual_count})" 1
                fi
                if [[ "${actual_bytes}" == "${expected_bytes}" ]]; then
                    check "S3 ${bucket} bytes=${expected_bytes}" 0
                else
                    check "S3 ${bucket} bytes (expected ${expected_bytes}, got ${actual_bytes})" 1
                fi
            else
                check "S3 ${bucket} listing format" 1
            fi
        done

        if [[ "${SKIP_S3_CHECKSUM}" == "1" ]]; then
            SKIP_COUNT=$((SKIP_COUNT + 1))
            warn "EXPLICIT SKIP: target S3 object checksums were skipped (--skip-s3-checksum)."
        else
            while IFS=$'\t' read -r bucket relative size hash extra; do
                [[ -n "${bucket}${relative}${size}${hash}${extra}" ]] || continue
                downloaded="${CHECK_DIR}/object"
                if ! mc_run cp "s3dst/${bucket}/${relative}" "${downloaded}" >/dev/null 2>&1; then
                    check "S3 ${bucket}/${relative} exists" 1
                    continue
                fi
                actual_size="$(stat -c%s "${downloaded}")"
                actual_hash="$(sha256sum "${downloaded}" | awk '{print $1}')"
                if [[ "${actual_size}" == "${size}" ]]; then
                    check "S3 ${bucket}/${relative} size" 0
                else
                    check "S3 ${bucket}/${relative} size mismatch" 1
                fi
                if [[ "${actual_hash}" == "${hash}" ]]; then
                    check "S3 ${bucket}/${relative} checksum" 0
                else
                    check "S3 ${bucket}/${relative} checksum mismatch" 1
                fi
                rm -f -- "${downloaded}"
            done < "${S3_MANIFEST}"
        fi
    fi
fi

echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Verification Summary${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  PASS: ${PASS_COUNT}  FAIL: ${FAIL_COUNT}  EXPLICIT SKIP: ${SKIP_COUNT}"
if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    echo -e "${RED}  RESTORE VERIFICATION FAILED${NC}" >&2
    exit 1
fi
if [[ "${SKIP_COUNT}" -gt 0 ]]; then
    echo -e "${YELLOW}  PASSED WITH ${SKIP_COUNT} EXPLICIT SKIP(S); this is not a full verification.${NC}"
    exit 0
fi
echo -e "${GREEN}  ALL CHECKS PASSED.${NC}"

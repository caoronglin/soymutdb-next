#!/usr/bin/env bash
# =====================================================================
# SoyMutDB authoritative backup (format v3)
# =====================================================================
# Backs up the authoritative native PostgreSQL database and every authoritative
# S3 bucket. PostgreSQL replaced ClickHouse as the system of record, so the
# default topology has no ClickHouse component and a run that cannot cover
# every mandatory component fails instead of publishing a partial archive.
# A run is successful only after all components,
# manifests, checksums, the final archive, and any configured offsite copy
# have been verified. node-exporter textfile metrics are updated atomically.
#
# The runtime is explicit. SOYMUTDB_BACKUP_RUNTIME (or --runtime) selects
# compose (the default, unchanged behaviour) or native, which always uses the
# host PostgreSQL client tools and a host 'mc' binary and never falls back to a
# container. An unsupported value fails closed before any data is touched.
#
# Usage:
#   bash deploy/scripts/backup.sh
#   bash deploy/scripts/backup.sh --full   # compatibility alias
#   bash deploy/scripts/backup.sh --runtime native
#   bash deploy/scripts/backup.sh --no-repo-env --runtime native
#
# Important configuration:
#   SOYMUTDB_BACKUP_RUNTIME compose (default) | native
#   SOYMUTDB_BACKUP_REPO_ENV set to 0 to ignore the repository .env
#   SOYMUTDB_NATIVE_WRITES_STOPPED must be 1 in the native runtime, where the
#                                compose service table cannot be inspected
#   BAK_BASE_DIR          local archive root (/opt/soymutdb/backups)
#   BACKUP_METRICS_DIR    node-exporter textfile directory
#   BAK_S3_BUCKETS        bucket list; may add buckets but cannot omit required
#   BACKUP_S3             optional offsite alias/bucket/prefix
#   BACKUP_S3_ENDPOINT    endpoint when the offsite mc alias must be configured
#   BACKUP_S3_ACCESS_KEY / BACKUP_S3_SECRET_KEY
#   BACKUP_WRITES_QUIESCED must be 1 after API/workers/beat are stopped
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
die()  { err "$*"; return 1; }

usage() {
    sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=deploy/scripts/mc-auth.sh
source "${SCRIPT_DIR}/mc-auth.sh"
# shellcheck source=deploy/scripts/backup-runtime.sh
source "${SCRIPT_DIR}/backup-runtime.sh"

RUNTIME_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
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
        --help|-h) usage; exit 0 ;;
        --full)
            warn "--full is deprecated; authoritative backup is always full."
            shift
            ;;
        "") shift ;;
        *) die "unknown argument: $1"; exit 1 ;;
    esac
done

backup_runtime_load_repo_env "${PROJECT_ROOT}" || die "repository .env loading was rejected"
# Resolved before any directory, tool, or data access so an unsupported value
# or a rejected .env policy cannot start a partial run.
backup_runtime_require "${RUNTIME_ARG}" || exit 1

readonly REQUIRED_S3_BUCKETS="genomic-data user-tracks blast-dbs exports gwas analyses"
RUNTIME_RUNTIME_SUMMARY=""
readonly -a QUIESCED_WRITER_SERVICES=(api worker-default worker-analyses worker-blast worker-ingest beat)

COMPOSE_DIR=""
COMPOSE_BIN=()
if ! backup_runtime_is_native; then
    INSTALL_DIR="${SOYMUTDB_INSTALL_DIR:-/opt/soymutdb}"
    if [[ -f "${INSTALL_DIR}/docker-compose.yml" ]]; then
        COMPOSE_DIR="${INSTALL_DIR}"
    else
        COMPOSE_DIR="${PROJECT_ROOT}"
    fi
    COMPOSE_BIN=(docker compose --project-directory "${COMPOSE_DIR}" -f "${COMPOSE_DIR}/docker-compose.yml")
fi

BAK_BASE_DIR="${BAK_BASE_DIR:-/opt/soymutdb/backups}"
BACKUP_METRICS_DIR="${BACKUP_METRICS_DIR:-/var/lib/node_exporter/textfile_collector}"
BACKUP_S3="${BACKUP_S3:-}"
BACKUP_S3_ENDPOINT="${BACKUP_S3_ENDPOINT:-}"
BACKUP_S3_ACCESS_KEY="${BACKUP_S3_ACCESS_KEY:-}"
BACKUP_S3_SECRET_KEY="${BACKUP_S3_SECRET_KEY:-}"
BAK_S3_BUCKETS="${BAK_S3_BUCKETS:-${REQUIRED_S3_BUCKETS}}"
BAK_S3_HASH_OBJECTS="${BAK_S3_HASH_OBJECTS:-1}"
BAK_RETAIN_DAILY="${BAK_RETAIN_DAILY:-7}"
BAK_RETAIN_WEEKLY="${BAK_RETAIN_WEEKLY:-4}"
BAK_RETAIN_MONTHLY="${BAK_RETAIN_MONTHLY:-6}"
BACKUP_WRITES_QUIESCED="${BACKUP_WRITES_QUIESCED:-0}"

PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:-soymutdb}"
PG_DB="${POSTGRES_DB:-soymutdb}"
S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9001}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-${MINIO_ROOT_USER:-minioadmin}}"
S3_SECRET_KEY="${S3_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-minioadmin}}"

# Second resolution cannot order two runs that start inside the same second, and
# with identical source data they also produce the identical component hash, so
# the second run builds the same backup id and its own "refusing to overwrite"
# guard fires against archives the first run just published. Wait for the next
# whole second instead of inventing a suffix: the id stays parseable by
# prune_local's ^[0-9]{8}_[0-9]{6}$ retention regex and by operator scripts that
# read the timestamp, and the collision becomes impossible rather than merely
# unlikely.
unique_backup_timestamp() {
    local stamp
    stamp="$(date +%Y%m%d_%H%M%S)"
    # A run that is still in flight owns `.staging/<stamp>-<pid>`; a completed
    # run owns `<stamp>-<component hash>.tar.gz`. Either means this second is
    # already taken, so the next whole second is used instead.
    while compgen -G "${BAK_BASE_DIR}/.staging/${stamp}-*" >/dev/null 2>&1 \
        || compgen -G "${BAK_BASE_DIR}/${stamp}-*.tar.gz" >/dev/null 2>&1; do
        while [[ "$(date +%H%M%S)" == "${stamp#*_}" ]]; do
            sleep 0.05 2>/dev/null || sleep 1
        done
        stamp="$(date +%Y%m%d_%H%M%S)"
    done
    printf '%s\n' "${stamp}"
}

TIMESTAMP="$(unique_backup_timestamp)"
HOSTNAME_SHORT="$(hostname -s 2>/dev/null || printf unknown)"
STAGING_DIR=""
PARTIAL_ARCHIVE=""
PARTIAL_SHA_FILE=""
PARTIAL_MANIFEST_COPY=""
PARTIAL_COMPLETE_FILE=""
FINAL_ARCHIVE=""
FINAL_SHA_FILE=""
FINAL_MANIFEST_COPY=""
FINAL_COMPLETE_FILE=""
LOCAL_PUBLISH_STARTED=0
BACKUP_SUCCEEDED=0
REMOTE_STAGE_URI=""
REMOTE_STAGE_READY=0
REMOTE_PUBLISH_STARTED=0
declare -a REMOTE_CREATED_URIS=()

metric_value() {
    local metric="$1" file="${BACKUP_METRICS_DIR}/soymutdb_backup.prom"
    [[ -f "${file}" ]] || { printf '0\n'; return; }
    awk -v name="${metric}" '$1 == name && $2 ~ /^[0-9]+([.][0-9]+)?$/ { value=$2 } END { print value+0 }' "${file}"
}

write_backup_metric() {
    local status="$1" now previous_success previous_failure temp metric_file
    now="$(date +%s)"
    metric_file="${BACKUP_METRICS_DIR}/soymutdb_backup.prom"
    mkdir -p "${BACKUP_METRICS_DIR}" || return 1
    previous_success="$(metric_value soymutdb_backup_last_success_timestamp_seconds)"
    previous_failure="$(metric_value soymutdb_backup_last_failure_timestamp_seconds)"
    if [[ "${status}" == "1" ]]; then
        previous_success="${now}"
    else
        previous_failure="${now}"
    fi
    temp="$(mktemp "${BACKUP_METRICS_DIR}/.soymutdb_backup.prom.XXXXXX")" || return 1
    {
        printf '# HELP soymutdb_backup_status Last authoritative backup attempt status (1=success, 0=failure).\n'
        printf '# TYPE soymutdb_backup_status gauge\n'
        printf 'soymutdb_backup_status %s\n' "${status}"
        printf '# HELP soymutdb_backup_last_attempt_timestamp_seconds Unix time of the last backup attempt.\n'
        printf '# TYPE soymutdb_backup_last_attempt_timestamp_seconds gauge\n'
        printf 'soymutdb_backup_last_attempt_timestamp_seconds %s\n' "${now}"
        printf '# HELP soymutdb_backup_last_success_timestamp_seconds Unix time of the last successful backup.\n'
        printf '# TYPE soymutdb_backup_last_success_timestamp_seconds gauge\n'
        printf 'soymutdb_backup_last_success_timestamp_seconds %s\n' "${previous_success}"
        printf '# HELP soymutdb_backup_last_failure_timestamp_seconds Unix time of the last failed backup.\n'
        printf '# TYPE soymutdb_backup_last_failure_timestamp_seconds gauge\n'
        printf 'soymutdb_backup_last_failure_timestamp_seconds %s\n' "${previous_failure}"
    } > "${temp}" || { rm -f -- "${temp}"; return 1; }
    chmod 0644 "${temp}" || { rm -f -- "${temp}"; return 1; }
    mv -f -- "${temp}" "${metric_file}"
}

safe_remove_staging() {
    [[ -n "${STAGING_DIR}" ]] || return 0
    case "${STAGING_DIR}" in
        "${BAK_BASE_DIR}"/.staging/*) rm -rf -- "${STAGING_DIR}" ;;
        *) warn "refusing to remove unexpected staging path: ${STAGING_DIR}"; return 1 ;;
    esac
}

compose_exec() {
    local service="$1"
    shift
    "${COMPOSE_BIN[@]}" exec -T "${service}" "$@"
}

MC_CFG_DIR="${BAK_BASE_DIR}/.mc"
# The runtime library owns the mc routing: compose may fall back to the
# minio/mc image, native requires a real mc and never starts a container.
mc_run() { runtime_mc_run "$@"; }

cleanup_run_artifacts() {
    local uri
    safe_remove_staging || true
    [[ -z "${PARTIAL_ARCHIVE}" ]] || rm -f -- "${PARTIAL_ARCHIVE}"
    [[ -z "${PARTIAL_SHA_FILE}" ]] || rm -f -- "${PARTIAL_SHA_FILE}"
    [[ -z "${PARTIAL_MANIFEST_COPY}" ]] || rm -f -- "${PARTIAL_MANIFEST_COPY}"
    [[ -z "${PARTIAL_COMPLETE_FILE}" ]] || rm -f -- "${PARTIAL_COMPLETE_FILE}"
    if [[ "${LOCAL_PUBLISH_STARTED}" == "1" ]]; then
        [[ -z "${FINAL_ARCHIVE}" ]] || rm -f -- "${FINAL_ARCHIVE}"
        [[ -z "${FINAL_SHA_FILE}" ]] || rm -f -- "${FINAL_SHA_FILE}"
        [[ -z "${FINAL_MANIFEST_COPY}" ]] || rm -f -- "${FINAL_MANIFEST_COPY}"
        [[ -z "${FINAL_COMPLETE_FILE}" ]] || rm -f -- "${FINAL_COMPLETE_FILE}"
    fi
    if [[ -n "${REMOTE_STAGE_URI}" ]]; then
        mc_run rm --recursive --force "${REMOTE_STAGE_URI}" >/dev/null 2>&1 \
            || warn "could not remove the current offsite staging prefix"
    fi
    if [[ "${REMOTE_PUBLISH_STARTED}" == "1" ]]; then
        for uri in "${REMOTE_CREATED_URIS[@]}"; do
            mc_run rm --force "${uri}" >/dev/null 2>&1 \
                || warn "could not remove incomplete current-run offsite object: ${uri}"
        done
    fi
}

on_exit() {
    local rc="$1"
    trap - EXIT
    if [[ "${rc}" -ne 0 || "${BACKUP_SUCCEEDED}" != "1" ]]; then
        set +e
        cleanup_run_artifacts
        if ! write_backup_metric "0"; then
            err "backup failed and the failure metric could not be written atomically"
        fi
        [[ "${rc}" -ne 0 ]] || rc=1
    fi
    exit "${rc}"
}
trap 'on_exit "$?"' EXIT

RUNTIME_RUNTIME_SUMMARY="PostgreSQL: $(backup_runtime_pg_client_mode), S3: $(backup_runtime_mc_client_mode), writers: $(backup_runtime_writers_attestation)"

mkdir -p "${BAK_BASE_DIR}" "${BACKUP_METRICS_DIR}" "${MC_CFG_DIR}" \
    || die "cannot create backup or metric directories"

for variable in BAK_RETAIN_DAILY BAK_RETAIN_WEEKLY BAK_RETAIN_MONTHLY; do
    [[ "${!variable}" =~ ^[1-9][0-9]*$ ]] \
        || die "${variable} must be a positive integer (got '${!variable}')"
done
[[ "${BAK_S3_HASH_OBJECTS}" == "1" ]] \
    || die "BAK_S3_HASH_OBJECTS must remain 1 for authoritative backups"

read -r -a S3_BUCKETS <<< "${BAK_S3_BUCKETS}"
read -r -a REQUIRED_BUCKET_ARRAY <<< "${REQUIRED_S3_BUCKETS}"
[[ ${#S3_BUCKETS[@]} -gt 0 ]] || die "BAK_S3_BUCKETS cannot be empty"
declare -A SEEN_BUCKETS=()
for bucket in "${S3_BUCKETS[@]}"; do
    [[ "${bucket}" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]] \
        || die "invalid S3 bucket name: ${bucket}"
    [[ -z "${SEEN_BUCKETS[${bucket}]:-}" ]] || die "duplicate S3 bucket: ${bucket}"
    SEEN_BUCKETS["${bucket}"]=1
done
for bucket in "${REQUIRED_BUCKET_ARRAY[@]}"; do
    [[ -n "${SEEN_BUCKETS[${bucket}]:-}" ]] \
        || die "required S3 bucket missing from BAK_S3_BUCKETS: ${bucket}"
done

# The compose runtime keeps exactly the tool set it always required; the
# native runtime adds the host PostgreSQL clients it now calls directly.
RUNTIME_PG_TOOLS=()
if backup_runtime_is_native; then
    RUNTIME_PG_TOOLS=(psql pg_dump)
fi
backup_runtime_assert_tools sha256sum tar stat find sort grep python3 \
    "${RUNTIME_PG_TOOLS[@]}" || exit 1
# A missing mc is fatal in the native runtime and never a container fallback.
backup_runtime_assert_mc || exit 1

# Compose runtime: the writer services must be observably stopped. Native
# runtime: the service table is unavailable, so the runtime library requires an
# explicit operator attestation and a live pg_stat_activity probe instead.
# Neither path degrades to an unconditional skip.
assert_writers_stopped() {
    local service running
    [[ "${BACKUP_WRITES_QUIESCED}" == "1" ]] \
        || { die "BACKUP_WRITES_QUIESCED=1 is required after stopping all writers"; return 1; }
    backup_runtime_is_native && return 0
    for service in "${QUIESCED_WRITER_SERVICES[@]}"; do
        if ! running="$("${COMPOSE_BIN[@]}" ps --status running -q "${service}" 2>/dev/null)"; then
            die "could not verify writer state for compose service: ${service}"
            return 1
        fi
        if [[ -n "${running}" ]]; then
            die "writer service must be stopped before backup: ${service}"
            return 1
        fi
    done
}
backup_runtime_assert_writers_stopped || exit 1

STAGING_DIR="${BAK_BASE_DIR}/.staging/${TIMESTAMP}-$$"
mkdir -p "${STAGING_DIR}"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  SoyMutDB Authoritative Backup${NC}"
echo -e "${CYAN}========================================${NC}"
echo "  Runtime:    ${BACKUP_RUNTIME} (${RUNTIME_RUNTIME_SUMMARY})"
echo "  Host:       ${HOSTNAME_SHORT}"
echo "  Staging:    ${STAGING_DIR}"
echo "  S3 buckets: ${S3_BUCKETS[*]}"
echo "  Offsite:    ${BACKUP_S3:-not configured}"
echo ""

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

pg_query() { runtime_pg_query "$1"; }

echo -e "${CYAN}[1/3] PostgreSQL...${NC}"
PG_TABLE_LIST="${STAGING_DIR}/pg_tables.list"
PG_ROWS_TSV="${STAGING_DIR}/pg_rows.tsv"
if ! pg_query "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1" > "${PG_TABLE_LIST}"; then
    die "PostgreSQL table discovery failed"
fi
[[ -s "${PG_TABLE_LIST}" ]] || die "PostgreSQL row snapshot would be empty"
: > "${PG_ROWS_TSV}"
while IFS= read -r table; do
    [[ -n "${table}" ]] || die "PostgreSQL table discovery returned an empty name"
    [[ "${table}" =~ ^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$ ]] \
        || die "PostgreSQL row snapshot table identifier is unsafe: ${table}"
    count="$(pg_query "SELECT count(*) FROM ${table}")" \
        || die "PostgreSQL row snapshot failed for ${table}"
    count="${count//$'\r'/}"
    [[ "${count}" =~ ^[0-9]+$ ]] \
        || die "PostgreSQL row snapshot is invalid for ${table}: ${count:-empty}"
    printf '%s\t%s\n' "${table}" "${count}" >> "${PG_ROWS_TSV}"
done < "${PG_TABLE_LIST}"
rm -f -- "${PG_TABLE_LIST}"
PG_TABLES_SNAPSHOTED="$(wc -l < "${PG_ROWS_TSV}" | tr -d ' ')"
[[ "${PG_TABLES_SNAPSHOTED}" -gt 0 ]] || die "PostgreSQL row snapshot is empty"

PG_DUMP_FILE="${STAGING_DIR}/postgres.dump"
if ! runtime_pg_dump_to "${PG_DUMP_FILE}"; then
    die "PostgreSQL pg_dump failed"
fi
[[ -s "${PG_DUMP_FILE}" ]] || die "PostgreSQL pg_dump produced an empty file"
PG_SIZE="$(stat -c%s "${PG_DUMP_FILE}")"
PG_SHA="$(sha256_of "${PG_DUMP_FILE}")"
info "PostgreSQL: ${PG_TABLES_SNAPSHOTED} tables, ${PG_SIZE} bytes"

echo -e "${CYAN}[2/3] S3 object data and policies...${NC}"
S3_BUCKETS_FILE="${STAGING_DIR}/s3_buckets.txt"
S3_MANIFEST_TSV="${STAGING_DIR}/s3_manifest.tsv"
printf '%s\n' "${S3_BUCKETS[@]}" > "${S3_BUCKETS_FILE}"
: > "${S3_MANIFEST_TSV}"
S3_OBJECT_COUNT=0
S3_TOTAL_BYTES=0
mc_configure_alias_env s3src "${S3_ENDPOINT}" "${S3_ACCESS_KEY}" "${S3_SECRET_KEY}" \
    || die "configuring the source S3 alias environment failed"
for bucket in "${S3_BUCKETS[@]}"; do
    local_bucket_dir="${STAGING_DIR}/s3_data/${bucket}"
    mkdir -p "${local_bucket_dir}"
    mc_run mirror --overwrite --remove "s3src/${bucket}" "${local_bucket_dir}" >/dev/null 2>&1 \
        || die "required S3 bucket mirror failed: ${bucket}"

    policy_file="${STAGING_DIR}/s3_policy_${bucket}.json"
    policy_temp="${policy_file}.partial"
    mc_run anonymous get-json "s3src/${bucket}" > "${policy_temp}" 2>/dev/null \
        || die "S3 bucket policy export failed: ${bucket}"
    [[ -s "${policy_temp}" ]] || die "S3 bucket policy export is empty: ${bucket}"
    python3 -m json.tool "${policy_temp}" >/dev/null \
        || die "S3 bucket policy export is invalid JSON: ${bucket}"
    mv -f -- "${policy_temp}" "${policy_file}"

    object_list="${STAGING_DIR}/.objects-${bucket}.partial"
    if ! find "${local_bucket_dir}" -type f -print0 > "${object_list}"; then
        die "S3 object enumeration failed: ${bucket}"
    fi
    while IFS= read -r -d '' object; do
        relative="${object#"${local_bucket_dir}"/}"
        if [[ "${relative}" == *$'\t'* || "${relative}" == *$'\n'* || "${relative}" == *$'\r'* ]]; then
            die "S3 object key cannot be represented safely in the manifest: ${bucket}"
        fi
        size="$(stat -c%s "${object}")"
        hash="$(sha256_of "${object}")"
        printf '%s\t%s\t%s\t%s\n' "${bucket}" "${relative}" "${size}" "${hash}" \
            >> "${S3_MANIFEST_TSV}"
        S3_OBJECT_COUNT=$((S3_OBJECT_COUNT + 1))
        S3_TOTAL_BYTES=$((S3_TOTAL_BYTES + size))
    done < "${object_list}"
    rm -f -- "${object_list}"
done
LC_ALL=C sort -o "${S3_MANIFEST_TSV}" "${S3_MANIFEST_TSV}"
info "S3: ${S3_OBJECT_COUNT} objects, ${S3_TOTAL_BYTES} bytes"

ARTIFACT_MANIFEST="${STAGING_DIR}/artifact_checksums.tsv"
ARTIFACT_MANIFEST_TEMP="${ARTIFACT_MANIFEST}.partial"
ARTIFACT_LIST="${STAGING_DIR}/.artifact-files.partial"
: > "${ARTIFACT_MANIFEST_TEMP}"
if ! find "${STAGING_DIR}" -type f \
    ! -name manifest.json \
    ! -name artifact_checksums.tsv.partial \
    ! -name .artifact-files.partial \
    -print0 > "${ARTIFACT_LIST}"; then
    die "artifact enumeration failed"
fi
while IFS= read -r -d '' artifact; do
    relative="${artifact#"${STAGING_DIR}"/}"
    [[ "${relative}" != "artifact_checksums.tsv.partial" ]] || continue
    if [[ "${relative}" == *$'\t'* || "${relative}" == *$'\n'* || "${relative}" == *$'\r'* ]]; then
        die "artifact path cannot be represented safely in checksum manifest"
    fi
    printf '%s\t%s\t%s\n' "$(sha256_of "${artifact}")" "$(stat -c%s "${artifact}")" "${relative}" \
        >> "${ARTIFACT_MANIFEST_TEMP}"
done < "${ARTIFACT_LIST}"
rm -f -- "${ARTIFACT_LIST}"
LC_ALL=C sort -o "${ARTIFACT_MANIFEST_TEMP}" "${ARTIFACT_MANIFEST_TEMP}"
[[ -s "${ARTIFACT_MANIFEST_TEMP}" ]] || die "artifact checksum manifest is empty"
mv -f -- "${ARTIFACT_MANIFEST_TEMP}" "${ARTIFACT_MANIFEST}"
ARTIFACT_MANIFEST_SIZE="$(stat -c%s "${ARTIFACT_MANIFEST}")"
ARTIFACT_MANIFEST_SHA="$(sha256_of "${ARTIFACT_MANIFEST}")"

S3_MANIFEST_SHA="$(sha256_of "${S3_MANIFEST_TSV}")"
COMPONENT_HASH="$(printf '%s%s' "${PG_SHA}" "${S3_MANIFEST_SHA}" | sha256sum | cut -c1-8)"
BACKUP_ID="${TIMESTAMP}-${COMPONENT_HASH}"
ARCHIVE_NAME="${BACKUP_ID}.tar.gz"
MANIFEST_FILE="${STAGING_DIR}/manifest.json"
MANIFEST_TEMP="${MANIFEST_FILE}.partial"
python3 - "${MANIFEST_TEMP}" "${BACKUP_ID}" "${HOSTNAME_SHORT}" \
    "${PG_SIZE}" "${PG_TABLES_SNAPSHOTED}" \
    "${S3_OBJECT_COUNT}" "${S3_TOTAL_BYTES}" "${ARTIFACT_MANIFEST_SIZE}" \
    "${ARTIFACT_MANIFEST_SHA}" "${BACKUP_RUNTIME}" \
    "$(backup_runtime_pg_client_mode)" "$(backup_runtime_mc_client_mode)" \
    "$(backup_runtime_writers_attestation)" <<'PY'
import datetime
import json
import sys

(
    output,
    backup_id,
    hostname,
    pg_size,
    pg_tables,
    s3_objects,
    s3_bytes,
    artifact_size,
    artifact_sha,
    runtime_mode,
    pg_client,
    s3_client,
    writers_attestation,
) = sys.argv[1:]
manifest = {
    "format_version": 3,
    "backup_id": backup_id,
    "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "host": hostname,
    "tool": "deploy/scripts/backup.sh authoritative-v3",
    "consistency": {
        "mode": "writers_quiesced",
        "scope": "postgres_s3_current_versions",
    },
    "runtime": {
        "mode": runtime_mode,
        "postgres_client": pg_client,
        "s3_client": s3_client,
        "writers_attestation": writers_attestation,
    },
    "components": {
        "postgres": {
            "status": "ok",
            "file": "postgres.dump",
            "row_counts_file": "pg_rows.tsv",
            "size": int(pg_size),
            "tables": int(pg_tables),
        },
        "s3": {
            "status": "ok",
            "manifest_file": "s3_manifest.tsv",
            "buckets_file": "s3_buckets.txt",
            "object_count": int(s3_objects),
            "total_bytes": int(s3_bytes),
            "checksum_algorithm": "sha256",
        },
    },
    "artifact_manifest": {
        "file": "artifact_checksums.tsv",
        "size": int(artifact_size),
        "sha256": artifact_sha,
    },
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
[[ -s "${MANIFEST_TEMP}" ]] || die "manifest generation failed"
mv -f -- "${MANIFEST_TEMP}" "${MANIFEST_FILE}"

PARTIAL_ARCHIVE="${BAK_BASE_DIR}/.staging/${ARCHIVE_NAME}.partial"
PARTIAL_SHA_FILE="${BAK_BASE_DIR}/.staging/${ARCHIVE_NAME}.sha256.partial"
PARTIAL_MANIFEST_COPY="${BAK_BASE_DIR}/.staging/${BACKUP_ID}.manifest.json.partial"
PARTIAL_COMPLETE_FILE="${BAK_BASE_DIR}/.staging/${ARCHIVE_NAME}.complete.partial"
FINAL_ARCHIVE="${BAK_BASE_DIR}/${ARCHIVE_NAME}"
FINAL_SHA_FILE="${FINAL_ARCHIVE}.sha256"
FINAL_MANIFEST_COPY="${BAK_BASE_DIR}/${BACKUP_ID}.manifest.json"
FINAL_COMPLETE_FILE="${FINAL_ARCHIVE}.complete"

echo -e "${CYAN}[3/3] Packaging, verifying, and publishing archive...${NC}"
tar -C "$(dirname "${STAGING_DIR}")" -czf "${PARTIAL_ARCHIVE}" "$(basename "${STAGING_DIR}")" \
    || die "archive creation failed"
ARCHIVE_SHA="$(sha256_of "${PARTIAL_ARCHIVE}")"
printf '%s  %s\n' "${ARCHIVE_SHA}" "${ARCHIVE_NAME}" > "${PARTIAL_SHA_FILE}" \
    || die "archive checksum sidecar generation failed"
cp -- "${MANIFEST_FILE}" "${PARTIAL_MANIFEST_COPY}" \
    || die "standalone manifest generation failed"

verify_local_archive() {
    local archive="$1" expected_sha="$2"
    [[ -s "${archive}" ]] || die "final archive is missing or empty"
    tar -tzf "${archive}" >/dev/null || die "final archive cannot be read"
    [[ "$(sha256_of "${archive}")" == "${expected_sha}" ]] \
        || die "final archive checksum mismatch"
}
verify_local_archive "${PARTIAL_ARCHIVE}" "${ARCHIVE_SHA}"

S3_ALIAS=""
S3_TARGET=""
upload_offsite_backup() {
    [[ "${BACKUP_S3}" == */* ]] || die "BACKUP_S3 must be alias/bucket[/prefix]"
    S3_ALIAS="${BACKUP_S3%%/*}"
    S3_TARGET="${BACKUP_S3#*/}"
    S3_TARGET="${S3_TARGET%/}"
    [[ -n "${S3_ALIAS}" && -n "${S3_TARGET}" ]] || die "BACKUP_S3 is incomplete"
    if [[ -n "${BACKUP_S3_ENDPOINT}" ]]; then
        [[ -n "${BACKUP_S3_ACCESS_KEY}" && -n "${BACKUP_S3_SECRET_KEY}" ]] \
            || die "offsite endpoint requires access and secret keys"
        mc_configure_alias_env "${S3_ALIAS}" "${BACKUP_S3_ENDPOINT}" \
            "${BACKUP_S3_ACCESS_KEY}" "${BACKUP_S3_SECRET_KEY}" \
            || die "configuring the offsite S3 alias environment failed"
    fi
    offsite_bucket="${S3_TARGET%%/*}"
    mc_run ls "${S3_ALIAS}/${offsite_bucket}" >/dev/null 2>&1 \
        || die "offsite backup bucket is not reachable"
    REMOTE_STAGE_URI="${S3_ALIAS}/${S3_TARGET}/.staging/${BACKUP_ID}"
    mc_run cp "${PARTIAL_ARCHIVE}" "${REMOTE_STAGE_URI}/${ARCHIVE_NAME}" >/dev/null 2>&1 \
        || die "offsite archive upload failed"
    mc_run cp "${PARTIAL_SHA_FILE}" "${REMOTE_STAGE_URI}/${ARCHIVE_NAME}.sha256" >/dev/null 2>&1 \
        || die "offsite checksum upload failed"
    mc_run cp "${PARTIAL_MANIFEST_COPY}" "${REMOTE_STAGE_URI}/${BACKUP_ID}.manifest.json" >/dev/null 2>&1 \
        || die "offsite manifest upload failed"
    remote_sha="$(mc_run cat "${REMOTE_STAGE_URI}/${ARCHIVE_NAME}" | sha256sum | awk '{print $1}')" \
        || die "offsite archive verification failed"
    [[ "${remote_sha}" == "${ARCHIVE_SHA}" ]] || die "offsite archive checksum mismatch"
    REMOTE_STAGE_READY=1
}

if [[ -n "${BACKUP_S3}" ]]; then
    upload_offsite_backup
fi

publish_local_artifacts() {
    local target
    for target in "${FINAL_ARCHIVE}" "${FINAL_SHA_FILE}" "${FINAL_MANIFEST_COPY}" \
        "${FINAL_COMPLETE_FILE}"; do
        [[ ! -e "${target}" ]] || die "refusing to overwrite existing backup artifact: ${target}"
    done
    LOCAL_PUBLISH_STARTED=1
    mv -- "${PARTIAL_MANIFEST_COPY}" "${FINAL_MANIFEST_COPY}"
    mv -- "${PARTIAL_SHA_FILE}" "${FINAL_SHA_FILE}"
    mv -- "${PARTIAL_ARCHIVE}" "${FINAL_ARCHIVE}"
}

assert_remote_target_absent() {
    local uri="$1" probe="${STAGING_DIR}/remote-stat-probe.log"
    if mc_run stat "${uri}" > "${probe}" 2>&1; then
        rm -f -- "${probe}"
        die "refusing to overwrite existing offsite artifact: ${uri}"
    fi
    if ! grep -Eiq 'not found|does not exist|no such|NoSuchKey' "${probe}"; then
        rm -f -- "${probe}"
        die "could not prove offsite target is absent: ${uri}"
    fi
    rm -f -- "${probe}"
}

publish_offsite_backup() {
    local remote_archive remote_sha remote_manifest remote_complete candidate marker published_sha
    [[ "${REMOTE_STAGE_READY}" == "1" ]] || die "offsite staging upload was not verified"
    remote_archive="${S3_ALIAS}/${S3_TARGET}/${ARCHIVE_NAME}"
    remote_sha="${remote_archive}.sha256"
    remote_manifest="${S3_ALIAS}/${S3_TARGET}/${BACKUP_ID}.manifest.json"
    remote_complete="${remote_archive}.complete"
    for candidate in "${remote_archive}" "${remote_sha}" "${remote_manifest}" "${remote_complete}"; do
        assert_remote_target_absent "${candidate}"
    done
    REMOTE_PUBLISH_STARTED=1
    REMOTE_CREATED_URIS+=("${remote_archive}")
    mc_run cp "${REMOTE_STAGE_URI}/${ARCHIVE_NAME}" "${remote_archive}" >/dev/null 2>&1 \
        || die "offsite archive publication failed"
    REMOTE_CREATED_URIS+=("${remote_sha}")
    mc_run cp "${REMOTE_STAGE_URI}/${ARCHIVE_NAME}.sha256" "${remote_sha}" >/dev/null 2>&1 \
        || die "offsite checksum publication failed"
    REMOTE_CREATED_URIS+=("${remote_manifest}")
    mc_run cp "${REMOTE_STAGE_URI}/${BACKUP_ID}.manifest.json" "${remote_manifest}" >/dev/null 2>&1 \
        || die "offsite manifest publication failed"
    published_sha="$(mc_run cat "${remote_archive}" | sha256sum | awk '{print $1}')" \
        || die "published offsite archive verification failed"
    [[ "${published_sha}" == "${ARCHIVE_SHA}" ]] || die "published offsite archive checksum mismatch"
    marker="${STAGING_DIR}/offsite.complete"
    printf 'backup_id=%s\nsha256=%s\n' "${BACKUP_ID}" "${ARCHIVE_SHA}" > "${marker}"
    REMOTE_CREATED_URIS+=("${remote_complete}")
    mc_run cp "${marker}" "${remote_complete}" >/dev/null 2>&1 \
        || die "offsite completion marker publication failed"
    mc_run rm --recursive --force "${REMOTE_STAGE_URI}" >/dev/null 2>&1 \
        || die "offsite staging cleanup failed"
    REMOTE_STAGE_URI=""
}

if [[ -n "${BACKUP_S3}" ]]; then
    publish_offsite_backup
fi

publish_local_artifacts
verify_local_archive "${FINAL_ARCHIVE}" "${ARCHIVE_SHA}"
(cd "${BAK_BASE_DIR}" && sha256sum -c "$(basename "${FINAL_SHA_FILE}")" >/dev/null) \
    || die "published archive sidecar verification failed"

safe_remove_staging || die "local staging cleanup failed"
STAGING_DIR=""

prune_local() {
    local dir="$1" now_epoch keep_days index name timestamp day week month newest
    local -a names=()
    local -A keep=()
    local path
    now_epoch="$(date +%s)"
    keep_days=$(((BAK_RETAIN_DAILY - 1) * 86400))
    for path in "${dir}"/*.tar.gz; do
        [[ -e "${path}" ]] || continue
        names+=("$(basename "${path}")")
    done
    for name in "${names[@]}"; do
        if [[ ! -f "${dir}/${name}.complete" ]]; then
            keep["${name}"]="no-complete-marker"
            continue
        fi
        timestamp="${name%.tar.gz}"
        timestamp="${timestamp%%-*}"
        if [[ ! "${timestamp}" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
            keep["${name}"]="unrecognized"
            continue
        fi
        day="${timestamp:0:8}"
        if [[ "$(date -d "${day}" +%s)" -ge $((now_epoch - keep_days)) ]]; then
            keep["${name}"]="daily"
        fi
    done
    for ((index = 0; index < BAK_RETAIN_WEEKLY; index++)); do
        week="$(date -d "now - ${index} weeks" +%G-%V)"
        newest=""
        for name in "${names[@]}"; do
            timestamp="${name%.tar.gz}"
            timestamp="${timestamp%%-*}"
            [[ "${timestamp}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || continue
            day="${timestamp:0:8}"
            [[ "$(date -d "${day}" +%G-%V)" == "${week}" ]] || continue
            [[ -n "${newest}" && "${timestamp}" < "${newest%%-*}" ]] || newest="${name}"
        done
        [[ -z "${newest}" ]] || keep["${newest}"]="weekly"
    done
    for ((index = 0; index < BAK_RETAIN_MONTHLY; index++)); do
        month="$(date -d "now - ${index} months" +%Y%m)"
        newest=""
        for name in "${names[@]}"; do
            timestamp="${name%.tar.gz}"
            timestamp="${timestamp%%-*}"
            [[ "${timestamp}" =~ ^[0-9]{8}_[0-9]{6}$ ]] || continue
            [[ "${timestamp:0:6}" == "${month}" ]] || continue
            [[ -n "${newest}" && "${timestamp}" < "${newest%%-*}" ]] || newest="${name}"
        done
        [[ -z "${newest}" ]] || keep["${newest}"]="monthly"
    done
    for name in "${names[@]}"; do
        [[ -n "${keep[${name}]:-}" ]] && continue
        if ! rm -f -- "${dir}/${name}" "${dir}/${name}.sha256" \
            "${dir}/${name%.tar.gz}.manifest.json" "${dir}/${name}.complete"; then
            warn "retention could not remove ${name}"
        fi
    done
}
prune_local "${BAK_BASE_DIR}"

write_completion_marker() {
    printf 'backup_id=%s\nsha256=%s\n' "${BACKUP_ID}" "${ARCHIVE_SHA}" \
        > "${PARTIAL_COMPLETE_FILE}" \
        || die "local completion marker generation failed"
    mv -- "${PARTIAL_COMPLETE_FILE}" "${FINAL_COMPLETE_FILE}" \
        || die "local completion marker publication failed"
}
write_completion_marker
write_backup_metric "1" || die "success metric could not be written atomically"
BACKUP_SUCCEEDED=1
BACKUP_SIZE="$(du -sh "${FINAL_ARCHIVE}" | cut -f1)"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Backup Complete${NC}"
echo -e "${GREEN}========================================${NC}"
echo "  Archive:  ${FINAL_ARCHIVE}"
echo "  Runtime:  ${BACKUP_RUNTIME} (PostgreSQL: $(backup_runtime_pg_client_mode), S3: $(backup_runtime_mc_client_mode), writers: $(backup_runtime_writers_attestation))"
echo "  Size:     ${BACKUP_SIZE}"
echo "  SHA-256:  ${ARCHIVE_SHA}"
echo "  Manifest: ${FINAL_MANIFEST_COPY}"
echo "  Commit:   ${FINAL_COMPLETE_FILE}"
if [[ -n "${BACKUP_S3}" ]]; then
    echo "  Offsite:  ${BACKUP_S3}/${ARCHIVE_NAME} (.complete marker present)"
else
    echo "  Offsite:  not configured (local backup only)"
fi
echo ""

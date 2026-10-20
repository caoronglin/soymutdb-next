# Disaster Recovery Operations

Authoritative format-v3 backups include PostgreSQL (including native variant facts and analytics) and these S3 buckets: `genomic-data`, `user-tracks`, `blast-dbs`, `exports`, `gwas`, and `analyses`. Extra buckets may be configured, but required buckets cannot be removed. Redis is disposable and is not authoritative recovery data.

> Local evidence: [2026-10-17 native validation](../dev/native-validation-20261017.md) covers real PostgreSQL and six S3 buckets restored to independent targets, including a deliberately changed bucket policy. It does not attest production or offsite recovery.

## Monitoring and Alert Delivery Setup

Create the host textfile directory and an Alertmanager receiver secret before updating the monitoring services:

```bash
sudo install -d -m 0755 /var/lib/node_exporter/textfile_collector
sudo install -d -m 0700 /etc/soymutdb/secrets
sudo install -m 0600 /dev/null /etc/soymutdb/secrets/alertmanager_webhook_url
# Write exactly one organization-approved HTTPS webhook URL to that file.
export ALERTMANAGER_WEBHOOK_URL_FILE=/etc/soymutdb/secrets/alertmanager_webhook_url
docker compose up -d alertmanager prometheus node-exporter
```

Alert delivery is available only when the secret contains a valid HTTPS receiver, Alertmanager passes its startup/configuration checks, and the receiver accepts notifications. Prometheus starts independently so it can still record `AlertmanagerUnavailable`; a missing receiver remains a failed delivery path. Check `/-/healthy`, `up{job="alertmanager"}`, and `alertmanager_notifications_failed_total` after deployment.

## Runtime Selection (Compose and Native)

`deploy/scripts/backup-runtime.sh` owns the runtime routing for all three
scripts. The runtime is explicit and defaults to `compose`, which behaves
exactly as before. `native` is the only way to run without Docker, and it is
the correct choice for a host deployment whose PostgreSQL and MinIO are not
managed by Compose.

| Value | PostgreSQL | S3 | Writers quiescence proof |
| --- | --- | --- | --- |
| `compose` (default) | loopback host goes through the compose `postgres` service | host `mc`, or the `minio/mc` image when `mc` is absent | compose service table shows every writer stopped |
| `native` | host `psql` / `pg_dump` / `pg_restore` / `dropdb` / `createdb`, always | host `mc` only | `SOYMUTDB_NATIVE_WRITES_STOPPED=1` plus a live `pg_stat_activity` probe |

Select it with `SOYMUTDB_BACKUP_RUNTIME` or the `--runtime` flag, which wins
over the environment (`--runtime=compose|native`). Any other value is
rejected before a single directory, tool, or data access happens; the scripts
never guess a runtime from a hostname or a port. In the native runtime a
missing client tool, including a missing `mc`, fails the run. It never falls
back to a container. All three scripts accept `--no-repo-env` (equivalently
`SOYMUTDB_BACKUP_REPO_ENV=0`) to keep the repository `.env` out of the
process, which is what an isolated drill or an offline contract run should
use.

## Native Runtime Operations (No Docker)

Install the PostgreSQL client tools (`psql`, `pg_dump`, `pg_restore`, `dropdb`,
`createdb`) and the MinIO client `mc` on `PATH`, together with the tools both
runtimes need (`sha256sum`, `tar`, `stat`, `find`, `sort`, `grep`, `python3`).

Backup. `POSTGRES_PASSWORD` is the password source for the host clients; the
scripts never read credentials from `PGPASSWORD` directly. Stop every writer
first: the native runtime cannot inspect a compose service table, so both the
quiesced flag and the out-of-band attestation are mandatory.

```bash
export SOYMUTDB_BACKUP_RUNTIME=native
export SOYMUTDB_NATIVE_WRITES_STOPPED=1   # writers stopped out of band
export BACKUP_WRITES_QUIESCED=1
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432
export POSTGRES_USER=soymutdb POSTGRES_DB=soymutdb
export POSTGRES_PASSWORD=...              # never commit this value
export S3_ENDPOINT=http://127.0.0.1:9000 S3_ACCESS_KEY=... S3_SECRET_KEY=...
export BAK_BASE_DIR=/opt/soymutdb/backups BACKUP_METRICS_DIR=/var/lib/node_exporter/textfile_collector

bash deploy/scripts/backup.sh --runtime native --no-repo-env
```

`BAK_S3_BUCKETS` still has to contain all six authoritative buckets, and
`BACKUP_S3`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_ACCESS_KEY`,
`BACKUP_S3_SECRET_KEY` still drive the offsite copy. Checksums, the six-bucket
coverage, the atomic `.partial` publication, the `.sha256` / `.complete`
markers, retention, and the failure metric are identical in both runtimes. The
published `manifest.json` gains a `runtime` block recording the mode, the
PostgreSQL and S3 clients, and how the writers quiescence was proven.

Isolated restore drill. The target config attests the runtime and the isolated
instance; a native target without those attestations is refused.

```bash
sudo install -m 0600 /dev/null /etc/soymutdb/secrets/drill-restore-native.env
```

The file (mode 0600) must set:

```bash
RESTORE_TARGET_ID=drill
RESTORE_TARGET_ISOLATED=1
RESTORE_TARGET_RUNTIME=native
RESTORE_NATIVE_INSTANCE_ID=drill-1        # must not be prod/production
RESTORE_POSTGRES_HOST=127.0.0.1
RESTORE_POSTGRES_PORT=5433
RESTORE_POSTGRES_USER=soymutdb
RESTORE_POSTGRES_DB=soymutdb_drill
RESTORE_POSTGRES_PASSWORD=...
RESTORE_S3_ENDPOINT=http://127.0.0.1:9100
RESTORE_S3_ACCESS_KEY=...
RESTORE_S3_SECRET_KEY=...
RESTORE_WRITES_QUIESCED=1
SOYMUTDB_NATIVE_WRITES_STOPPED=1
```

`RESTORE_COMPOSE_FILE` / `RESTORE_COMPOSE_PROJECT` are not required for a
native target, but if `RESTORE_COMPOSE_FILE` is present it still may not point
at the repository's default production Compose file. Run the drill with:

```bash
bash deploy/scripts/restore.sh --runtime native --target drill \
  --target-config /etc/soymutdb/secrets/drill-restore-native.env \
  --no-repo-env /path/to/<id>.tar.gz
```

The drill target PostgreSQL is contacted directly and must answer a
reachability probe before anything destructive starts; an unreachable target
fails instead of proceeding. The `.incomplete` marker and the legacy-v2
behaviour are unchanged.

Production restore. `--target prod` accepts no `--target-config` and cannot be
pre-authorized by any environment variable: the operator still has to type
`restore` at the prompt. It additionally requires `RESTORE_WRITES_QUIESCED=1`
and, in the native runtime, `SOYMUTDB_NATIVE_WRITES_STOPPED=1`.

```bash
bash deploy/scripts/restore.sh --runtime native --target prod /path/to/<id>.tar.gz
```

Verification. Point the host clients at the restored target and select the
runtime; `--skip-s3` and `--skip-s3-checksum` remain explicit exceptions and a
run with skips is never reported as a full verification.

```bash
SOYMUTDB_BACKUP_RUNTIME=native POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 \
POSTGRES_USER=soymutdb POSTGRES_DB=soymutdb POSTGRES_PASSWORD=... \
S3_ENDPOINT=http://127.0.0.1:9000 S3_ACCESS_KEY=... S3_SECRET_KEY=... \
bash deploy/scripts/verify-restore.sh --runtime native --no-repo-env /path/to/<id>.tar.gz
```

Verification reports the runtime recorded in the archive, and warns when it
differs from the runtime of the current run. Legacy format-v2 archives carry a
ClickHouse component and stay compose-only: both restore and verification
refuse them in the native runtime, with or without `--allow-legacy-v2`.

## Backup and Drill

Set `BACKUP_S3=alias/bucket/prefix` when offsite retention is required. If configured, any upload or remote verification failure fails the entire run. Only archives with matching `.sha256` and `.complete` files are committed backups. Configure retention/lifecycle rules on the offsite bucket; the script does not delete historical remote backups.

```bash
docker compose stop api worker-default worker-analyses worker-blast worker-ingest beat
BACKUP_WRITES_QUIESCED=1 bash deploy/scripts/backup.sh
bash deploy/scripts/verify-restore.sh /path/to/<id>.tar.gz
```

The quiescence guard is mandatory: PostgreSQL and S3 do not share a transaction, so an online backup cannot claim one cross-store point in time. The script also verifies that Compose writer services are stopped. Keep them stopped until the backup finishes.

Those commands use the default `compose` runtime. Add `--runtime native` (see [Runtime Selection](#runtime-selection-compose-and-native)) when PostgreSQL and MinIO run on the host instead of Compose.

The default stack has no ClickHouse service. Historical format-v2 archives require `--allow-legacy-v2` for both restore and verification. They require a reachable legacy service and its backup disk; a missing component fails the operation. With that flag, scripts load `docker-compose.legacy-clickhouse.yml` when present beside the target compose file. An isolated target can explicitly provide `RESTORE_LEGACY_COMPOSE_FILE` / `VERIFY_LEGACY_COMPOSE_FILE`. Start the legacy service in that isolated project before restoring. Verify and backfill historical facts using [the native cutover guide](../dev/native-postgres-cutover.md) before starting native application writers.

For a drill, create a separate Compose project and a mode-0600 target file. The file must set `RESTORE_TARGET_ID`, `RESTORE_TARGET_ISOLATED=1`, a non-production `RESTORE_COMPOSE_FILE`, `RESTORE_COMPOSE_PROJECT`, explicit `RESTORE_POSTGRES_*`, `RESTORE_S3_*`, and `RESTORE_WRITES_QUIESCED=1`. Only a legacy-v2 drill additionally requires `RESTORE_CLICKHOUSE_HOST/USER`. Legacy verification requires explicit `CLICKHOUSE_HOST`. The restore refuses the repository's default Compose file:

```bash
bash deploy/scripts/restore.sh --target drill \
  --target-config /etc/soymutdb/secrets/drill-restore.env \
  /path/to/<id>.tar.gz
```

Production restore likewise requires all writers stopped plus `RESTORE_WRITES_QUIESCED=1`, and requires typing `restore`. An atomic `.incomplete` marker remains under the backup directory after any partial failure; do not restart writers until the restore is rerun successfully and independent verification passes.

`--skip-s3` and `--skip-s3-checksum` are explicit verification exceptions. They are never enabled by default, and verification reports a run with skips as incomplete.

Bucket policies are restored and independently compared against the target. Policy-less buckets (`{}` or a version with an empty statement list) are reset with `mc anonymous set none`; nonempty policies use `set-json`. A failed policy read, invalid JSON, or differing policy fails verification.

Format v3 captures and verifies the current object version for every key. It does not archive historical MinIO versions or deletion markers; retain MinIO replication/object-lock retention separately when historical versions are part of the recovery objective.

Format-v1 archives lack the complete bucket and artifact contracts and are rejected by these restore scripts. Preserve legacy tooling for historical archives, create and verify a fresh format-v3 backup after native cutover, and do not delete old backups during migration.

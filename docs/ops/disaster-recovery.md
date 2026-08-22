# Disaster Recovery Operations

Authoritative format-v2 backups include PostgreSQL, the complete `soymutdb` ClickHouse database, and these S3 buckets: `genomic-data`, `user-tracks`, `blast-dbs`, `exports`, `gwas`, and `analyses`. Extra buckets may be configured, but required buckets cannot be removed.

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

## Backup and Drill

Set `BACKUP_S3=alias/bucket/prefix` when offsite retention is required. If configured, any upload or remote verification failure fails the entire run. Only archives with matching `.sha256` and `.complete` files are committed backups. Configure retention/lifecycle rules on the offsite bucket; the script does not delete historical remote backups.

```bash
docker compose stop api worker-default worker-analyses worker-blast worker-ingest beat
BACKUP_WRITES_QUIESCED=1 bash deploy/scripts/backup.sh
bash deploy/scripts/verify-restore.sh /path/to/<id>.tar.gz
```

The quiescence guard is mandatory: PostgreSQL, ClickHouse, and S3 do not share a transaction, so an online backup cannot claim one cross-store point in time. The script also verifies that Compose writer services are stopped. Keep them stopped until the backup finishes.

The Compose stack mounts a dedicated ClickHouse `backups` disk at `/var/lib/clickhouse-backups`. Apply the updated ClickHouse configuration and restart that service before the first v2 backup.

For a drill, create a separate Compose project and a mode-0600 target file. The file must set `RESTORE_TARGET_ID`, `RESTORE_TARGET_ISOLATED=1`, a non-production `RESTORE_COMPOSE_FILE`, `RESTORE_COMPOSE_PROJECT`, explicit `RESTORE_POSTGRES_*`, `RESTORE_CLICKHOUSE_HOST/USER`, `RESTORE_S3_*`, and `RESTORE_WRITES_QUIESCED=1`. The restore refuses the repository's default Compose file:

```bash
bash deploy/scripts/restore.sh --target drill \
  --target-config /etc/soymutdb/secrets/drill-restore.env \
  /path/to/<id>.tar.gz
```

Production restore likewise requires all writers stopped plus `RESTORE_WRITES_QUIESCED=1`, and requires typing `restore`. An atomic `.incomplete` marker remains under the backup directory after any partial failure; do not restart writers until the restore is rerun successfully and independent verification passes.

`--skip-s3` and `--skip-s3-checksum` are explicit verification exceptions. They are never enabled by default, and verification reports a run with skips as incomplete.

Format v2 captures and verifies the current object version for every key. It does not archive historical MinIO versions or deletion markers; retain MinIO replication/object-lock retention separately when historical versions are part of the recovery objective.

Format-v1 archives lack the complete bucket and artifact contracts and are rejected by the new restore scripts. Preserve legacy tooling for historical archives, create and verify a fresh format-v2 backup before rollout, and do not delete old backups during migration.

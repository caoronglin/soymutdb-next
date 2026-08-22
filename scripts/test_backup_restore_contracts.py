import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "deploy/scripts/backup.sh"
RESTORE = ROOT / "deploy/scripts/restore.sh"
VERIFY = ROOT / "deploy/scripts/verify-restore.sh"
COMPOSE = ROOT / "docker-compose.yml"
PROMETHEUS = ROOT / "infra/monitoring/prometheus.yml"
ALERTS = ROOT / "infra/monitoring/rules/alerts.yml"
ALERTMANAGER = ROOT / "infra/monitoring/alertmanager.yml"
ALERTMANAGER_ENTRYPOINT = ROOT / "infra/monitoring/start-alertmanager.sh"
CLICKHOUSE_CONFIG = ROOT / "infra/clickhouse/config.xml"
DISASTER_RECOVERY_DOC = ROOT / "docs/ops/disaster-recovery.md"

REQUIRED_BUCKETS = (
    "genomic-data",
    "user-tracks",
    "blast-dbs",
    "exports",
    "gwas",
    "analyses",
)

QUIESCED_WRITER_SERVICES = (
    "api",
    "worker-default",
    "worker-analyses",
    "worker-blast",
    "worker-ingest",
    "beat",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdin: str = "",
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=merged_env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _make_backup_archive(
    tmp_path: Path,
    *,
    buckets: tuple[str, ...] = REQUIRED_BUCKETS,
    pg_rows: str = "public.items\t1\n",
    clickhouse_rows: str = "variant_facts\t1\t1\n",
    component_statuses: dict[str, str] | None = None,
    corrupt_after_manifest: str | None = None,
    sidecar: bool = True,
    completion_marker: bool = True,
) -> Path:
    source = tmp_path / "fixture-backup"
    source.mkdir()
    (source / "s3_data").mkdir()

    files: dict[str, bytes] = {
        "postgres.dump": b"fixture-postgres-dump",
        "clickhouse_soymutdb.zip": b"fixture-clickhouse-backup",
        "pg_rows.tsv": pg_rows.encode(),
        "clickhouse_rows.tsv": clickhouse_rows.encode(),
        "s3_buckets.txt": ("\n".join(buckets) + "\n").encode(),
        "s3_manifest.tsv": b"",
    }
    for bucket in buckets:
        (source / "s3_data" / bucket).mkdir()
        files[f"s3_policy_{bucket}.json"] = b"{}\n"

    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    artifact_lines: list[str] = []
    for path in sorted(source.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            artifact_lines.append(
                f"{_sha256(path)}\t{path.stat().st_size}\t{relative}\n"
            )
    artifact_manifest = source / "artifact_checksums.tsv"
    artifact_manifest.write_text("".join(artifact_lines), encoding="utf-8")

    statuses = {"postgres": "ok", "clickhouse": "ok", "s3": "ok"}
    statuses.update(component_statuses or {})
    manifest = {
        "format_version": 2,
        "backup_id": "fixture-backup",
        "created_at": "2026-08-19T00:00:00Z",
        "consistency": {"mode": "writers_quiesced"},
        "components": {
            "postgres": {
                "status": statuses["postgres"],
                "file": "postgres.dump",
                "row_counts_file": "pg_rows.tsv",
                "tables": len([line for line in pg_rows.splitlines() if line]),
            },
            "clickhouse": {
                "status": statuses["clickhouse"],
                "file": "clickhouse_soymutdb.zip",
                "row_counts_file": "clickhouse_rows.tsv",
                "tables": len([line for line in clickhouse_rows.splitlines() if line]),
            },
            "s3": {
                "status": statuses["s3"],
                "manifest_file": "s3_manifest.tsv",
                "buckets_file": "s3_buckets.txt",
                "object_count": 0,
                "total_bytes": 0,
                "checksum_algorithm": "sha256",
            },
        },
        "artifact_manifest": {
            "file": "artifact_checksums.tsv",
            "size": artifact_manifest.stat().st_size,
            "sha256": _sha256(artifact_manifest),
        },
    }
    (source / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    if corrupt_after_manifest:
        with (source / corrupt_after_manifest).open("ab") as handle:
            handle.write(b"corrupt")

    archive = tmp_path / "fixture-backup.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname=source.name)
    if sidecar:
        Path(f"{archive}.sha256").write_text(
            f"{_sha256(archive)}  {archive.name}\n", encoding="utf-8"
        )
    if completion_marker:
        Path(f"{archive}.complete").write_text(
            f"backup_id=fixture-backup\nsha256={_sha256(archive)}\n",
            encoding="utf-8",
        )
    return archive


def _verification_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    _write_executable(fake_bin / "psql", "printf '1\\n'")
    _write_executable(fake_bin / "curl", "printf '1\\n'")
    _write_executable(fake_bin / "mc", "exit 42")
    _write_executable(fake_bin / "docker", "exit 42")
    return {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "POSTGRES_HOST": "pg-drill.invalid",
        "CLICKHOUSE_HOST": "ch-drill.invalid",
        "BAK_BASE_DIR": str(tmp_path / "backup-client-state"),
    }


def test_all_scripts_pin_the_complete_authoritative_bucket_set() -> None:
    for script in (BACKUP, RESTORE, VERIFY):
        text = script.read_text(encoding="utf-8")
        match = re.search(
            r'^readonly REQUIRED_S3_BUCKETS="([^"]+)"$', text, re.MULTILINE
        )
        assert match is not None, f"{script.name} must define the authoritative set"
        assert tuple(match.group(1).split()) == REQUIRED_BUCKETS
        assert '"buckets_file"' in text


def test_backup_uses_atomic_artifacts_metrics_and_delays_success_banner() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    assert "artifact_checksums.tsv" in script
    assert ".partial" in script
    assert "verify_local_archive" in script
    assert "publish_local_artifacts" in script
    assert "upload_offsite_backup" in script
    assert "write_completion_marker" in script
    assert 'write_backup_metric "1"' in script
    assert "on_exit" in script and "trap" in script
    assert "--collector.textfile.directory" not in script

    completion = script.rindex("Backup Complete")
    assert script.rindex("upload_offsite_backup") < completion
    assert script.rindex('write_backup_metric "1"') < completion
    assert script.rindex("publish_offsite_backup") < script.rindex(
        "publish_local_artifacts"
    )
    assert script.rindex("write_completion_marker") < script.rindex(
        'write_backup_metric "1"'
    )
    assert "回退为维度表 TSV" not in script


def test_clickhouse_backup_disk_is_declared_and_mounted() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    config = CLICKHOUSE_CONFIG.read_text(encoding="utf-8")
    backup = BACKUP.read_text(encoding="utf-8")
    restore = RESTORE.read_text(encoding="utf-8")

    assert "<storage_configuration>" in config
    assert "<backups>" in config
    assert "<path>/var/lib/clickhouse-backups/</path>" in config
    assert "<allowed_disk>backups</allowed_disk>" in config
    assert "chbackups:/var/lib/clickhouse-backups" in compose
    assert "chbackups:" in compose
    assert "/var/lib/clickhouse-backups/" in backup
    assert "/var/lib/clickhouse-backups/" in restore


def test_backup_requires_quiesced_writers_before_data_access() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    guard = script.index("BACKUP_WRITES_QUIESCED")
    postgres_snapshot = script.index('echo -e "${CYAN}[1/3] PostgreSQL')
    assert guard < postgres_snapshot
    assert "assert_writers_stopped" in script
    assert '"mode": "writers_quiesced"' in script
    assert "consistency.mode" in RESTORE.read_text(encoding="utf-8")


def test_quiescence_contract_covers_all_compose_writer_services() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    compose_writers = set(
        re.findall(r"^  (api|worker-[a-z0-9-]+|beat):$", compose, re.MULTILINE)
    )
    expected_writers = set(QUIESCED_WRITER_SERVICES)
    assert compose_writers == expected_writers

    for script_path in (BACKUP, RESTORE):
        script = script_path.read_text(encoding="utf-8")
        match = re.search(
            r"^readonly -a QUIESCED_WRITER_SERVICES=\(([^)]*)\)$",
            script,
            re.MULTILINE,
        )
        assert match is not None, f"{script_path.name} must declare writer services"
        assert tuple(match.group(1).split()) == QUIESCED_WRITER_SERVICES
        assert 'for service in "${QUIESCED_WRITER_SERVICES[@]}"; do' in script

    operations = DISASTER_RECOVERY_DOC.read_text(encoding="utf-8")
    stop_command = re.search(r"^docker compose stop (.+)$", operations, re.MULTILINE)
    assert stop_command is not None
    assert tuple(stop_command.group(1).split()) == QUIESCED_WRITER_SERVICES


def test_backup_does_not_hide_object_or_artifact_enumeration_failures() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    assert '< <(find "${local_bucket_dir}"' not in script
    assert '< <(find "${STAGING_DIR}"' not in script
    assert "S3 object enumeration failed" in script
    assert "artifact enumeration failed" in script


def test_offsite_absence_probe_is_fail_closed() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    assert "assert_remote_target_absent" in script
    assert "could not prove offsite target is absent" in script


def test_s3_credentials_are_not_passed_as_mc_alias_argv() -> None:
    for script_path in (BACKUP, RESTORE, VERIFY):
        script = script_path.read_text(encoding="utf-8")
        assert "mc_configure_alias_env" in script
        assert "mc_run alias set" not in script


def test_retention_preserves_legacy_uncommitted_and_unrecognized_archives() -> None:
    script = BACKUP.read_text(encoding="utf-8")

    assert '[[ ! -f "${dir}/${name}.complete" ]]' in script
    assert 'keep["${name}"]="not-format-v2"' in script
    assert 'keep["${name}"]="unrecognized"' in script


def test_backup_failure_cleans_staging_and_writes_failure_metric(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "psql", "exit 31")
    _write_executable(fake_bin / "pg_dump", "exit 31")
    _write_executable(fake_bin / "docker", "exit 31")
    _write_executable(fake_bin / "mc", "exit 31")

    backup_dir = tmp_path / "backups"
    metrics_dir = tmp_path / "metrics"
    result = _run(
        ["bash", str(BACKUP)],
        env={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "BAK_BASE_DIR": str(backup_dir),
            "BACKUP_METRICS_DIR": str(metrics_dir),
            "POSTGRES_HOST": "pg-backup.invalid",
            "BAK_S3_BUCKETS": " ".join(REQUIRED_BUCKETS),
        },
    )

    assert result.returncode != 0
    assert "Backup Complete" not in result.stdout + result.stderr
    assert not list(backup_dir.glob("*.tar.gz"))
    staging = backup_dir / ".staging"
    assert not staging.exists() or not list(staging.iterdir())
    metric = metrics_dir / "soymutdb_backup.prom"
    assert metric.is_file()
    metric_text = metric.read_text(encoding="utf-8")
    assert "soymutdb_backup_status 0" in metric_text
    assert "soymutdb_backup_last_failure_timestamp_seconds" in metric_text
    assert not list(metrics_dir.glob("*.tmp"))


def test_bucket_override_cannot_omit_analyses_or_touch_data_services(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    called = tmp_path / "external-command-called"
    command_body = f"touch {called!s}; exit 55"
    for name in ("docker", "mc", "psql", "pg_dump", "curl"):
        _write_executable(fake_bin / name, command_body)

    result = _run(
        ["bash", str(BACKUP)],
        env={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "BAK_BASE_DIR": str(tmp_path / "backups"),
            "BACKUP_METRICS_DIR": str(tmp_path / "metrics"),
            "BAK_S3_BUCKETS": "genomic-data user-tracks blast-dbs exports gwas",
        },
    )

    assert result.returncode != 0
    assert "analyses" in (result.stdout + result.stderr)
    assert not called.exists(), (
        "configuration must fail before contacting data services"
    )


def test_restore_rejects_non_ok_component_before_confirmation(tmp_path: Path) -> None:
    archive = _make_backup_archive(
        tmp_path, component_statuses={"clickhouse": "backup-failed"}
    )
    result = _run(["bash", str(RESTORE), "--target", "drill", str(archive)])

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "clickhouse" in output.lower() and "status" in output.lower()
    assert "确认?" not in output


def test_drill_restore_requires_explicit_isolated_target_config(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path)
    result = _run(["bash", str(RESTORE), "--target", "drill", str(archive)])

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "target config" in output.lower()
    assert "restore over isolated target" not in output.lower()


def test_drill_restore_rejects_default_compose_as_isolated(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path)
    target = tmp_path / "drill.env"
    target.write_text(
        "\n".join(
            (
                "RESTORE_TARGET_ID=drill",
                "RESTORE_TARGET_ISOLATED=1",
                f"RESTORE_COMPOSE_FILE={COMPOSE}",
                "RESTORE_COMPOSE_PROJECT=soymutdb-drill",
                "RESTORE_POSTGRES_HOST=localhost",
                "RESTORE_POSTGRES_PORT=5432",
                "RESTORE_POSTGRES_USER=soymutdb",
                "RESTORE_POSTGRES_DB=soymutdb",
                "RESTORE_POSTGRES_PASSWORD=not-a-real-secret",
                "RESTORE_CLICKHOUSE_HOST=localhost",
                "RESTORE_CLICKHOUSE_USER=soymutdb",
                "RESTORE_S3_ENDPOINT=http://localhost:9001",
                "RESTORE_S3_ACCESS_KEY=drill",
                "RESTORE_S3_SECRET_KEY=not-a-real-secret",
                "RESTORE_WRITES_QUIESCED=1",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--target",
            "drill",
            "--target-config",
            str(target),
            str(archive),
        ]
    )

    assert result.returncode != 0
    assert "default production compose" in (result.stdout + result.stderr).lower()


def test_restore_requires_quiesced_writers_and_tracks_incomplete_state() -> None:
    script = RESTORE.read_text(encoding="utf-8")

    assert "RESTORE_WRITES_QUIESCED" in script
    assert "assert_writers_stopped" in script
    assert "RESTORE_STATE_FILE" in script
    assert "restore_incomplete" in script
    assert 'rm -f -- "${RESTORE_STATE_FILE}"' in script
    assert script.index("restore_incomplete") < script.index("Restoring PostgreSQL")
    assert "verify_restored_postgres_rows" in script
    assert "verify_restored_clickhouse_rows" in script
    assert script.index("verify_restored_postgres_rows") < script.index(
        'rm -f -- "${RESTORE_STATE_FILE}"'
    )


def test_restore_replaces_databases_instead_of_leaving_unknown_objects() -> None:
    script = RESTORE.read_text(encoding="utf-8")

    assert "dropdb" in script and "createdb" in script
    assert script.index("dropdb") < script.index("pg_restore")
    assert 'DROP DATABASE IF EXISTS soymutdb SYNC' in script
    assert script.index('DROP DATABASE IF EXISTS soymutdb SYNC') < script.index(
        "RESTORE DATABASE soymutdb"
    )
    assert "ClickHouse table discovery before restore failed" not in script


def test_restore_and_verify_require_the_archive_sidecar(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path, sidecar=False)
    for command in (
        ["bash", str(RESTORE), "--target", "drill", str(archive)],
        ["bash", str(VERIFY), str(archive)],
    ):
        result = _run(command)
        assert result.returncode != 0
        assert "sidecar" in (result.stdout + result.stderr).lower()


def test_restore_and_verify_require_the_completion_marker(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path, completion_marker=False)
    for command in (
        ["bash", str(RESTORE), "--target", "drill", str(archive)],
        ["bash", str(VERIFY), str(archive)],
    ):
        result = _run(command)
        assert result.returncode != 0
        assert "completion marker" in (result.stdout + result.stderr).lower()


def test_verify_rejects_missing_required_bucket(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path, buckets=REQUIRED_BUCKETS[:-1])
    result = _run(["bash", str(VERIFY), str(archive)])

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "analyses" in output and "bucket" in output.lower()


def test_verify_rejects_empty_or_error_row_snapshots(tmp_path: Path) -> None:
    for case, rows in (("empty", ""), ("error", "public.items\tERROR\n")):
        case_dir = tmp_path / case
        case_dir.mkdir()
        archive = _make_backup_archive(case_dir, pg_rows=rows)
        result = _run(["bash", str(VERIFY), str(archive)])

        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert "row" in output.lower() and "snapshot" in output.lower()


def test_verify_rejects_unsafe_snapshot_table_identifiers(tmp_path: Path) -> None:
    cases = (
        {"pg_rows": "public.items;DROP TABLE users\t1\n"},
        {"clickhouse_rows": "facts`; DROP DATABASE soymutdb\t1\t1\n"},
    )
    for index, overrides in enumerate(cases):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        archive = _make_backup_archive(case_dir, **overrides)
        result = _run(["bash", str(VERIFY), str(archive)])

        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert "snapshot" in output.lower() and "identifier" in output.lower()


def test_verify_rejects_internal_artifact_checksum_mismatch(tmp_path: Path) -> None:
    archive = _make_backup_archive(
        tmp_path, corrupt_after_manifest="clickhouse_soymutdb.zip"
    )
    result = _run(["bash", str(VERIFY), str(archive)])

    assert result.returncode != 0
    assert "checksum" in (result.stdout + result.stderr).lower()


def test_verify_only_skips_s3_when_explicitly_requested(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path)
    env = _verification_env(tmp_path)

    default_result = _run(["bash", str(VERIFY), str(archive)], env=env)
    assert default_result.returncode != 0
    assert "s3" in (default_result.stdout + default_result.stderr).lower()

    skipped_result = _run(["bash", str(VERIFY), "--skip-s3", str(archive)], env=env)
    assert skipped_result.returncode == 0, skipped_result.stdout + skipped_result.stderr
    assert "explicit skip" in (skipped_result.stdout + skipped_result.stderr).lower()
    assert "all checks passed" not in skipped_result.stdout.lower()


def test_monitoring_connects_prometheus_to_validated_alertmanager() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    prometheus = PROMETHEUS.read_text(encoding="utf-8")
    alerts = ALERTS.read_text(encoding="utf-8")

    assert "--collector.textfile.directory=/textfile" in compose
    assert "BACKUP_METRICS_DIR" in compose
    assert re.search(r"^  alertmanager:$", compose, re.MULTILINE)
    assert "prom/alertmanager:" in compose
    assert ":latest" not in re.search(
        r"^  alertmanager:\n.*?(?=^  [a-z0-9-]+:\n|^volumes:)",
        compose,
        re.MULTILINE | re.DOTALL,
    ).group(0)
    assert "alertmanager_webhook_url" in compose
    assert "start-alertmanager.sh" in compose
    prometheus_service = re.search(
        r"^  prometheus:\n.*?(?=^  [a-z0-9-]+:\n|^volumes:)",
        compose,
        re.MULTILINE | re.DOTALL,
    ).group(0)
    assert "condition: service_healthy" not in prometheus_service

    assert "alerting:" in prometheus
    assert 'targets: ["alertmanager:9093"]' in prometheus
    assert 'job_name: "alertmanager"' in prometheus
    assert "BackupStale" in alerts
    assert "BackupFailed" in alerts
    assert "soymutdb_backup_last_success_timestamp_seconds" in alerts
    assert "soymutdb_backup_status == 0" in alerts


def test_alertmanager_template_contains_no_receiver_secret() -> None:
    config = ALERTMANAGER.read_text(encoding="utf-8")

    assert "url_file: /run/secrets/alertmanager_webhook_url" in config
    assert "https://" not in config
    assert "__WEBHOOK" not in config


def test_alertmanager_startup_rejects_missing_insecure_or_invalid_config(
    tmp_path: Path,
) -> None:
    base_env = {
        "ALERTMANAGER_CONFIG_FILE": str(ALERTMANAGER),
        "ALERTMANAGER_BIN": "/bin/true",
        "AMTOOL_BIN": "/bin/true",
    }
    missing = _run(["sh", str(ALERTMANAGER_ENTRYPOINT)], env=base_env)
    assert missing.returncode != 0
    assert "missing or empty" in (missing.stdout + missing.stderr).lower()

    secret = tmp_path / "receiver-url"
    secret.write_text("http://receiver.invalid/hook\n", encoding="utf-8")
    insecure = _run(
        ["sh", str(ALERTMANAGER_ENTRYPOINT)],
        env={**base_env, "ALERTMANAGER_WEBHOOK_URL_FILE": str(secret)},
    )
    assert insecure.returncode != 0
    assert "https" in (insecure.stdout + insecure.stderr).lower()

    receiver = "https://receiver.invalid/private-token"
    secret.write_text(f"{receiver}\n", encoding="utf-8")
    invalid_config = _run(
        ["sh", str(ALERTMANAGER_ENTRYPOINT)],
        env={
            **base_env,
            "ALERTMANAGER_WEBHOOK_URL_FILE": str(secret),
            "AMTOOL_BIN": "/bin/false",
        },
    )
    assert invalid_config.returncode != 0
    assert receiver not in invalid_config.stdout + invalid_config.stderr

    valid = _run(
        ["sh", str(ALERTMANAGER_ENTRYPOINT)],
        env={**base_env, "ALERTMANAGER_WEBHOOK_URL_FILE": str(secret)},
    )
    assert valid.returncode == 0, valid.stdout + valid.stderr
    assert receiver not in valid.stdout + valid.stderr


def test_contract_test_has_no_runtime_docker_dependency() -> None:
    assert shutil.which("bash") is not None

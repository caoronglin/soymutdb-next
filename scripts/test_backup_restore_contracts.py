import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "deploy/scripts/backup.sh"
RESTORE = ROOT / "deploy/scripts/restore.sh"
RUNTIME = ROOT / "deploy/scripts/backup-runtime.sh"
VERIFY = ROOT / "deploy/scripts/verify-restore.sh"
COMPOSE = ROOT / "docker-compose.yml"
PROMETHEUS = ROOT / "infra/monitoring/prometheus.yml"
ALERTS = ROOT / "infra/monitoring/rules/alerts.yml"
ALERTMANAGER = ROOT / "infra/monitoring/alertmanager.yml"
ALERTMANAGER_ENTRYPOINT = ROOT / "infra/monitoring/start-alertmanager.sh"
CLICKHOUSE_CONFIG = ROOT / "infra/clickhouse/config.xml"
LEGACY_COMPOSE = ROOT / "docker-compose.legacy-clickhouse.yml"
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


def _write_python_executable(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


FAKE_DOCKER = """
import os
import sys

args = sys.argv[1:]
if "clickhouse-client" in args:
    print(os.environ.get("FAKE_CLICKHOUSE_ROW_COUNT", "1"))
    raise SystemExit(0)
if "--services" in args:
    for service in os.environ.get("FAKE_COMPOSE_SERVICES", "postgres").split():
        print(service)
    raise SystemExit(0)
if "ps" in args:
    raise SystemExit(0)
raise SystemExit(0)
"""

FAKE_PSQL = """
import os
import sys

sql = sys.argv[-1]
if "pg_tables" in sql:
    for table in os.environ.get("FAKE_PG_TABLES", "public.items").split(","):
        print(table)
elif "count(*)" in sql:
    print(os.environ.get("FAKE_PG_ROW_COUNT", "1"))
raise SystemExit(0)
"""

FAKE_PG_DUMP = """
import sys

if "-f" in sys.argv:
    target = sys.argv[sys.argv.index("-f") + 1]
    with open(target, "wb") as handle:
        handle.write(b"fixture-postgres-dump")
raise SystemExit(0)
"""

FAKE_MC = """
import json
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
if args and args[0] == "--config-dir":
    args = args[2:]
if not args:
    raise SystemExit(0)
store = Path(os.environ["FAKE_MC_STORE"])
# Bucket policies live beside the object store instead of inside a bucket
# directory, so they never appear in an object listing.
policy_root = store / "_policies"
invocation_log = os.environ.get("FAKE_MC_LOG")
if invocation_log:
    with open(invocation_log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\\n")


def parse_uri(uri):
    alias, _, rest = uri.partition("/")
    return alias, rest.strip("/")


def policy_path(alias, key):
    return policy_root / alias / (key + ".json")


if args[0] == "mirror":
    source_raw, destination_raw = args[-2], args[-1]
    source, destination = Path(source_raw), Path(destination_raw)
    if destination.is_dir():
        alias, key = parse_uri(source_raw)
        root = store / alias / key
        if not root.is_dir():
            raise SystemExit(11)
        for path in sorted(root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    else:
        if not source.is_dir():
            raise SystemExit(11)
        alias, key = parse_uri(destination_raw)
        target = store / alias / key
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(source.rglob("*")):
            if path.is_file():
                relative = path.relative_to(source).as_posix()
                out = target / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, out)
    raise SystemExit(0)

if args[0] == "anonymous" and args[1] == "get-json":
    alias, key = parse_uri(args[2])
    if not (store / alias / key).is_dir():
        raise SystemExit(12)
    if os.environ.get("FAKE_MC_FAIL_GET_JSON") == "1":
        print("mc: <ERROR> Access Denied", file=sys.stderr)
        raise SystemExit(13)
    # MinIO reads a policy-less bucket back as an empty document.
    stored = policy_path(alias, key)
    sys.stdout.write(
        stored.read_text(encoding="utf-8") if stored.is_file() else "{}"
    )
    raise SystemExit(0)

if args[0] == "anonymous" and args[1] == "set":
    # Only the policy-free reset is modelled; anything else is unsupported.
    alias, key = parse_uri(args[-1])
    if args[2] != "none":
        raise SystemExit(18)
    if not (store / alias / key).is_dir():
        raise SystemExit(19)
    stored = policy_path(alias, key)
    if stored.is_file():
        stored.unlink()
    raise SystemExit(0)

if args[0] == "anonymous" and args[1] == "set-json":
    alias, key = parse_uri(args[3])
    target = store / alias / key
    target.mkdir(parents=True, exist_ok=True)
    if os.environ.get("FAKE_MC_FAIL_SET_JSON") == "1":
        print("mc: <ERROR> Access Denied", file=sys.stderr)
        raise SystemExit(20)
    document = json.loads(Path(args[2]).read_text(encoding="utf-8"))
    # MinIO rejects a document that carries no 2012-10-17 policy version, so a
    # restore that ships an empty {} policy fails exactly like it does live.
    if not isinstance(document, dict) or document.get("Version") != "2012-10-17":
        print(
            "mc: <ERROR> Invalid policy version. Only 2012-10-17 is supported.",
            file=sys.stderr,
        )
        raise SystemExit(21)
    stored = policy_path(alias, key)
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(json.dumps(document, sort_keys=True) + "\\n", encoding="utf-8")
    raise SystemExit(0)

if args[0] == "mb":
    for uri in args[1:]:
        if uri.startswith("-"):
            continue
        alias, key = parse_uri(uri)
        (store / alias / key).mkdir(parents=True, exist_ok=True)
    raise SystemExit(0)

if args[0] == "ls":
    alias, key = parse_uri([a for a in args[1:] if not a.startswith("-")][-1])
    target = store / alias / key
    if not target.is_dir():
        raise SystemExit(13)
    if "--json" in args:
        for path in sorted(target.rglob("*")):
            if path.is_file():
                print(json.dumps({
                    "type": "file",
                    "key": path.relative_to(target).as_posix(),
                    "size": path.stat().st_size,
                }))
    raise SystemExit(0)

if args[0] == "cp":
    source_raw, destination_raw = args[-2], args[-1]

    def is_remote(value):
        return not value.startswith("/") and not Path(value).exists()

    if is_remote(source_raw) and is_remote(destination_raw):
        alias, key = parse_uri(source_raw)
        found = store / alias / key
        if not found.is_file():
            raise SystemExit(14)
        alias, key = parse_uri(destination_raw)
        target = store / alias / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, target)
    elif is_remote(source_raw):
        alias, key = parse_uri(source_raw)
        found = store / alias / key
        if not found.is_file():
            raise SystemExit(14)
        Path(destination_raw).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, destination_raw)
    elif is_remote(destination_raw):
        alias, key = parse_uri(destination_raw)
        target = store / alias / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_raw, target)
    else:
        if not Path(source_raw).exists():
            raise SystemExit(14)
        shutil.copy2(source_raw, destination_raw)
    raise SystemExit(0)

if args[0] == "cat":
    alias, key = parse_uri(args[-1])
    path = store / alias / key
    if not path.is_file():
        raise SystemExit(15)
    sys.stdout.buffer.write(path.read_bytes())
    sys.stdout.buffer.flush()
    raise SystemExit(0)

if args[0] == "stat":
    print("mc: <ERROR> Object does not exist")
    raise SystemExit(16)

if args[0] == "rm":
    for uri in args[1:]:
        if uri.startswith("-"):
            continue
        alias, key = parse_uri(uri)
        path = store / alias / key
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    raise SystemExit(0)

raise SystemExit(17)
"""


def _native_backup_environment(tmp_path: Path) -> dict[str, str]:
    """Mock a native (PostgreSQL + S3, no ClickHouse) deployment."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    _write_python_executable(fake_bin / "docker", FAKE_DOCKER)
    _write_python_executable(fake_bin / "mc", FAKE_MC)
    _write_python_executable(fake_bin / "psql", FAKE_PSQL)
    _write_python_executable(fake_bin / "pg_dump", FAKE_PG_DUMP)
    for name in ("pg_restore", "dropdb", "createdb"):
        _write_executable(fake_bin / name, "exit 0")
    store = tmp_path / "mc-store"
    store.mkdir(exist_ok=True)
    return {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_MC_STORE": str(store),
        "FAKE_MC_LOG": str(tmp_path / "mc-invocations.log"),
        "FAKE_COMPOSE_SERVICES": "postgres api worker-default beat",
        "POSTGRES_HOST": "pg-drill.invalid",
        "POSTGRES_PASSWORD": "not-a-real-secret",
        "S3_ENDPOINT": "http://localhost:9001",
        "S3_ACCESS_KEY": "not-a-real-access-key",
        "S3_SECRET_KEY": "not-a-real-secret-key",
        "BAK_BASE_DIR": str(tmp_path / "backups"),
        "BACKUP_METRICS_DIR": str(tmp_path / "metrics"),
        "BACKUP_WRITES_QUIESCED": "1",
        "BAK_S3_BUCKETS": " ".join(REQUIRED_BUCKETS),
    }


def _seed_source_bucket(store: Path, alias: str = "s3src") -> int:
    objects = 0
    for index, bucket in enumerate(REQUIRED_BUCKETS):
        target = store / alias / bucket
        target.mkdir(parents=True, exist_ok=True)
        (target / "payload.bin").write_bytes(f"object-{index}".encode())
        objects += 1
    return objects


def _seed_restored_target(store: Path) -> None:
    """Mirror the source objects into the alias a restore would populate."""
    for bucket in REQUIRED_BUCKETS:
        source = store / "s3src" / bucket
        target = store / "s3dst" / bucket
        target.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)


def _offsite_environment(tmp_path: Path) -> dict[str, str]:
    (tmp_path / "mc-store" / "offsite" / "dr-backups").mkdir(parents=True, exist_ok=True)
    return {
        "BACKUP_S3": "offsite/dr-backups",
        "BACKUP_S3_ENDPOINT": "https://offsite.invalid",
        "BACKUP_S3_ACCESS_KEY": "offsite-key",
        "BACKUP_S3_SECRET_KEY": "offsite-secret",
    }


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
    format_version: int = 3,
    pg_rows: str = "public.items\t1\n",
    clickhouse_rows: str = "variant_facts\t1\t1\n",
    s3_objects: dict[str, dict[str, bytes]] | None = None,
    component_statuses: dict[str, str] | None = None,
    policies: dict[str, str] | None = None,
    corrupt_after_manifest: str | None = None,
    sidecar: bool = True,
    completion_marker: bool = True,
) -> Path:
    source = tmp_path / "fixture-backup"
    source.mkdir()
    (source / "s3_data").mkdir()

    files: dict[str, bytes] = {
        "postgres.dump": b"fixture-postgres-dump",
        "pg_rows.tsv": pg_rows.encode(),
        "s3_buckets.txt": ("\n".join(buckets) + "\n").encode(),
        "s3_manifest.tsv": b"",
    }
    if format_version == 2:
        files["clickhouse_soymutdb.zip"] = b"fixture-clickhouse-backup"
        files["clickhouse_rows.tsv"] = clickhouse_rows.encode()
    for bucket in buckets:
        (source / "s3_data" / bucket).mkdir()
        # The default archived policy is the empty document a policy-less
        # bucket exports; a case can supply a real policy per bucket.
        policy = (policies or {}).get(bucket, "{}" + chr(10))
        files[f"s3_policy_{bucket}.json"] = policy.encode()

    for relative, content in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    s3_rows: list[str] = []
    for bucket, objects in (s3_objects or {}).items():
        for key, payload in objects.items():
            path = source / "s3_data" / bucket / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            s3_rows.append(
                f"{bucket}\t{key}\t{len(payload)}\t{_sha256(path)}\n"
            )
    (source / "s3_manifest.tsv").write_text("".join(sorted(s3_rows)), encoding="utf-8")

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
    components = {
        "postgres": {
            "status": statuses["postgres"],
            "file": "postgres.dump",
            "row_counts_file": "pg_rows.tsv",
            "tables": len([line for line in pg_rows.splitlines() if line]),
        },
        "s3": {
            "status": statuses["s3"],
            "manifest_file": "s3_manifest.tsv",
            "buckets_file": "s3_buckets.txt",
            "object_count": len(s3_rows),
            "total_bytes": sum(int(row.split("\t")[2]) for row in s3_rows),
            "checksum_algorithm": "sha256",
        },
    }
    if format_version == 2:
        components["clickhouse"] = {
            "status": statuses["clickhouse"],
            "file": "clickhouse_soymutdb.zip",
            "row_counts_file": "clickhouse_rows.tsv",
            "tables": len([line for line in clickhouse_rows.splitlines() if line]),
        }
    manifest = {
        "format_version": format_version,
        "backup_id": "fixture-backup",
        "created_at": "2026-08-19T00:00:00Z",
        "consistency": {"mode": "writers_quiesced"},
        "components": components,
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


VALID_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::genomic-data/*"],
        }
    ],
    # An unknown top-level field has to survive the comparison untouched.
    "SoyMutDBProbeField": "keep-me",
}

EMPTY_STATEMENT_POLICY = {"Version": "2012-10-17", "Statement": []}


def _mc_invocations(tmp_path: Path) -> list[str]:
    log = tmp_path / "mc-invocations.log"
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def _policy_invocations(tmp_path: Path, verb: str) -> list[str]:
    prefix = f"anonymous {verb} "
    return [line for line in _mc_invocations(tmp_path) if line.startswith(prefix)]


def _target_policy(store: Path, alias: str, bucket: str) -> dict | None:
    path = store / "_policies" / alias / f"{bucket}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def test_clickhouse_backup_disk_belongs_to_the_legacy_compose_file() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    legacy = LEGACY_COMPOSE.read_text(encoding="utf-8")
    config = CLICKHOUSE_CONFIG.read_text(encoding="utf-8")
    backup = BACKUP.read_text(encoding="utf-8")
    restore = RESTORE.read_text(encoding="utf-8")

    assert "<storage_configuration>" in config
    assert "<backups>" in config
    assert "<path>/var/lib/clickhouse-backups/</path>" in config
    assert "<allowed_disk>backups</allowed_disk>" in config
    # The default native stack has no ClickHouse at all; the backup disk lives
    # with the explicit legacy migration topology only.
    assert "clickhouse" not in compose.lower()
    assert "chbackups" not in compose
    assert "chbackups:/var/lib/clickhouse-backups" in legacy
    assert "chbackups:" in legacy
    # The native backup never touches ClickHouse; only the explicit legacy
    # restore path still carries the ClickHouse staging disk.
    for forbidden in (
        "compose_exec clickhouse",
        "clickhouse-client",
        "BACKUP DATABASE",
        "clickhouse_rows.tsv",
        "clickhouse_soymutdb.zip",
    ):
        assert forbidden not in backup, forbidden
    assert "/var/lib/clickhouse-backups/" in restore


def test_backup_scripts_do_not_require_clickhouse_by_default() -> None:
    backup = BACKUP.read_text(encoding="utf-8")
    restore = RESTORE.read_text(encoding="utf-8")
    verify = VERIFY.read_text(encoding="utf-8")

    # The PostgreSQL client routing is shared by the three scripts, so the
    # compose path is asserted where it now lives as well as in the caller.
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "compose_exec postgres" in backup or "compose_exec postgres" in runtime
    assert "compose_exec postgres" in restore or "compose_exec postgres" in runtime
    assert '"format_version": 3' in backup
    assert "postgres_s3_current_versions" in backup
    assert "required S3 bucket mirror failed" in backup
    assert "--allow-legacy-v2" in restore and "--allow-legacy-v2" in verify


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
    assert 'keep["${name}"]="no-complete-marker"' in script
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
        tmp_path, component_statuses={"s3": "backup-failed"}
    )
    result = _run(["bash", str(RESTORE), "--target", "drill", str(archive)])

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "s3" in output.lower() and "status" in output.lower()
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
        ("postgresql", {"pg_rows": "public.items;DROP TABLE users\t1\n"}, False),
        (
            "clickhouse",
            {
                "format_version": 2,
                "clickhouse_rows": "facts" + chr(96) + "; DROP DATABASE soymutdb\t1\t1\n",
            },
            True,
        ),
    )
    for index, (label, overrides, legacy) in enumerate(cases):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        archive = _make_backup_archive(case_dir, **overrides)
        command = ["bash", str(VERIFY)]
        if legacy:
            command.append("--allow-legacy-v2")
        result = _run([*command, str(archive)], env={"CLICKHOUSE_HOST": "ch-drill.invalid"})

        assert result.returncode != 0
        output = result.stdout + result.stderr
        assert "snapshot" in output.lower() and "identifier" in output.lower()
        assert label in output.lower()


def test_verify_rejects_internal_artifact_checksum_mismatch(tmp_path: Path) -> None:
    archive = _make_backup_archive(
        tmp_path, corrupt_after_manifest="postgres.dump"
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


def _read_archive_manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as handle:
        member = next(m for m in handle.getmembers() if m.name.endswith("/manifest.json"))
        extracted = handle.extractfile(member)
        assert extracted is not None
        return json.loads(extracted.read().decode("utf-8"))


def _archive_members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as handle:
        return {m.name for m in handle.getmembers()}


def _archive_root(archive: Path) -> str:
    with tarfile.open(archive, "r:gz") as handle:
        return handle.getmembers()[0].name.split("/", 1)[0]


def test_backup_publishes_native_postgres_and_s3_format_v3(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Backup Complete" in result.stdout

    archives = list((tmp_path / "backups").glob("*.tar.gz"))
    assert len(archives) == 1
    archive = archives[0]

    manifest = _read_archive_manifest(archive)
    assert manifest["format_version"] == 3
    assert manifest["consistency"] == {
        "mode": "writers_quiesced",
        "scope": "postgres_s3_current_versions",
    }
    assert set(manifest["components"]) == {"postgres", "s3"}
    assert manifest["components"]["postgres"]["tables"] == 1
    assert manifest["components"]["s3"]["object_count"] == len(REQUIRED_BUCKETS)
    assert manifest["components"]["s3"]["checksum_algorithm"] == "sha256"
    assert "clickhouse" not in json.dumps(manifest).lower()

    names = _archive_members(archive)
    assert any(name.endswith("/postgres.dump") for name in names)
    assert not any("clickhouse" in name for name in names)
    assert not any(name.endswith("/pg_tables.list") for name in names)

    assert Path(f"{archive}.sha256").is_file()
    assert Path(f"{archive}.complete").is_file()
    metric = (tmp_path / "metrics" / "soymutdb_backup.prom").read_text(encoding="utf-8")
    assert "soymutdb_backup_status 1" in metric


def test_backup_v3_covers_every_required_bucket_and_policy(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")
    result = _run(["bash", str(BACKUP)], env=env)
    assert result.returncode == 0, result.stdout + result.stderr

    archive = next((tmp_path / "backups").glob("*.tar.gz"))
    names = _archive_members(archive)
    root = _archive_root(archive)
    for bucket in REQUIRED_BUCKETS:
        assert f"{root}/s3_data/{bucket}/payload.bin" in names
        assert f"{root}/s3_policy_{bucket}.json" in names
        assert f"{root}/s3_data/{bucket}" in names

    manifest = _read_archive_manifest(archive)
    assert manifest["components"]["s3"]["total_bytes"] == sum(
        len(f"object-{index}".encode()) for index in range(len(REQUIRED_BUCKETS))
    )


def test_backup_fails_when_an_s3_component_cannot_be_captured(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    env["BACKUP_METRICS_DIR"] = str(tmp_path / "metrics")
    broken_bin = tmp_path / "broken-bin"
    broken_bin.mkdir()
    _write_executable(broken_bin / "mc", "exit 33")
    env["PATH"] = f"{broken_bin}{os.pathsep}{env['PATH']}"

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Backup Complete" not in output
    assert not list((tmp_path / "backups").glob("*.tar.gz"))
    metric = (tmp_path / "metrics" / "soymutdb_backup.prom").read_text(encoding="utf-8")
    assert "soymutdb_backup_status 0" in metric


def test_backup_publishes_the_offsite_disaster_recovery_copy(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")
    result = _run(["bash", str(BACKUP)], env={**env, **_offsite_environment(tmp_path)})

    assert result.returncode == 0, result.stdout + result.stderr
    archive = next((tmp_path / "backups").glob("*.tar.gz"))
    offsite = tmp_path / "mc-store" / "offsite" / "dr-backups"
    published = offsite / archive.name
    assert published.is_file()
    assert _sha256(published) == _sha256(archive)
    assert (offsite / f"{archive.name}.sha256").is_file()
    assert (offsite / f"{archive.name}.complete").is_file()
    assert not any((offsite / ".staging").glob("*")) if (offsite / ".staging").exists() else True
    assert (offsite / f"{archive.name.removesuffix('.tar.gz')}.manifest.json").is_file()


def test_backup_output_never_prints_s3_credentials(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")
    result = _run(["bash", str(BACKUP)], env={**env, **_offsite_environment(tmp_path)})

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for secret in (
        "not-a-real-access-key",
        "not-a-real-secret-key",
        "offsite-key",
        "offsite-secret",
    ):
        assert secret not in output
    for artifact in (tmp_path / "backups").rglob("*"):
        if artifact.is_file():
            blob = artifact.read_bytes()
            assert b"not-a-real-secret-key" not in blob
            assert b"offsite-secret" not in blob


def test_restore_and_verify_refuse_legacy_v2_without_an_explicit_flag(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)

    for command in (
        ["bash", str(RESTORE), "--target", "drill", str(archive)],
        ["bash", str(VERIFY), str(archive)],
    ):
        result = _run(command)
        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "--allow-legacy-v2" in output


def test_verify_legacy_v2_fails_when_the_clickhouse_component_is_unreachable(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)

    without_host = _run(["bash", str(VERIFY), "--allow-legacy-v2", str(archive)])
    assert without_host.returncode != 0
    assert "clickhouse" in (without_host.stdout + without_host.stderr).lower()

    env = _verification_env(tmp_path)
    without_service = _run(
        ["bash", str(VERIFY), "--allow-legacy-v2", str(archive)], env=env
    )
    assert without_service.returncode != 0
    assert "compose" in (without_service.stdout + without_service.stderr).lower()


def test_restore_legacy_v2_fails_when_the_target_has_no_clickhouse_service(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)
    target = _drill_target_config(tmp_path, clickhouse=True)
    env = _native_backup_environment(tmp_path)
    env["FAKE_COMPOSE_SERVICES"] = "postgres api worker-default beat"

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--allow-legacy-v2",
            "--target",
            "drill",
            "--target-config",
            str(target),
            str(archive),
        ],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "clickhouse" in output.lower()
    assert "cannot continue" in output.lower()


def test_restore_legacy_v2_still_restores_clickhouse_when_explicitly_asked(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)
    target = _drill_target_config(tmp_path, clickhouse=True)
    env = _native_backup_environment(tmp_path)
    env["FAKE_COMPOSE_SERVICES"] = (
        "postgres clickhouse api worker-default worker-blast worker-ingest beat"
    )

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--allow-legacy-v2",
            "--target",
            "drill",
            "--target-config",
            str(target),
            str(archive),
        ],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ClickHouse database restore complete" in output
    assert "verify-restore.sh --allow-legacy-v2" in output


def test_verify_legacy_v2_checks_clickhouse_when_explicitly_asked(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)
    env = _native_backup_environment(tmp_path)
    env["CLICKHOUSE_HOST"] = "localhost"
    env["FAKE_COMPOSE_SERVICES"] = "postgres clickhouse"
    _seed_restored_target(tmp_path / "mc-store")

    result = _run(
        ["bash", str(VERIFY), "--allow-legacy-v2", str(archive)], env=env
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ClickHouse variant_facts rows=1" in result.stdout
    assert "ClickHouse variant_facts partitions=1" in result.stdout
    assert "FAIL: 0" in output


def test_verify_legacy_v2_reports_a_clickhouse_row_mismatch(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path, format_version=2)
    env = _native_backup_environment(tmp_path)
    env["CLICKHOUSE_HOST"] = "localhost"
    env["FAKE_COMPOSE_SERVICES"] = "postgres clickhouse"
    env["FAKE_CLICKHOUSE_ROW_COUNT"] = "9"
    _seed_restored_target(tmp_path / "mc-store")

    result = _run(
        ["bash", str(VERIFY), "--allow-legacy-v2", str(archive)], env=env
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE VERIFICATION FAILED" in output
    assert "ClickHouse variant_facts rows (expected 1, got 9)" in output


def _drill_target_config(tmp_path: Path, *, clickhouse: bool) -> Path:
    compose = tmp_path / "drill-compose.yml"
    compose.write_text("services:\n  postgres:\n    image: drill/postgres\n", encoding="utf-8")
    lines = [
        "RESTORE_TARGET_ID=drill",
        "RESTORE_TARGET_ISOLATED=1",
        f"RESTORE_COMPOSE_FILE={compose}",
        "RESTORE_COMPOSE_PROJECT=soymutdb-drill",
        "RESTORE_POSTGRES_HOST=pg-drill.invalid",
        "RESTORE_POSTGRES_PORT=5432",
        "RESTORE_POSTGRES_USER=soymutdb",
        "RESTORE_POSTGRES_DB=soymutdb",
        "RESTORE_POSTGRES_PASSWORD=not-a-real-secret",
        "RESTORE_S3_ENDPOINT=http://localhost:9001",
        "RESTORE_S3_ACCESS_KEY=drill",
        "RESTORE_S3_SECRET_KEY=not-a-real-secret",
        "RESTORE_WRITES_QUIESCED=1",
    ]
    if clickhouse:
        lines += ["RESTORE_CLICKHOUSE_HOST=localhost", "RESTORE_CLICKHOUSE_USER=soymutdb"]
    target = tmp_path / "drill.env"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_restore_v3_restores_postgres_and_s3_into_an_isolated_drill(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path)
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)
    env["RESTORE_S3_ENDPOINT"] = "http://localhost:9001"

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--target",
            "drill",
            "--target-config",
            str(target),
            str(archive),
        ],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Restore Complete" in output
    assert "clickhouse" not in output.lower()
    assert "verify-restore.sh" in output
    assert not (tmp_path / "backups" / "restore-drill.incomplete").exists()

    restored = tmp_path / "mc-store" / "s3dst"
    for bucket in REQUIRED_BUCKETS:
        assert (restored / bucket).is_dir()


def test_restore_v3_marks_the_drill_incomplete_when_a_component_fails(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path)
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)
    broken_bin = tmp_path / "broken-bin"
    broken_bin.mkdir()
    _write_executable(broken_bin / "pg_restore", "exit 47")
    env["PATH"] = f"{broken_bin}{os.pathsep}{env['PATH']}"

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--target",
            "drill",
            "--target-config",
            str(target),
            str(archive),
        ],
        env=env,
        stdin="y\n",
    )

    assert result.returncode != 0
    assert "Restore Complete" not in result.stdout
    state = tmp_path / "backups" / "restore-drill.incomplete"
    assert state.is_file()
    assert "backup_id=fixture-backup" in state.read_text(encoding="utf-8")


def test_verify_v3_checks_postgres_and_s3_without_clickhouse(tmp_path: Path) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")
    backup_result = _run(["bash", str(BACKUP)], env=env)
    assert backup_result.returncode == 0, backup_result.stdout + backup_result.stderr
    archive = next((tmp_path / "backups").glob("*.tar.gz"))
    _seed_restored_target(tmp_path / "mc-store")

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL CHECKS PASSED" in output
    assert "clickhouse" not in output.lower()
    for bucket in REQUIRED_BUCKETS:
        assert f"S3 {bucket} object count=1" in result.stdout
        assert f"S3 {bucket} bytes=" in result.stdout
    assert "FAIL: 0" in output


def test_verify_v3_reports_a_real_postgres_row_mismatch(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path, pg_rows="public.items\t7\n")
    env = _native_backup_environment(tmp_path)

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE VERIFICATION FAILED" in output
    assert "expected 7" in output


def test_verify_v3_detects_a_tampered_s3_object(tmp_path: Path) -> None:
    archive = _make_backup_archive(
        tmp_path, s3_objects={"genomic-data": {"payload.bin": b"original-payload"}}
    )
    extracted = tmp_path / "extract"
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(extracted)
    target = extracted / "fixture-backup/s3_data/genomic-data/payload.bin"
    assert target.is_file()
    target.write_bytes(b"tampered-payload")

    manifest_path = extracted / "fixture-backup" / "artifact_checksums.tsv"
    rows = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, size, relative = line.split("\t")
        if relative == "s3_data/genomic-data/payload.bin":
            digest = _sha256(target)
            size = str(target.stat().st_size)
        rows.append(f"{digest}\t{size}\t{relative}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    manifest_file = extracted / "fixture-backup" / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["artifact_manifest"]["size"] = manifest_path.stat().st_size
    manifest["artifact_manifest"]["sha256"] = _sha256(manifest_path)
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as handle:
        handle.add(extracted / "fixture-backup", arcname="fixture-backup")
    Path(f"{tampered}.sha256").write_text(
        f"{_sha256(tampered)}  {tampered.name}\n", encoding="utf-8"
    )
    Path(f"{tampered}.complete").write_text(
        f"backup_id=fixture-backup\nsha256={_sha256(tampered)}\n", encoding="utf-8"
    )

    env = _native_backup_environment(tmp_path)
    result = _run(["bash", str(VERIFY), str(tampered)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "checksum mismatch: genomic-data/payload.bin" in output


def test_backup_output_never_prints_s3_credentials_during_offsite_publish(
    tmp_path: Path,
) -> None:
    env = _native_backup_environment(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")
    result = _run(["bash", str(BACKUP)], env={**env, **_offsite_environment(tmp_path)})
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for secret in ("offsite-key", "offsite-secret"):
        assert secret not in output


# ---------------------------------------------------------------------------
# S3 bucket policy round trip
#
# A policy-less bucket exports an empty document, and MinIO refuses to accept
# that document back: `mc anonymous set-json` answers "Invalid policy version.
# Only 2012-10-17 is supported." The restore has to distinguish "no policy"
# from a real policy, and verification has to compare the policy that is
# actually on the target with the one in the archive.
# ---------------------------------------------------------------------------


def _policy_json(document: dict) -> str:
    return json.dumps(document, indent=2) + "\n"


def _apply_target_policy(store: Path, alias: str, bucket: str, document: dict) -> None:
    """Put a policy on the mock target the way `mc anonymous set-json` would."""
    path = store / "_policies" / alias / f"{bucket}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_policy_json(document), encoding="utf-8")


def _restore_command(archive: Path, target_config: Path) -> list[str]:
    return [
        "bash",
        str(RESTORE),
        "--target",
        "drill",
        "--target-config",
        str(target_config),
        str(archive),
    ]


def test_restore_resets_a_policy_less_bucket_with_anonymous_set_none(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path)
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)

    result = _run(_restore_command(archive, target), env=env, stdin="y\n")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Restore Complete" in output
    # An empty archived policy is a reset, never a set-json of an empty file.
    assert _policy_invocations(tmp_path, "set-json") == []
    resets = _policy_invocations(tmp_path, "set none")
    for bucket in REQUIRED_BUCKETS:
        assert any(line.endswith(f"s3dst/{bucket}") for line in resets), bucket
    assert _target_policy(tmp_path / "mc-store", "s3dst", "genomic-data") is None


def test_restore_treats_a_version_with_empty_statement_as_no_policy(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(
        tmp_path,
        policies={bucket: _policy_json(EMPTY_STATEMENT_POLICY) for bucket in REQUIRED_BUCKETS},
    )
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)

    result = _run(_restore_command(archive, target), env=env, stdin="y\n")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert _policy_invocations(tmp_path, "set-json") == []
    for bucket in REQUIRED_BUCKETS:
        assert any(
            line.endswith(f"s3dst/{bucket}")
            for line in _policy_invocations(tmp_path, "set none")
        ), bucket


def test_restore_applies_a_real_policy_with_set_json_and_keeps_unknown_fields(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(
        tmp_path, policies={"genomic-data": _policy_json(VALID_POLICY)}
    )
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)

    result = _run(_restore_command(archive, target), env=env, stdin="y\n")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    applied = _policy_invocations(tmp_path, "set-json")
    assert [line for line in applied if line.endswith("s3dst/genomic-data")]
    # Every other bucket is policy-less in this archive and gets reset.
    for bucket in REQUIRED_BUCKETS:
        if bucket == "genomic-data":
            continue
        assert any(
            line.endswith(f"s3dst/{bucket}")
            for line in _policy_invocations(tmp_path, "set none")
        ), bucket
    stored = _target_policy(tmp_path / "mc-store", "s3dst", "genomic-data")
    assert stored == VALID_POLICY
    assert stored["SoyMutDBProbeField"] == "keep-me"


def test_restore_does_not_swallow_a_policy_write_failure(tmp_path: Path) -> None:
    archive = _make_backup_archive(
        tmp_path, policies={"genomic-data": _policy_json(VALID_POLICY)}
    )
    target = _drill_target_config(tmp_path, clickhouse=False)
    env = _native_backup_environment(tmp_path)
    env["FAKE_MC_FAIL_SET_JSON"] = "1"

    result = _run(_restore_command(archive, target), env=env, stdin="y\n")

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Restore Complete" not in output
    assert "policy" in output.lower()
    state = tmp_path / "backups" / "restore-drill.incomplete"
    assert state.is_file()


def test_verify_compares_the_target_policy_with_the_archived_policy(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(
        tmp_path, policies={"genomic-data": _policy_json(VALID_POLICY)}
    )
    env = _native_backup_environment(tmp_path)
    _seed_restored_target(tmp_path / "mc-store")
    _apply_target_policy(tmp_path / "mc-store", "s3dst", "genomic-data", VALID_POLICY)

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL CHECKS PASSED" in output
    assert "EXPLICIT SKIP: 0" in output


def test_verify_fails_when_the_target_policy_differs(tmp_path: Path) -> None:
    archive = _make_backup_archive(tmp_path)
    env = _native_backup_environment(tmp_path)
    _seed_restored_target(tmp_path / "mc-store")
    # The archived bucket has no policy; the target grants anonymous reads.
    _apply_target_policy(tmp_path / "mc-store", "s3dst", "genomic-data", VALID_POLICY)

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE VERIFICATION FAILED" in output
    assert "ALL CHECKS PASSED" not in output
    assert "genomic-data" in output
    assert "policy" in output.lower()
    assert "EXPLICIT SKIP: 0" in output


def test_verify_treats_an_empty_statement_policy_as_equivalent_to_no_policy(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path)
    env = _native_backup_environment(tmp_path)
    _seed_restored_target(tmp_path / "mc-store")
    for bucket in REQUIRED_BUCKETS:
        _apply_target_policy(
            tmp_path / "mc-store", "s3dst", bucket, EMPTY_STATEMENT_POLICY
        )

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL CHECKS PASSED" in output


def test_verify_fails_closed_when_the_target_policy_cannot_be_read(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(tmp_path)
    env = _native_backup_environment(tmp_path)
    _seed_restored_target(tmp_path / "mc-store")
    env["FAKE_MC_FAIL_GET_JSON"] = "1"

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE VERIFICATION FAILED" in output
    assert "ALL CHECKS PASSED" not in output
    # A policy that cannot be read is a failure, never a skip.
    assert "EXPLICIT SKIP: 0" in output


def test_verify_detects_a_missing_unknown_field_in_the_target_policy(
    tmp_path: Path,
) -> None:
    archive = _make_backup_archive(
        tmp_path, policies={"genomic-data": _policy_json(VALID_POLICY)}
    )
    env = _native_backup_environment(tmp_path)
    _seed_restored_target(tmp_path / "mc-store")
    stripped = {key: value for key, value in VALID_POLICY.items() if key != "SoyMutDBProbeField"}
    _apply_target_policy(tmp_path / "mc-store", "s3dst", "genomic-data", stripped)

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE VERIFICATION FAILED" in output
    assert "genomic-data" in output

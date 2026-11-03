"""Contracts for the explicit native (non-Docker) backup runtime.

The default runtime stays ``compose``; ``SOYMUTDB_BACKUP_RUNTIME=native`` (or
``--runtime native``) is the only way to run without Docker. These cases pin
the routing, the fail-closed gates, and the isolation rules that make that
runtime safe to use on a host deployment.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPTS = ROOT / "deploy/scripts"
BACKUP = DEPLOY_SCRIPTS / "backup.sh"
RESTORE = DEPLOY_SCRIPTS / "restore.sh"
VERIFY = DEPLOY_SCRIPTS / "verify-restore.sh"
RUNTIME = DEPLOY_SCRIPTS / "backup-runtime.sh"
COMPOSE = ROOT / "docker-compose.yml"

REQUIRED_BUCKETS = (
    "genomic-data",
    "user-tracks",
    "blast-dbs",
    "exports",
    "gwas",
    "analyses",
)

SCRIPTS_TO_COPY = (
    "backup.sh",
    "restore.sh",
    "verify-restore.sh",
    "mc-auth.sh",
    "backup-runtime.sh",
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


# Records every invocation so a case can prove Docker was never touched, and
# answers the psql calls the compose runtime routes at the postgres service.
FAKE_DOCKER = """
import os
import sys

marker = os.environ.get("FAKE_DOCKER_MARKER")
if marker:
    with open(marker, "a", encoding="utf-8") as handle:
        handle.write(" ".join(sys.argv[1:]) + "\\n")
if "psql" in sys.argv:
    sql = sys.argv[-1]
    if "pg_tables" in sql:
        for table in os.environ.get("FAKE_PG_TABLES", "public.items").split(","):
            print(table)
    elif "count(*)" in sql:
        print(os.environ.get("FAKE_PG_ROW_COUNT", "1"))
    raise SystemExit(0)
if "pg_dump" in sys.argv:
    # The compose runtime captures pg_dump stdout into the staging file.
    sys.stdout.buffer.write(b"fixture-postgres-dump")
    raise SystemExit(0)
raise SystemExit(0)
"""

# Records every invocation so a case can assert that the host PostgreSQL
# clients were used, and which host they were pointed at.
FAKE_PSQL = """
import os
import sys

log = os.environ.get("FAKE_PSQL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(sys.argv[1:]) + "\\n")

sql = sys.argv[-1]
if "pg_stat_activity" in sql:
    print(os.environ.get("FAKE_ACTIVE_SESSIONS", "0"))
elif sql.strip() == "SELECT 1":
    print("1")
elif "pg_tables" in sql:
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


def policy_path(alias, key):
    return policy_root / alias / (key + ".json")


def parse_uri(uri):
    alias, _, rest = uri.partition("/")
    return alias, rest.strip("/")


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
                target = destination / path.relative_to(root)
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
                out = target / path.relative_to(source)
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


def _tool_bin(tmp_path: Path, *, with_mc: bool = True, with_psql: bool = True) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    _write_python_executable(fake_bin / "docker", FAKE_DOCKER)
    if with_psql:
        _write_python_executable(fake_bin / "psql", FAKE_PSQL)
        _write_python_executable(fake_bin / "pg_dump", FAKE_PG_DUMP)
        for name in ("pg_restore", "dropdb", "createdb"):
            _write_executable(fake_bin / name, "exit 0")
    if with_mc:
        _write_python_executable(fake_bin / "mc", FAKE_MC)
    return fake_bin


def _seed_source_bucket(store: Path, alias: str = "s3src") -> int:
    objects = 0
    for index, bucket in enumerate(REQUIRED_BUCKETS):
        target = store / alias / bucket
        target.mkdir(parents=True, exist_ok=True)
        (target / "payload.bin").write_bytes(f"object-{index}".encode())
        objects += 1
    return objects


def _seed_restored_target(store: Path) -> None:
    for bucket in REQUIRED_BUCKETS:
        source = store / "s3src" / bucket
        target = store / "s3dst" / bucket
        target.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)


def _env(tmp_path: Path, fake_bin: Path, **extra: str) -> dict[str, str]:
    (tmp_path / "mc-store").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_MC_STORE": str(tmp_path / "mc-store"),
        "FAKE_MC_LOG": str(tmp_path / "mc-invocations.log"),
        "FAKE_DOCKER_MARKER": str(tmp_path / "docker-was-called"),
        "FAKE_MC_FAIL_GET_JSON": "",
        "FAKE_MC_FAIL_SET_JSON": "",
        "FAKE_PSQL_LOG": str(tmp_path / "psql-calls.log"),
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "55432",
        "POSTGRES_USER": "soymutdb",
        "POSTGRES_DB": "soymutdb",
        "POSTGRES_PASSWORD": "not-a-real-secret",
        "S3_ENDPOINT": "http://127.0.0.1:59000",
        "S3_ACCESS_KEY": "not-a-real-access-key",
        "S3_SECRET_KEY": "not-a-real-secret-key",
        "BAK_BASE_DIR": str(tmp_path / "backups"),
        "BACKUP_METRICS_DIR": str(tmp_path / "metrics"),
        "BACKUP_WRITES_QUIESCED": "1",
        "SOYMUTDB_BACKUP_RUNTIME": "native",
        "SOYMUTDB_NATIVE_WRITES_STOPPED": "1",
        "BAK_S3_BUCKETS": " ".join(REQUIRED_BUCKETS),
        "SOYMUTDB_BACKUP_REPO_ENV": "0",
    }
    env.update(extra)
    return env


def _run(command, *, env=None, stdin="", cwd=ROOT) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=merged,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _archive_manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as handle:
        member = next(m for m in handle.getmembers() if m.name.endswith("/manifest.json"))
        extracted = handle.extractfile(member)
        assert extracted is not None
        return json.loads(extracted.read().decode("utf-8"))


def _only_archive(tmp_path: Path) -> Path:
    archives = list((tmp_path / "backups").glob("*.tar.gz"))
    assert len(archives) == 1, archives
    return archives[0]


def _psql_calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "psql-calls.log"
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


def _native_target_config(
    tmp_path: Path,
    *,
    target: str = "drill",
    attest_runtime: bool = True,
    instance_id: str | None = "drill-1",
    compose_file: str | None = None,
    database: str = "soymutdb_drill",
) -> Path:
    lines = [
        f"RESTORE_TARGET_ID={target}",
        "RESTORE_TARGET_ISOLATED=1",
        "RESTORE_POSTGRES_HOST=127.0.0.1",
        "RESTORE_POSTGRES_PORT=55433",
        "RESTORE_POSTGRES_USER=soymutdb",
        f"RESTORE_POSTGRES_DB={database}",
        "RESTORE_POSTGRES_PASSWORD=not-a-real-secret",
        "RESTORE_S3_ENDPOINT=http://127.0.0.1:59010",
        "RESTORE_S3_ACCESS_KEY=drill",
        "RESTORE_S3_SECRET_KEY=not-a-real-secret",
        "RESTORE_WRITES_QUIESCED=1",
        "SOYMUTDB_NATIVE_WRITES_STOPPED=1",
    ]
    if attest_runtime:
        lines.append("RESTORE_TARGET_RUNTIME=native")
    if instance_id is not None:
        lines.append(f"RESTORE_NATIVE_INSTANCE_ID={instance_id}")
    if compose_file is not None:
        lines.append(f"RESTORE_COMPOSE_FILE={compose_file}")
        lines.append("RESTORE_COMPOSE_PROJECT=soymutdb-drill")
    config = tmp_path / f"{target}-native.env"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _fixture_archive(tmp_path: Path, *, format_version: int = 3) -> Path:
    source = tmp_path / "fixture-backup"
    (source / "s3_data").mkdir(parents=True)
    files = {
        "postgres.dump": b"fixture-postgres-dump",
        "pg_rows.tsv": b"public.items\t1\n",
        "s3_buckets.txt": ("\n".join(REQUIRED_BUCKETS) + "\n").encode(),
        "s3_manifest.tsv": b"",
    }
    for bucket in REQUIRED_BUCKETS:
        (source / "s3_data" / bucket).mkdir()
        (source / "s3_data" / bucket / "payload.bin").write_bytes(b"object")
        files[f"s3_policy_{bucket}.json"] = b"{}\n"
    for relative, content in files.items():
        (source / relative).write_bytes(content)

    rows = []
    for bucket in REQUIRED_BUCKETS:
        path = source / "s3_data" / bucket / "payload.bin"
        rows.append(f"{bucket}\tpayload.bin\t{path.stat().st_size}\t{_sha256(path)}\n")
    (source / "s3_manifest.tsv").write_text("".join(sorted(rows)), encoding="utf-8")

    artifact_lines = []
    for path in sorted(source.rglob("*")):
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            artifact_lines.append(f"{_sha256(path)}\t{path.stat().st_size}\t{relative}\n")
    artifact_manifest = source / "artifact_checksums.tsv"
    artifact_manifest.write_text("".join(artifact_lines), encoding="utf-8")

    components = {
        "postgres": {
            "status": "ok",
            "file": "postgres.dump",
            "row_counts_file": "pg_rows.tsv",
            "tables": 1,
        },
        "s3": {
            "status": "ok",
            "manifest_file": "s3_manifest.tsv",
            "buckets_file": "s3_buckets.txt",
            "object_count": len(rows),
            "total_bytes": sum(int(row.split("\t")[2]) for row in rows),
            "checksum_algorithm": "sha256",
        },
    }
    if format_version == 2:
        (source / "clickhouse_soymutdb.zip").write_bytes(b"fixture-clickhouse")
        (source / "clickhouse_rows.tsv").write_text("variant_facts\t1\t1\n", encoding="utf-8")
        components["clickhouse"] = {
            "status": "ok",
            "file": "clickhouse_soymutdb.zip",
            "row_counts_file": "clickhouse_rows.tsv",
            "tables": 1,
        }
    manifest = {
        "format_version": format_version,
        "backup_id": "fixture-backup",
        "created_at": "2026-10-16T00:00:00Z",
        "consistency": {"mode": "writers_quiesced"},
        "runtime": {
            "mode": "native",
            "postgres_client": "native-postgres-client",
            "s3_client": "native-mc",
            "writers_attestation": "declared-native-quiescence",
        },
        "components": components,
        "artifact_manifest": {
            "file": "artifact_checksums.tsv",
            "size": artifact_manifest.stat().st_size,
            "sha256": _sha256(artifact_manifest),
        },
    }
    (source / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    archive = tmp_path / "fixture-backup.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname=source.name)
    Path(f"{archive}.sha256").write_text(
        f"{_sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )
    Path(f"{archive}.complete").write_text(
        f"backup_id=fixture-backup\nsha256={_sha256(archive)}\n", encoding="utf-8"
    )
    return archive


# --- shared routing --------------------------------------------------------

def test_all_three_scripts_source_the_shared_runtime_library() -> None:
    assert RUNTIME.is_file()
    for script in (BACKUP, RESTORE, VERIFY):
        body = script.read_text(encoding="utf-8")
        assert 'source "${SCRIPT_DIR}/backup-runtime.sh"' in body, script.name
        assert "backup_runtime_require" in body, script.name
        assert "SOYMUTDB_BACKUP_RUNTIME" in body, script.name
        # The runtime, not the hostname, decides the PostgreSQL client.
        assert 'if [[ "${PG_HOST}" == "localhost"' not in body, script.name


def test_runtime_library_keeps_the_native_gates_fail_closed() -> None:
    body = RUNTIME.read_text(encoding="utf-8")
    assert "pg_stat_activity" in body
    assert "SOYMUTDB_NATIVE_WRITES_STOPPED" in body
    assert "never falls back to the minio/mc container" in body
    # The native branch must never reach the container image.
    native_branch = body.split("elif backup_runtime_is_native; then")[1].split("else")[0]
    assert "docker" not in native_branch


# --- runtime selection -----------------------------------------------------

def test_default_runtime_is_compose_and_keeps_the_loopback_compose_route(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, SOYMUTDB_BACKUP_RUNTIME="")
    env.pop("SOYMUTDB_BACKUP_RUNTIME")
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = _archive_manifest(_only_archive(tmp_path))
    assert manifest["runtime"] == {
        "mode": "compose",
        "postgres_client": "compose-postgres-service",
        "s3_client": "mc-or-container",
        "writers_attestation": "compose-service-state",
    }
    # A loopback PostgreSQL host keeps going through the compose service.
    assert _psql_calls(tmp_path) == []
    assert (tmp_path / "docker-was-called").is_file()


def test_native_runtime_uses_host_clients_even_on_loopback(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert not (tmp_path / "docker-was-called").exists(), (
        "the native runtime must not reach for Docker on a loopback host"
    )
    calls = _psql_calls(tmp_path)
    assert any("-h" in call and "127.0.0.1" in call for call in calls)
    manifest = _archive_manifest(_only_archive(tmp_path))
    assert manifest["runtime"]["mode"] == "native"
    assert manifest["runtime"]["postgres_client"] == "native-postgres-client"
    assert manifest["runtime"]["s3_client"] == "native-mc"


def test_runtime_flag_selects_native_without_the_environment_variable(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    env.pop("SOYMUTDB_BACKUP_RUNTIME")
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP), "--runtime", "native"], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _archive_manifest(_only_archive(tmp_path))["runtime"]["mode"] == "native"


def test_unsupported_runtime_value_fails_closed(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    _seed_source_bucket(tmp_path / "mc-store")

    for override in (
        {"SOYMUTDB_BACKUP_RUNTIME": "docker"},
        {"SOYMUTDB_BACKUP_RUNTIME": "host"},
        {"SOYMUTDB_BACKUP_RUNTIME": ""},
    ):
        env = _env(tmp_path, fake_bin, **override)
        if not override["SOYMUTDB_BACKUP_RUNTIME"]:
            env.pop("SOYMUTDB_BACKUP_RUNTIME")
        result = _run(["bash", str(BACKUP), "--runtime", "kubernetes"], env=env)
        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "kubernetes" in output
        assert "compose native" in output
        assert not (tmp_path / "docker-was-called").exists()
        assert not list((tmp_path / "backups").glob("*.tar.gz"))


def test_unsupported_runtime_value_is_rejected_by_restore_and_verify(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, SOYMUTDB_BACKUP_RUNTIME="postgres-direct")

    restore_result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config",
         str(_native_target_config(tmp_path)), str(archive)],
        env=env,
        stdin="y\n",
    )
    verify_result = _run(["bash", str(VERIFY), str(archive)], env=env)

    for result in (restore_result, verify_result):
        output = result.stdout + result.stderr
        assert result.returncode != 0
        assert "postgres-direct" in output
        assert "compose native" in output
    assert not (tmp_path / "docker-was-called").exists()


# --- missing tools ---------------------------------------------------------

def test_native_runtime_fails_without_mc_and_never_falls_back_to_docker(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path, with_mc=False)
    env = _env(tmp_path, fake_bin)
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "mc" in output
    assert "never falls back to the minio/mc container" in output
    assert not (tmp_path / "docker-was-called").exists()
    assert not list((tmp_path / "backups").glob("*.tar.gz"))
    metric = (tmp_path / "metrics" / "soymutdb_backup.prom").read_text(encoding="utf-8")
    assert "soymutdb_backup_status 0" in metric


def test_native_runtime_fails_without_the_host_postgres_clients(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path, with_psql=False)
    env = _env(tmp_path, fake_bin)
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "psql" in output
    assert "pg_dump" in output
    assert not (tmp_path / "docker-was-called").exists()


def test_native_verify_fails_without_mc(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path, with_mc=False)
    env = _env(tmp_path, fake_bin)

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "minio/mc container" in output
    assert not (tmp_path / "docker-was-called").exists()


# --- writer quiescence -----------------------------------------------------

def test_native_backup_requires_an_explicit_out_of_band_writer_attestation(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    env.pop("SOYMUTDB_NATIVE_WRITES_STOPPED")
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "SOYMUTDB_NATIVE_WRITES_STOPPED=1" in output
    assert not list((tmp_path / "backups").glob("*.tar.gz"))

    env["SOYMUTDB_NATIVE_WRITES_STOPPED"] = "0"
    again = _run(["bash", str(BACKUP)], env=env)
    assert again.returncode != 0
    assert "SOYMUTDB_NATIVE_WRITES_STOPPED=1" in again.stdout + again.stderr


def test_native_backup_still_requires_the_quiesced_writes_flag(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, BACKUP_WRITES_QUIESCED="0")
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "BACKUP_WRITES_QUIESCED=1" in output
    assert not list((tmp_path / "backups").glob("*.tar.gz"))


def test_native_backup_fails_while_a_writer_session_is_still_connected(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, FAKE_ACTIVE_SESSIONS="2")
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "2 writer session(s)" in output
    assert "Backup Complete" not in output
    assert not list((tmp_path / "backups").glob("*.tar.gz"))


# --- archive contract ------------------------------------------------------

def test_native_backup_keeps_checksums_buckets_and_attestation(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    object_count = _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    archive = _only_archive(tmp_path)
    manifest = _archive_manifest(archive)

    assert manifest["format_version"] == 3
    assert manifest["components"]["s3"]["object_count"] == object_count
    assert manifest["components"]["s3"]["checksum_algorithm"] == "sha256"
    assert manifest["consistency"]["mode"] == "writers_quiesced"
    assert manifest["runtime"]["writers_attestation"] == "declared-native-quiescence"

    with tarfile.open(archive, "r:gz") as handle:
        names = {member.name for member in handle.getmembers()}
    root = next(iter(names)).split("/", 1)[0]
    for bucket in REQUIRED_BUCKETS:
        assert f"{root}/s3_data/{bucket}/payload.bin" in names
        assert f"{root}/s3_policy_{bucket}.json" in names
    assert f"{root}/artifact_checksums.tsv" in names
    assert f"{root}/postgres.dump" in names

    assert Path(f"{archive}.sha256").is_file()
    assert Path(f"{archive}.complete").is_file()
    assert f"{_sha256(archive)}  {archive.name}\n" == Path(
        f"{archive}.sha256"
    ).read_text(encoding="utf-8")


def test_native_backup_never_leaks_credentials_into_output_or_artifacts(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    _seed_source_bucket(tmp_path / "mc-store")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    secrets = (b"not-a-real-access-key", b"not-a-real-secret-key")
    for secret in secrets:
        assert secret.decode() not in output
    for artifact in (tmp_path / "backups").rglob("*"):
        if artifact.is_file():
            blob = artifact.read_bytes()
            for secret in secrets:
                assert secret not in blob, artifact


# --- restore isolation -----------------------------------------------------

def test_native_restore_requires_an_explicit_target_runtime_attestation(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    config = _native_target_config(tmp_path, attest_runtime=False)

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_TARGET_RUNTIME=native" in output
    assert "Restore Complete" not in output
    assert not (tmp_path / "backups" / "restore-drill.incomplete").exists()


def test_native_restore_requires_an_isolated_native_instance_id(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)

    missing = _native_target_config(tmp_path, instance_id=None)
    without = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(missing), str(archive)],
        env=env,
        stdin="y\n",
    )
    assert without.returncode != 0
    assert "RESTORE_NATIVE_INSTANCE_ID" in without.stdout + without.stderr

    production = _native_target_config(tmp_path, target="drill2", instance_id="production")
    named_production = _run(
        ["bash", str(RESTORE), "--target", "drill2", "--target-config", str(production), str(archive)],
        env=env,
        stdin="y\n",
    )
    assert named_production.returncode != 0
    assert "must not name the production instance" in (
        named_production.stdout + named_production.stderr
    )


def test_native_restore_refuses_the_default_production_compose_file(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    config = _native_target_config(tmp_path, compose_file=str(COMPOSE))

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "default production compose file" in output
    assert not (tmp_path / "docker-was-called").exists()


def test_native_restore_completes_against_an_isolated_target(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    # Restore proves quiescence with RESTORE_WRITES_QUIESCED; it must never
    # depend on the backup-side BACKUP_WRITES_QUIESCED flag.
    env.pop("BACKUP_WRITES_QUIESCED")
    config = _native_target_config(tmp_path)

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Restore Complete (target: drill, runtime: native)" in output
    assert not (tmp_path / "backups" / "restore-drill.incomplete").exists()
    assert not (tmp_path / "docker-was-called").exists()
    assert "BACKUP_WRITES_QUIESCED" not in output
    restored = tmp_path / "mc-store" / "s3dst"
    for bucket in REQUIRED_BUCKETS:
        assert (restored / bucket).is_dir()
    # The fixture archives policy-less buckets, so the native restore has to
    # reset them instead of handing an empty document to set-json.
    log = tmp_path / "mc-invocations.log"
    invocations = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    assert not [line for line in invocations if line.startswith("anonymous set-json ")]
    for bucket in REQUIRED_BUCKETS:
        assert any(
            line.endswith(f"s3dst/{bucket}") and line.startswith("anonymous set none ")
            for line in invocations
        ), bucket
    # The target endpoint came from the target config, not from the environment.
    assert any("-h" in call and "127.0.0.1" in call for call in _psql_calls(tmp_path))


def test_native_restore_names_the_restore_quiesced_flag(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    config = _native_target_config(tmp_path)
    # The target config is the only place the drill flag is set.
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "RESTORE_WRITES_QUIESCED=1", "RESTORE_WRITES_QUIESCED=0"
        ),
        encoding="utf-8",
    )

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "RESTORE_WRITES_QUIESCED=1 is required" in output
    assert "Restore Complete" not in output
    assert not (tmp_path / "docker-was-called").exists()


def test_native_restore_still_requires_the_out_of_band_writer_attestation(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    # Neither the environment nor the target config may claim the writers are
    # stopped out of band.
    env.pop("SOYMUTDB_NATIVE_WRITES_STOPPED")
    config = _native_target_config(tmp_path)
    config.write_text(
        "\n".join(
            line
            for line in config.read_text(encoding="utf-8").splitlines()
            if not line.startswith("SOYMUTDB_NATIVE_WRITES_STOPPED")
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "SOYMUTDB_NATIVE_WRITES_STOPPED=1" in output
    assert "Restore Complete" not in output


def test_native_restore_fails_closed_while_a_writer_session_is_connected(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, FAKE_ACTIVE_SESSIONS="3")
    config = _native_target_config(tmp_path)

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "3 writer session(s)" in output
    assert "Restore Complete" not in output
    assert not (tmp_path / "backups" / "restore-drill.incomplete").exists()


def test_native_restore_marks_the_target_incomplete_when_a_component_fails(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    _write_executable(fake_bin / "pg_restore", "exit 47")
    env = _env(tmp_path, fake_bin)
    config = _native_target_config(tmp_path)

    result = _run(
        ["bash", str(RESTORE), "--target", "drill", "--target-config", str(config), str(archive)],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Restore Complete" not in output
    state = tmp_path / "backups" / "restore-drill.incomplete"
    assert state.is_file()
    assert "backup_id=fixture-backup" in state.read_text(encoding="utf-8")


def test_native_restore_refuses_a_legacy_v2_archive(tmp_path: Path) -> None:
    archive = _fixture_archive(tmp_path, format_version=2)
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    config = _native_target_config(tmp_path)

    result = _run(
        [
            "bash",
            str(RESTORE),
            "--allow-legacy-v2",
            "--target",
            "drill",
            "--target-config",
            str(config),
            str(archive),
        ],
        env=env,
        stdin="y\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "compose runtime" in output
    assert "Restore Complete" not in output


def test_native_restore_does_not_authorize_production_without_the_typed_word(
    tmp_path: Path,
) -> None:
    archive = _fixture_archive(tmp_path)
    fake_bin = _tool_bin(tmp_path)
    touched = tmp_path / "pg-tool-was-called"
    for name in ("dropdb", "createdb"):
        _write_executable(fake_bin / name, f"touch {touched}; exit 0")
    # Production restore still proves quiescence first; the typed confirmation
    # is what is under test here.
    env = _env(tmp_path, fake_bin, RESTORE_WRITES_QUIESCED="1")

    result = _run(
        ["bash", str(RESTORE), "--target", "prod", str(archive)],
        env=env,
        stdin="yes\n",
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "restore aborted" in output
    assert not touched.exists()
    assert not (tmp_path / "docker-was-called").exists()


# --- verification ----------------------------------------------------------

def test_native_verify_uses_host_clients_and_reports_the_archive_runtime(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    _seed_source_bucket(tmp_path / "mc-store")
    backup_result = _run(["bash", str(BACKUP)], env=env)
    assert backup_result.returncode == 0, backup_result.stdout + backup_result.stderr
    archive = _only_archive(tmp_path)
    (tmp_path / "psql-calls.log").unlink()
    _seed_restored_target(tmp_path / "mc-store")

    result = _run(["bash", str(VERIFY), str(archive)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL CHECKS PASSED" in output
    assert "Archive runtime: native" in output
    assert "declared-native-quiescence" in output
    assert "FAIL: 0" in output
    assert not (tmp_path / "docker-was-called").exists()
    assert any("-h" in call and "127.0.0.1" in call for call in _psql_calls(tmp_path))


# --- repository .env -------------------------------------------------------

def _fake_project(tmp_path: Path) -> Path:
    root = tmp_path / "fake-project"
    (root / "deploy/scripts").mkdir(parents=True)
    for name in SCRIPTS_TO_COPY:
        shutil.copy2(DEPLOY_SCRIPTS / name, root / "deploy/scripts" / name)
    (root / ".env").write_text(
        "POSTGRES_HOST=repo-env-host\nPOSTGRES_DB=repo_env_db\n", encoding="utf-8"
    )
    return root


def test_no_repo_env_option_keeps_the_repository_env_out_of_the_run(
    tmp_path: Path,
) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    env.pop("SOYMUTDB_BACKUP_REPO_ENV")
    _seed_source_bucket(tmp_path / "mc-store")
    project = _fake_project(tmp_path)

    inherited = _run(
        ["bash", str(project / "deploy/scripts/backup.sh")],
        env=env,
        cwd=tmp_path,
    )
    assert inherited.returncode == 0, inherited.stdout + inherited.stderr
    inherited_calls = "\n".join(_psql_calls(tmp_path))
    assert "repo-env-host" in inherited_calls
    assert _archive_manifest(_only_archive(tmp_path))["components"]["postgres"]["tables"] == 1

    (tmp_path / "psql-calls.log").unlink()
    isolated = _run(
        ["bash", str(project / "deploy/scripts/backup.sh"), "--no-repo-env"],
        env=env,
        cwd=tmp_path,
    )
    assert isolated.returncode == 0, isolated.stdout + isolated.stderr
    assert "repo-env-host" not in "\n".join(_psql_calls(tmp_path))


def test_back_to_back_runs_do_not_collide_on_a_second_stamped_backup_id(
    tmp_path: Path,
) -> None:
    """Two backups in the same wall second must not refuse to run.

    The backup id is `<timestamp>-<component hash>`, the timestamp has second
    resolution, and identical source data yields an identical component hash.
    A second run started inside the same second therefore built the very id the
    first run had just published and aborted with

        refusing to overwrite existing backup artifact: <id>.tar.gz

    against a file it had not created. This was flaky rather than deterministic
    because it depended on how long the harness took, which is why it surfaced
    as an intermittent contracts-suite failure. Runs are now serialised onto
    distinct seconds.
    """
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin)
    env.pop("SOYMUTDB_BACKUP_REPO_ENV")
    _seed_source_bucket(tmp_path / "mc-store")
    project = _fake_project(tmp_path)

    # Three runs in a row is the smallest count that exposes the collision: the
    # second run usually still lands in the next second, the third does not.
    for attempt in range(3):
        result = _run(
            ["bash", str(project / "deploy/scripts/backup.sh"), "--no-repo-env"],
            env=env,
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"run {attempt}: {result.stdout}{result.stderr}"

    archives = sorted((tmp_path / "backups").glob("*.tar.gz"))
    assert len(archives) == 3, [archive.name for archive in archives]
    ids = {archive.name.removesuffix(".tar.gz").rsplit("-", 1)[0] for archive in archives}
    assert len(ids) == 3, f"backup ids collided: {sorted(ids)}"


def test_repo_env_policy_rejects_an_ambiguous_value(tmp_path: Path) -> None:
    fake_bin = _tool_bin(tmp_path)
    env = _env(tmp_path, fake_bin, SOYMUTDB_BACKUP_REPO_ENV="maybe")

    result = _run(["bash", str(BACKUP)], env=env)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "SOYMUTDB_BACKUP_REPO_ENV must be 0 or 1" in output
    assert not (tmp_path / "docker-was-called").exists()

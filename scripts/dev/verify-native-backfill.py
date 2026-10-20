#!/usr/bin/env python3
"""Rehearse the native ClickHouse -> PostgreSQL backfill on isolated services.

Exercises the real tooling end to end against a throwaway PostgreSQL database
and a throwaway ClickHouse database. Nothing here is mocked:

    CH DDL taken from infra/clickhouse/init.sql  (26 columns, not a fixture)
      -> CH fixtures for v4, v5 and a second release
      -> soymutdb_worker.native_backfill dry-run      (writes nothing)
      -> --apply --source-frozen                        (verified transfer)
      -> app.scripts.verify_native_cutover              (cutover verdict)
      -> --apply again                                  (idempotent receipt)
      -> three rejections, each with the target unchanged

This is a rehearsal. It proves the transfer contract on data this script
created; it is not evidence that any production release has been backfilled.

Safety: refuses unless SOYMUTDB_APP_ENV=dev, PostgreSQL is loopback with a
database named "soymutdb_backfill_*", and ClickHouse is a loopback HTTP URL
whose database also starts with "soymutdb_backfill_".

Usage
    SOYMUTDB_APP_ENV=dev
    SOYMUTDB_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55448/soymutdb_backfill_20261017
    BACKFILL_CLICKHOUSE_URL=http://127.0.0.1:58123
    BACKFILL_CLICKHOUSE_DATABASE=soymutdb_backfill_rehearsal
    BACKFILL_CLICKHOUSE_USER=default
    BACKFILL_CLICKHOUSE_PASSWORD=
      python3.15 scripts/dev/verify-native-backfill.py \
        --evidence-out /tmp/backfill-rehearsal.json

Exit codes: 0 rehearsed, 1 rehearsal failed, 2 refused (unsafe config).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"
WORKER_SRC = REPO_ROOT / "apps" / "worker" / "src"
INIT_SQL = REPO_ROOT / "infra" / "clickhouse" / "init.sql"
sys.path.insert(0, str(WORKER_SRC))

from soymutdb_worker.tasks.variant_finalize import BASE_COLUMNS

BACKFILL_DB_PREFIX = "soymutdb_backfill_"

RELEASE_VERSION = "backfill-v5.0.0"
OTHER_RELEASE_VERSION = "backfill-v4.0.0"
ASSEMBLY_LABELS = {"backfill-v4": "v4", "backfill-v5": "v5"}

#: (release, assembly label, variant_id). Two assemblies for the target release
#: prove the namespace map; the second release proves the source query is
#: release-scoped and must not be swept in.
FACT_ROWS = [
    (RELEASE_VERSION, "backfill-v4", 2001),
    (RELEASE_VERSION, "backfill-v4", 2002),
    (RELEASE_VERSION, "backfill-v5", 2003),
    (RELEASE_VERSION, "backfill-v5", 2004),
    (RELEASE_VERSION, "backfill-v5", 2005),
    (OTHER_RELEASE_VERSION, "backfill-v4", 3001),
]
TARGET_RELEASE_ROWS = [row for row in FACT_ROWS if row[0] == RELEASE_VERSION]


class RehearsalError(Exception):
    """A rehearsal assertion failed; reported as evidence, not a traceback."""


def _is_loopback(host: str | None) -> bool:
    import ipaddress

    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _redact(value: Any, note: str) -> str:
    return f"<redacted: {note}>"


def ch_quote(value: str) -> str:
    """Quote a ClickHouse string literal. Refuses characters needing escapes so
    the fixture generator never hand-rolls escaping."""
    if any(char in value for char in ("'", "\\", "\n", "\r", "\t")):
        raise RehearsalError(f"fixture value {value!r} needs escaping")
    return f"'{value}'"


# --------------------------------------------------------------------------
# Safety guard
# --------------------------------------------------------------------------


def assert_isolated_target() -> dict[str, Any]:
    from sqlalchemy.engine import make_url

    if os.environ.get("SOYMUTDB_APP_ENV", "dev") != "dev":
        raise RehearsalError("SOYMUTDB_APP_ENV must be dev")

    database_url = make_url(os.environ["SOYMUTDB_DATABASE_URL"])
    if not _is_loopback(database_url.host):
        raise RehearsalError(f"database host {database_url.host!r} is not loopback")
    if not re.fullmatch(r"soymutdb_backfill_[A-Za-z0-9_]+", str(database_url.database or "")):
        raise RehearsalError(
            f"database name {database_url.database!r} must start with "
            f"{BACKFILL_DB_PREFIX!r}"
        )

    ch_url = os.environ["BACKFILL_CLICKHOUSE_URL"]
    ch_parts = urllib.parse.urlsplit(ch_url)
    if ch_parts.scheme != "http" or not _is_loopback(ch_parts.hostname):
        raise RehearsalError(
            f"BACKFILL_CLICKHOUSE_URL must be a loopback HTTP URL (got {ch_url!r})"
        )
    ch_database = os.environ["BACKFILL_CLICKHOUSE_DATABASE"]
    if not re.fullmatch(r"soymutdb_backfill_[A-Za-z0-9_]+", ch_database):
        raise RehearsalError(
            f"ClickHouse database {ch_database!r} must start with "
            f"{BACKFILL_DB_PREFIX!r}"
        )

    return {
        "app_env": "dev",
        "postgres": (
            f"{database_url.host}:{database_url.port or 5432}/{database_url.database}"
        ),
        "clickhouse": f"{ch_parts.hostname}:{ch_parts.port}",
        "clickhouse_database": ch_database,
    }


# --------------------------------------------------------------------------
# ClickHouse over HTTP
# --------------------------------------------------------------------------


def ch_post(sql: str, *, database: str | None = None, timeout: float = 180.0) -> str:
    """Send one statement to ClickHouse; parameters travel in the query string."""
    url = os.environ["BACKFILL_CLICKHOUSE_URL"]
    if database:
        url = f"{url}?{urllib.parse.urlencode({'database': database})}"
    request = urllib.request.Request(
        url,
        data=sql.encode("utf-8"),
        method="POST",
        headers={
            "X-ClickHouse-User": os.environ["BACKFILL_CLICKHOUSE_USER"],
            "X-ClickHouse-Key": os.environ["BACKFILL_CLICKHOUSE_PASSWORD"],
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def extract_variant_facts_ddl() -> str:
    """Take the real variant_facts DDL from init.sql.

    Reusing the shipped DDL is the point: a hand-written 20-column fixture
    would agree with a stale contract instead of proving the transfer reads
    the 26 columns the legacy store actually carries.
    """
    text = INIT_SQL.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS variant_facts \(.*?\)\s*ENGINE\s*=.*?;",
        text,
        re.DOTALL,
    )
    if match is None:
        raise RehearsalError("no variant_facts DDL block found in init.sql")
    ddl = match.group(0)

    declared = set(re.findall(r"^ {4}(\w+)\s+\w", ddl, re.MULTILINE))
    declared.discard("PARTITION")
    expected = set(BASE_COLUMNS)
    if declared != expected:
        raise RehearsalError(
            f"init.sql declares {len(declared)} columns, expected "
            f"{len(expected)}; missing={sorted(expected - declared)}, "
            f"unexpected={sorted(declared - expected)}"
        )
    if len(declared) != 26:
        raise RehearsalError(
            f"init.sql variant_facts has {len(declared)} columns, expected 26"
        )
    return ddl


def provision_clickhouse() -> dict[str, Any]:
    """Create the rehearsal database and the real variant_facts table."""
    database = os.environ["BACKFILL_CLICKHOUSE_DATABASE"]
    ch_post(f"CREATE DATABASE IF NOT EXISTS {database}")
    ddl = extract_variant_facts_ddl()
    ch_post(ddl, database=database)
    ch_post("TRUNCATE TABLE IF EXISTS variant_facts", database=database)
    return {
        "database": database,
        "ddl_source": str(INIT_SQL.relative_to(REPO_ROOT)),
        "ddl_columns": len(BASE_COLUMNS),
    }


def ch_fact_row(release: str, assembly: str, variant_id: int) -> str:
    """One ClickHouse row carrying every BASE_COLUMN with the right type."""
    values: dict[str, Any] = {
        "variant_id": variant_id,
        "release_key": release,
        "assembly_key": assembly,
        "chromosome": f"Chr{(variant_id % 4) + 1}",
        "position": 100000 + variant_id,
        "ref_allele": "A",
        "alt_allele": "T",
        "variant_type": "SNP",
        "variant_subtype": "",
        "length": 1,
        "gene_id": f"Glyma.05G{variant_id:010d}",
        "gene_symbol": f"GLYMA_{variant_id}",
        "gene_surrogate_id": variant_id % 97,
        "mutant_line_surrogate_id": variant_id % 31,
        "mutant_line_name": "",
        "consequence": "missense_variant",
        "consequence_id": variant_id % 11,
        "impact": "MODERATE",
        "rs_id": f"rs{variant_id}",
        "quality_score": 60.0,
        "filter_status": "PASS",
        "read_depth": 30,
        "allele_frequency": 0.25,
        "hgvs_c": f"c.{variant_id}A>T",
        "hgvs_p": "p.Met1Thr",
        "zygosity": "het",
    }
    missing = set(BASE_COLUMNS) - set(values)
    if missing:
        raise RehearsalError(f"fixture row is missing columns {sorted(missing)}")

    def render(name: str) -> str:
        value = values[name]
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return repr(value)
        return ch_quote(value)

    return "(" + ", ".join(render(name) for name in BASE_COLUMNS) + ")"


def seed_clickhouse() -> dict[str, Any]:
    database = os.environ["BACKFILL_CLICKHOUSE_DATABASE"]
    rows = [ch_fact_row(release, assembly, vid) for release, assembly, vid in FACT_ROWS]
    columns = ", ".join(BASE_COLUMNS)
    values = ", ".join(rows)
    ch_post(f"INSERT INTO variant_facts ({columns}) VALUES {values}", database=database)

    total = int(ch_post("SELECT count() FROM variant_facts", database=database).strip())
    scoped = ch_post(
        "SELECT count() FROM variant_facts WHERE release_key = "
        + ch_quote(RELEASE_VERSION),
        database=database,
    ).strip()
    return {
        "rows_inserted": len(rows),
        "clickhouse_total_rows": total,
        "clickhouse_target_release_rows": int(scoped),
        "expected_target_release_rows": len(TARGET_RELEASE_ROWS),
        "assemblies_seeded": sorted({row[1] for row in FACT_ROWS}),
        "releases_seeded": sorted({row[0] for row in FACT_ROWS}),
    }


# --------------------------------------------------------------------------
# PostgreSQL, via the worker's own psycopg2 driver
# --------------------------------------------------------------------------


def pg_connect(database: str | None = None) -> Any:
    import psycopg2
    from sqlalchemy.engine import make_url

    parsed = make_url(os.environ["SOYMUTDB_DATABASE_URL"])
    return psycopg2.connect(
        host=parsed.host,
        port=parsed.port or 5432,
        user=parsed.username or "postgres",
        password=parsed.password or "",
        dbname=database or parsed.database,
    )


def pg_url() -> str:
    """The sync URL the backfill CLI opens; it uses psycopg2, not asyncpg."""
    from sqlalchemy.engine import make_url

    parsed = make_url(os.environ["SOYMUTDB_DATABASE_URL"])
    return parsed.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


def create_pg_database() -> str:
    from sqlalchemy.engine import make_url

    name = make_url(os.environ["SOYMUTDB_DATABASE_URL"]).database
    connection = pg_connect("postgres")
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            existed = cursor.fetchone() is not None
            if not existed:
                cursor.execute(f'CREATE DATABASE "{name}"')
    finally:
        connection.close()
    return "existed" if existed else "created"


def migrate_pg(api_python: str) -> str:
    result = subprocess.run(
        [api_python, "-m", "alembic", "upgrade", "head"],
        cwd=str(API_DIR),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[-400:] or result.stdout.strip()[-400:]
        raise RehearsalError(f"alembic upgrade head failed: {detail}")
    return "at head"


RELEASE_INSERT = (
    "INSERT INTO releases (version, name, description, status,"
    " published_at, variant_count, gene_count, mutant_line_count,"
    " created_at, updated_at)"
    " VALUES (%s, %s, %s, 'published', now(), %s, 0, 0, now(), now())"
)

ASSEMBLY_INSERT = (
    "INSERT INTO assemblies (name, species, version, description)"
    " VALUES (%s, 'Glycine max', %s, 'rehearsal')"
    " ON CONFLICT (name) DO UPDATE SET version = EXCLUDED.version RETURNING id"
)


def seed_pg_identity() -> dict[str, Any]:
    """Create the release and assembly identities the assembly_map points at."""
    expected = len(TARGET_RELEASE_ROWS)
    connection = pg_connect()
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                RELEASE_INSERT + " ON CONFLICT (name) DO UPDATE"
                " SET variant_count = EXCLUDED.variant_count RETURNING id",
                (RELEASE_VERSION, "Backfill rehearsal target", "rehearsal", expected),
            )
            release_id = cursor.fetchone()[0]
            cursor.execute(
                RELEASE_INSERT + " ON CONFLICT (name) DO UPDATE"
                " SET variant_count = 0 RETURNING id",
                (OTHER_RELEASE_VERSION, "Backfill rehearsal other", "rehearsal", 0),
            )
            other_release_id = cursor.fetchone()[0]
            assembly_ids = {}
            for label, version in ASSEMBLY_LABELS.items():
                cursor.execute(ASSEMBLY_INSERT, (label, version))
                assembly_ids[label] = cursor.fetchone()[0]
    finally:
        connection.close()
    return {
        "release_id": release_id,
        "release_version": RELEASE_VERSION,
        "release_variant_count": expected,
        "other_release_id": other_release_id,
        "other_release_version": OTHER_RELEASE_VERSION,
        "assembly_map": assembly_ids,
        "assembly_labels": dict(ASSEMBLY_LABELS),
    }


def snapshot_pg(release_id: int) -> dict[str, Any]:
    """Everything a transfer may touch, so a rejection can be shown inert."""
    connection = pg_connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM variant_facts WHERE release_id = %s",
                (release_id,),
            )
            release_facts = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM variant_facts")
            all_facts = cursor.fetchone()[0]
            cursor.execute(
                "SELECT assembly_id, variant_id FROM variant_facts"
                " WHERE release_id = %s ORDER BY assembly_id, variant_id",
                (release_id,),
            )
            identities = [[row[0], row[1]] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT release_id, source_version, source_count, payload_sha256"
                " FROM native_variant_backfills ORDER BY release_id"
            )
            receipts = [
                {
                    "release_id": row[0],
                    "source_version": row[1],
                    "source_count": row[2],
                    "payload_sha256": row[3],
                }
                for row in cursor.fetchall()
            ]
    finally:
        connection.close()
    return {
        "release_facts": release_facts,
        "all_facts": all_facts,
        "receipt_count": len(receipts),
        "receipts": receipts,
        "identities": identities,
    }


# --------------------------------------------------------------------------
# The real CLI
# --------------------------------------------------------------------------


def cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["BACKFILL_POSTGRES_URL"] = pg_url()
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(WORKER_SRC),
            str(REPO_ROOT / "packages" / "jobs-py" / "src"),
            str(REPO_ROOT / "packages" / "import-protocol"),
        ]
    )
    return env


def run_backfill(
    *,
    release_id: int,
    source_version: str,
    assembly_map: dict[str, int],
    apply: bool,
    source_frozen: bool,
) -> dict[str, Any]:
    """Invoke the real soymutdb_worker.native_backfill CLI."""
    argv = [
        sys.executable,
        "-m",
        "soymutdb_worker.native_backfill",
        "--release-id",
        str(release_id),
        "--source-version",
        source_version,
        "--assembly-map",
        json.dumps(assembly_map, sort_keys=True),
    ]
    if apply:
        argv.append("--apply")
    if source_frozen:
        argv.append("--source-frozen")
    result = subprocess.run(
        argv,
        env=cli_env(),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    report: dict[str, Any] = {
        "argv": ["<python>" if part == sys.executable else part for part in argv[1:]],
        "exit_code": result.returncode,
    }
    if result.returncode == 0:
        report["report"] = json.loads(result.stdout)
    else:
        report["stderr_tail"] = result.stderr.strip()[-400:]
    return report


def run_cutover(api_python: str) -> dict[str, Any]:
    result = subprocess.run(
        [api_python, "-m", "app.scripts.verify_native_cutover"],
        cwd=str(API_DIR),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    verdict: dict[str, Any] = {"exit_code": result.returncode}
    try:
        verdict.update(json.loads(result.stdout))
    except json.JSONDecodeError:
        verdict["stdout_tail"] = result.stdout.strip()[-400:]
        verdict["stderr_tail"] = result.stderr.strip()[-400:]
    return verdict


def expect_rejected(
    label: str,
    result: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    needle: str,
) -> dict[str, Any]:
    """A negative case only counts if it failed AND changed nothing."""
    if result["exit_code"] == 0:
        raise RehearsalError(f"{label}: CLI accepted an input it must reject")
    if before != after:
        raise RehearsalError(f"{label}: PostgreSQL changed despite the rejection")
    text = result.get("stderr_tail", "")
    if needle.lower() not in text.lower():
        raise RehearsalError(
            f"{label}: rejection message did not mention {needle!r}: {text[-200:]}"
        )
    return {
        "case": label,
        "rejected": True,
        "exit_code": result["exit_code"],
        "message_matched": needle,
        "postgres_unchanged": True,
        "postgres_after": {
            "release_facts": after["release_facts"],
            "receipt_count": after["receipt_count"],
        },
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run(api_python: str, evidence_out: str | None) -> int:
    try:
        target = assert_isolated_target()
    except RehearsalError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    evidence: dict[str, Any] = {
        "target": target,
        "scope": "isolated rehearsal; NOT a production backfill",
        "worker_python": sys.version.split()[0],
        "api_python": subprocess.check_output([api_python, "--version"], text=True).strip(),
        "steps": [],
    }

    evidence["postgres_database"] = create_pg_database()
    evidence["postgres_migration"] = migrate_pg(api_python)
    evidence["steps"].append("rehearsal database created and migrated to head")

    evidence["clickhouse"] = provision_clickhouse()
    evidence["clickhouse"]["fixtures"] = seed_clickhouse()
    evidence["steps"].append("ClickHouse provisioned from init.sql and seeded")

    identity = seed_pg_identity()
    evidence["identity"] = identity
    evidence["steps"].append("PostgreSQL identity seeded (releases, assemblies)")

    release_id = identity["release_id"]
    assembly_map = identity["assembly_map"]
    expected = len(TARGET_RELEASE_ROWS)

    clean = snapshot_pg(release_id)
    if clean["release_facts"] or clean["receipt_count"]:
        raise RehearsalError("rehearsal database is not empty; results unattributable")

    # 1. Dry run verifies the source and must write nothing.
    dry = run_backfill(
        release_id=release_id,
        source_version=RELEASE_VERSION,
        assembly_map=assembly_map,
        apply=False,
        source_frozen=False,
    )
    after_dry = snapshot_pg(release_id)
    if dry["exit_code"] != 0:
        raise RehearsalError(f"dry run failed: {dry.get('stderr_tail')}")
    if after_dry != clean:
        raise RehearsalError("dry run wrote to PostgreSQL")
    evidence["dry_run"] = {
        "report": dry["report"],
        "wrote_nothing": True,
        "release_facts": after_dry["release_facts"],
        "receipt_count": after_dry["receipt_count"],
    }
    evidence["steps"].append("dry run verified the source and wrote nothing")

    # 2. Apply with the legacy writers confirmed frozen.
    applied = run_backfill(
        release_id=release_id,
        source_version=RELEASE_VERSION,
        assembly_map=assembly_map,
        apply=True,
        source_frozen=True,
    )
    after_apply = snapshot_pg(release_id)
    if applied["exit_code"] != 0:
        raise RehearsalError(f"apply failed: {applied.get('stderr_tail')}")
    if after_apply["release_facts"] != expected:
        raise RehearsalError(
            f"apply wrote {after_apply['release_facts']} facts, expected {expected}"
        )
    if after_apply["receipt_count"] != 1:
        raise RehearsalError("apply did not leave exactly one receipt")
    evidence["apply"] = {
        "report": applied["report"],
        "release_facts": after_apply["release_facts"],
        "receipts": after_apply["receipts"],
        "identities": after_apply["identities"],
    }
    evidence["steps"].append("apply transferred and verified with one receipt")

    # 3. Cutover verdict for the migrated database.
    cutover = run_cutover(api_python)
    if not cutover.get("native_cutover_ready"):
        raise RehearsalError(f"verify_native_cutover reported faults: {cutover}")
    evidence["cutover"] = cutover
    evidence["steps"].append("verify_native_cutover reports ready")

    # 4. Idempotence: the same apply again changes nothing.
    repeat = run_backfill(
        release_id=release_id,
        source_version=RELEASE_VERSION,
        assembly_map=assembly_map,
        apply=True,
        source_frozen=True,
    )
    after_repeat = snapshot_pg(release_id)
    if repeat["exit_code"] != 0:
        raise RehearsalError(f"repeat apply failed: {repeat.get('stderr_tail')}")
    if after_repeat != after_apply:
        raise RehearsalError("repeat apply changed PostgreSQL")
    if repeat["report"]["payload_sha256"] != applied["report"]["payload_sha256"]:
        raise RehearsalError("repeat apply produced a different payload digest")
    evidence["idempotent_repeat"] = {
        "payload_sha256": repeat["report"]["payload_sha256"],
        "digest_matches_first_apply": True,
        "receipt_count": after_repeat["receipt_count"],
        "unchanged": True,
    }
    evidence["steps"].append("repeat apply was idempotent (same digest, one receipt)")

    # 5. Rejections, each proven inert.
    collapsed = dict(assembly_map)
    collapsed["backfill-v5"] = collapsed["backfill-v4"]
    version_mismatch = run_backfill(
        release_id=release_id,
        source_version="backfill-v9.9.9",
        assembly_map=assembly_map,
        apply=True,
        source_frozen=True,
    )
    negatives = [
        expect_rejected(
            "apply without --source-frozen",
            run_backfill(
                release_id=release_id,
                source_version=RELEASE_VERSION,
                assembly_map=assembly_map,
                apply=True,
                source_frozen=False,
            ),
            after_repeat,
            snapshot_pg(release_id),
            "source-frozen",
        ),
        expect_rejected(
            "collapsed assembly namespaces",
            run_backfill(
                release_id=release_id,
                source_version=RELEASE_VERSION,
                assembly_map=collapsed,
                apply=True,
                source_frozen=True,
            ),
            after_repeat,
            snapshot_pg(release_id),
            "must not be collapsed",
        ),
        expect_rejected(
            "source version does not match the release",
            version_mismatch,
            after_repeat,
            snapshot_pg(release_id),
            "does not match authoritative identity",
        ),
    ]
    evidence["negatives"] = negatives
    evidence["steps"].append("three rejections refused, PostgreSQL unchanged")

    evidence["postgres_final"] = snapshot_pg(release_id)
    evidence["verified"] = True
    evidence["disclaimer"] = (
        "Rehearsal evidence only. It proves the backfill contract against data "
        "this script created in a throwaway database; it is not a claim that "
        "any production release has been backfilled."
    )
    payload = json.dumps(evidence, indent=2, sort_keys=True, default=str)
    if evidence_out:
        Path(evidence_out).write_text(payload + chr(10), encoding="utf-8")
    print(payload)
    return 0


def main() -> int:
    if sys.version_info < (3, 15):
        print("Python 3.15+ is required", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-python",
        default=sys.executable,
        help="Interpreter used for alembic and verify_native_cutover.",
    )
    parser.add_argument(
        "--evidence-out",
        help="Also write the redacted JSON evidence to this path.",
    )
    args = parser.parse_args()
    try:
        return run(args.api_python, args.evidence_out)
    except RehearsalError as exc:
        print(
            json.dumps({"rehearsed": False, "failure": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        # psycopg2.Error, urllib errors and ClickHouse HTTP faults all mean the
        # environment is not ready, not that the rehearsal proved anything.
        import psycopg2

        if isinstance(exc, (psycopg2.Error, ConnectionError, OSError)):
            print(
                json.dumps(
                    {
                        "rehearsed": False,
                        "failure": (
                            f"could not reach a local service "
                            f"({type(exc).__name__}): {str(exc)[:200]}. Start "
                            "PostgreSQL and ClickHouse and confirm the URLs."
                        ),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())

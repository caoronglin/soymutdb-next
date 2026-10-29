#!/usr/bin/env python3
"""Verify the native variant-export chain against real services, unmocked.

Drives the real FastAPI app over an ASGI transport, real PostgreSQL, the real
Celery broker, a real worker process and real S3:

    POST /variants/export (202) -> outbox_events row -> poll_outbox_once()
    -> broker -> worker writes the artifact to S3 -> AsyncResult SUCCESS
    -> artifact read back from S3 and inspected

The artifact assertions are the point: three negative rows are seeded (private
mutant line, other assembly, draft release) and must be absent, so a regression
in the worker's released/public restriction fails here instead of passing
silently.

Started separately by the operator: migrated PostgreSQL, Redis, MinIO/S3, and a
Celery worker on the "export" queue against those same three.

Refuses to run unless SOYMUTDB_APP_ENV=dev and the database, broker, result
backend and S3 endpoint are loopback with a database named "soymutdb_chain_*".
Writes stay inside that database and under the "exports/" prefix.

Usage
    SOYMUTDB_APP_ENV=dev \
    SOYMUTDB_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55448/soymutdb_chain_20261016 \
    SOYMUTDB_CELERY_BROKER_URL=redis://127.0.0.1:56389/1 \
    SOYMUTDB_CELERY_RESULT_BACKEND=redis://127.0.0.1:56389/2 \
    SOYMUTDB_S3_ENDPOINT=http://127.0.0.1:59000 \
    SOYMUTDB_JWT_SECRET=... \
      apps/api/.venv/bin/python scripts/dev/verify-native-export-chain.py \
        --evidence-out /tmp/evidence.json

Exit codes: 0 verified, 1 verification failed, 2 refused (unsafe config).
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

CHAIN_DB_PREFIX = "soymutdb_chain_"
EXPORT_PREFIX = "exports/"

PUBLISHED_VERSION = "chain-pub-1"
DRAFT_VERSION = "chain-draft-1"
ASSEMBLY_V4 = "chain-v4"
ASSEMBLY_V5 = "chain-v5"
PUBLIC_LINE = "chain-public-line"
PRIVATE_LINE = "chain-private-line"
RESEARCHER_USERNAME = "chain_researcher"
RESEARCHER_EMAIL = "chain-researcher@localhost.invalid"

# (release, assembly, variant_id, position, line, included, reason)
FACT_ROWS = [
    ("published", ASSEMBLY_V4, "1001", 100001, "public", True, "released, public"),
    ("published", ASSEMBLY_V4, "1002", 200001, "none", True, "belongs to no line"),
    ("published", ASSEMBLY_V4, "1003", 300001, "private", False, "private line"),
    ("published", ASSEMBLY_V5, "1004", 400001, "public", False, "other assembly"),
    ("draft", ASSEMBLY_V4, "1005", 500001, "public", False, "draft release"),
]
EXPECTED_VARIANT_IDS = {row[2] for row in FACT_ROWS if row[5]}
EXCLUDED_VARIANT_IDS = [row[2] for row in FACT_ROWS if not row[5]]

# Transcribed independently from the worker's EXPORT_COLUMNS so a widened or
# reordered artifact is caught here rather than trusted from the code under test.
EXPECTED_COLUMNS = [
    "release_key",
    "assembly_key",
    "chromosome",
    "position",
    "variant_id",
    "ref_allele",
    "alt_allele",
    "variant_type",
    "variant_subtype",
    "impact",
    "quality_score",
    "allele_frequency",
    "zygosity",
    "gene_id",
    "gene_symbol",
    "mutant_public_id",
    "hgvs_c",
    "hgvs_p",
    "read_depth",
    "filter_status",
]

#: Internal join keys that must never reach a published artifact.
FORBIDDEN_COLUMNS = {
    "gene_surrogate_id",
    "mutant_line_surrogate_id",
    "mutant_line_name",
}

#: Bound in run() from the API's global factory, so the HTTP layer and the
#: outbox dispatcher provably share one engine and one database.
session_factory: Any = None


class VerificationError(Exception):
    """A chain assertion failed; reported as evidence, not a traceback."""


def _is_loopback(host: str | None) -> bool:
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


def export_bucket() -> str:
    """The worker's bucket name, resolved with the worker's own lookup order."""
    return os.getenv(
        "SOYMUTDB_S3_EXPORT_BUCKET", os.getenv("S3_EXPORT_BUCKET", "exports")
    )


def assert_isolated_target(settings: Any) -> dict[str, Any]:
    """Refuse anything but a loopback dev database named soymutdb_chain_*.

    Reads Settings rather than raw env vars, so a value from a .env file is
    checked too. Runs before the first write.
    """
    from sqlalchemy.engine import make_url

    if settings.app_env != "dev":
        raise VerificationError(f"app_env is {settings.app_env!r}, not dev")

    database_url = make_url(settings.database_url)
    if not _is_loopback(database_url.host):
        raise VerificationError(f"database host {database_url.host!r} is not loopback")
    if not str(database_url.database or "").startswith(CHAIN_DB_PREFIX):
        raise VerificationError(
            f"database name {database_url.database!r} must start with "
            f"{CHAIN_DB_PREFIX!r}"
        )

    broker_host = urlparse(settings.celery_broker_url).hostname
    backend_host = urlparse(settings.celery_result_backend).hostname
    if not _is_loopback(broker_host) or not _is_loopback(backend_host):
        raise VerificationError(
            f"broker/backend must be loopback (got {broker_host!r}/{backend_host!r})"
        )

    s3_host = urlparse(settings.s3_endpoint).hostname
    if not _is_loopback(s3_host):
        raise VerificationError(f"S3 endpoint host {s3_host!r} is not loopback")

    return {
        "app_env": settings.app_env,
        "database": (
            f"{database_url.host}:{database_url.port or 5432}/{database_url.database}"
        ),
        "broker": _redact(settings.celery_broker_url, "broker url"),
        "result_backend": _redact(settings.celery_result_backend, "broker url"),
        "s3_endpoint": settings.s3_endpoint,
        "s3_region": settings.s3_region,
    }


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------


async def _find_or_create(
    session: Any, model: Any, defaults: dict[str, Any], **match: Any
) -> Any:
    from sqlalchemy import select

    obj = (await session.execute(select(model).filter_by(**match))).scalar_one_or_none()
    if obj is None:
        # The created row must become the return value: the callers below
        # read ``.id``/``.public_id`` off it, and a freshly seeded database
        # has no pre-existing row to return.
        obj = model(**match, **defaults)
        session.add(obj)
    else:
        for field, value in defaults.items():
            setattr(obj, field, value)
    await session.flush()
    return obj


async def seed() -> dict[str, Any]:
    """Create the fixture, replacing only the rows this script owns."""
    from app.core.public_ids import generate_public_id
    from app.core.security import RoleName, hash_password
    from app.models.auth import Role, User
    from app.models.content import Release, ReleaseStatus
    from app.models.data_publishing import ActiveRelease
    from app.models.genomic import Assembly
    from app.models.variant import MutantLine
    from app.models.variant_facts import variant_facts
    from sqlalchemy import delete

    async with session_factory() as session:
        published = await _find_or_create(
            session,
            Release,
            {
                "name": "Chain published release",
                "description": "Isolated verification fixture",
                "status": ReleaseStatus.PUBLISHED,
                "published_at": datetime.now(UTC),
            },
            version=PUBLISHED_VERSION,
        )
        draft = await _find_or_create(
            session,
            Release,
            {
                "name": "Chain draft release",
                "description": "Isolated verification fixture (never exported)",
                "status": ReleaseStatus.DRAFT,
            },
            version=DRAFT_VERSION,
        )

        assemblies = {}
        for name, version in ((ASSEMBLY_V4, "v4"), (ASSEMBLY_V5, "v5")):
            assemblies[name] = await _find_or_create(
                session,
                Assembly,
                {"version": version, "species": "Glycine max"},
                name=name,
            )
        published.assembly_id = assemblies[ASSEMBLY_V4].id
        published.assembly = ASSEMBLY_V4

        public_line = await _find_or_create(
            session,
            MutantLine,
            {
                "is_public": True,
                "release_id": published.id,
                "description": "Chain fixture public line",
            },
            name=PUBLIC_LINE,
        )
        # Kept stable across reruns: the artifact assertion compares against it.
        public_line.public_id = public_line.public_id or generate_public_id()

        private_line = await _find_or_create(
            session,
            MutantLine,
            {
                # Unpublished; publication is what requires a public_id.
                "public_id": None,
                "is_public": False,
                "release_id": published.id,
                "description": "Chain fixture private line",
            },
            name=PRIVATE_LINE,
        )

        role = await _find_or_create(
            session,
            Role,
            {"description": "Chain fixture researcher", "permissions": {}},
            name=RoleName.RESEARCHER.value,
        )
        user = await _find_or_create(
            session,
            User,
            {
                # Never used or printed: the script mints an access token
                # directly, so no known credential is created.
                "password_hash": hash_password(secrets.token_urlsafe(32)),
                "full_name": "Chain researcher",
                "role_id": role.id,
                "is_active": True,
                "is_superuser": False,
            },
            username=RESEARCHER_USERNAME,
            email=RESEARCHER_EMAIL,
        )

        # The export request resolves its release from this singleton.
        await _find_or_create(
            session, ActiveRelease, {"release_id": published.id}, id=1
        )

        # Replace only this script's own facts, scoped to the two chain
        # releases, so a rerun is deterministic.
        await session.execute(
            delete(variant_facts).where(
                variant_facts.c.release_id.in_([published.id, draft.id])
            )
        )

        lines = {
            "public": (PUBLIC_LINE, public_line.id),
            "private": (PRIVATE_LINE, private_line.id),
            "none": ("", 0),
        }
        releases = {"published": published.id, "draft": draft.id}
        await session.execute(
            variant_facts.insert(),
            [
                {
                    "release_id": releases[release_key],
                    "assembly_id": assemblies[assembly].id,
                    "variant_id": variant_id,
                    "assembly_key": assembly,
                    "chromosome": "Chr01",
                    "position": position,
                    "ref_allele": "A",
                    "alt_allele": "T",
                    "variant_type": "SNP",
                    "impact": "MODERATE",
                    "quality_score": 60.0,
                    "filter_status": "PASS",
                    "allele_frequency": 0.25,
                    "mutant_line_name": lines[line][0],
                    "mutant_line_surrogate_id": lines[line][1],
                    "gene_id": "Glyma.01G000100",
                }
                for release_key, assembly, variant_id, position, line, _, _ in FACT_ROWS
            ],
        )
        await session.commit()

    return {
        "published_release": {"id": published.id, "version": PUBLISHED_VERSION},
        "draft_release": {"id": draft.id, "version": DRAFT_VERSION},
        "assemblies": {name: {"id": a.id} for name, a in assemblies.items()},
        "mutant_lines": {
            "public": {"name": PUBLIC_LINE, "public_id": public_line.public_id},
            "private": {"name": PRIVATE_LINE, "public_id": None, "is_public": False},
        },
        "researcher": {"username": RESEARCHER_USERNAME, "role": role.name},
        "user_id": str(user.id),
        "variant_facts_seeded": len(FACT_ROWS),
        "variant_facts_expected_in_export": sorted(EXPECTED_VARIANT_IDS),
        "variant_facts_expected_excluded": [
            {"variant_id": row[2], "because": row[6]} for row in FACT_ROWS if not row[5]
        ],
    }


# --------------------------------------------------------------------------
# Chain steps
# --------------------------------------------------------------------------


async def submit_anonymous_export(client: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/variants/export",
        json={"format": "tsv", "compress": False, "filters": {}},
    )
    if response.status_code != 401:
        raise VerificationError(
            f"anonymous export returned {response.status_code}, expected 401"
        )
    body = response.json() if response.content else {}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    return {
        "request": "POST /api/v1/variants/export (no Authorization header)",
        "status_code": response.status_code,
        "error_code": error.get("code"),
        "rejected": True,
    }


async def submit_authenticated_export(
    client: Any, token: str, assembly: str
) -> tuple[dict[str, Any], str]:
    response = await client.post(
        "/api/v1/variants/export",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "format": "tsv",
            # Plain text, so the artifact needs no unpacking to be inspected.
            "compress": False,
            "filters": {"assembly": assembly},
        },
    )
    if response.status_code != 202:
        raise VerificationError(
            f"authenticated export returned {response.status_code}: "
            f"{response.text[:400]}"
        )
    export_id = response.json().get("export_id")
    if not export_id:
        raise VerificationError("export response carried no export_id")
    return (
        {
            "request": "POST /api/v1/variants/export (researcher bearer token)",
            "status_code": response.status_code,
            "export_id": export_id,
            "format": "tsv",
            "compress": False,
            "assembly_filter": assembly,
            "authorization_header": _redact("Bearer <jwt>", "access token"),
        },
        export_id,
    )


async def read_outbox_event(export_id: str) -> Any:
    """The durable outbox row the accepted export committed."""
    from app.models.outbox import OutboxEvent
    from sqlalchemy import select

    async with session_factory() as session:
        event = (
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.aggregate_id == export_id)
                )
            )
            .scalars()
            .first()
        )
        if event is None:
            raise VerificationError("no outbox row was persisted for the export")
        session.expunge(event)
        return event


def outbox_evidence(event: Any) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "aggregate_type": event.aggregate_type,
        "event_type": event.event_type,
        "status": str(event.status),
        "attempt_count": event.attempt_count,
        "task_name": (event.payload or {}).get("task_name"),
        "sent_at": event.sent_at.isoformat() if event.sent_at else None,
    }


async def wait_for_task(event_id: str, timeout_seconds: float) -> dict[str, Any]:
    from app.core.task_dispatch import get_celery_client

    result = get_celery_client().AsyncResult(str(event_id))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    state = result.state
    while state not in {"SUCCESS", "FAILURE", "REVOKED"}:
        if loop.time() >= deadline:
            raise VerificationError(
                f"Celery task {event_id} was still {state!r} after "
                f"{timeout_seconds:g}s. It reached the broker, so no worker "
                "consumed it: start a Celery worker on the 'export' queue "
                "against the same broker, database and S3."
            )
        await asyncio.sleep(1.0)
        state = result.state

    if state != "SUCCESS":
        raise VerificationError(f"Celery task {event_id} finished in state {state!r}")
    outcome = result.result or {}
    if not isinstance(outcome, dict):
        raise VerificationError("export task returned a non-dict result")
    return {
        "async_result_state": state,
        "task_id_matches_outbox_event_id": str(result.id) == str(event_id),
        "record_count": outcome.get("record_count"),
        "file_size": outcome.get("file_size"),
        "s3_path": outcome.get("s3_path"),
        # The task result carries the object key only: the download URL is
        # signed on demand by the API for the requester, never by the task.
        "artifact_key": outcome.get("s3_path"),
    }


def inspect_artifact(
    body: bytes,
    published_id: int,
    draft_id: int,
    public_id: str,
    assembly_v4: str,
    assembly_v5: str,
) -> dict[str, Any]:
    """Assert the artifact carries only released, public, in-scope rows."""
    text = body.decode("utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise VerificationError("artifact is empty")

    header = lines[0].split("	")
    if header != EXPECTED_COLUMNS:
        leaked = sorted(FORBIDDEN_COLUMNS.intersection(header))
        raise VerificationError(
            f"artifact header mismatch; forbidden columns present: {leaked}"
        )

    records = [
        dict(zip(EXPECTED_COLUMNS, line.split("	"), strict=False))
        for line in lines[1:]
    ]
    found = {record["variant_id"] for record in records}
    if found != EXPECTED_VARIANT_IDS:
        raise VerificationError(
            f"artifact carries variant_ids {sorted(found)}, expected "
            f"{sorted(EXPECTED_VARIANT_IDS)}"
        )
    if PRIVATE_LINE in text:
        raise VerificationError("artifact leaked the private mutant line name")

    for record in records:
        vid = record["variant_id"]
        if record["release_key"] != str(published_id):
            raise VerificationError(
                f"row {vid} has release_key {record['release_key']!r}, "
                f"expected {published_id}"
            )
        if record["release_key"] == str(draft_id):
            raise VerificationError("artifact carries a draft release row")
        if record["assembly_key"] != assembly_v4:
            raise VerificationError(
                f"row {vid} has assembly_key {record['assembly_key']!r}, "
                f"expected {assembly_v4!r}"
            )
        if record["assembly_key"] == assembly_v5:
            raise VerificationError("artifact carries the other assembly")
        if record["mutant_public_id"] not in {"", public_id}:
            raise VerificationError(
                f"row {vid} exposes an unexpected mutant_public_id "
                f"{record['mutant_public_id']!r}"
            )

    return {
        "columns": header,
        "forbidden_columns_absent": sorted(FORBIDDEN_COLUMNS),
        "row_count": len(records),
        "variant_ids": sorted(found),
        "release_key_values": sorted({r["release_key"] for r in records}),
        "assembly_key_values": sorted({r["assembly_key"] for r in records}),
        "mutant_public_id_values": sorted({r["mutant_public_id"] for r in records}),
        "private_line_name_absent": True,
        "excluded_variant_ids": EXCLUDED_VARIANT_IDS,
    }


def ensure_bucket(s3: Any, bucket: str) -> str:
    """Create the export bucket if this isolated stack has not yet."""
    from botocore.exceptions import ClientError

    try:
        s3.head_bucket(Bucket=bucket)
        return "existed"
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        return "created"


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def emit(evidence: dict[str, Any], path: str | None) -> None:
    """Write the evidence as JSON. The app logs to stdout, so a file is the
    only reliably parseable form."""
    payload = json.dumps(evidence, indent=2, sort_keys=True, default=str)
    if path:
        Path(path).write_text(payload + "\n", encoding="utf-8")
    print(payload)


async def run(task_timeout: float, evidence_out: str | None) -> int:
    global session_factory

    # Checked before any product import: several API modules build Settings at
    # import time, so an unsafe app_env would otherwise surface as a config
    # traceback rather than a refusal.
    if os.environ.get("SOYMUTDB_APP_ENV", "dev") != "dev":
        print(
            f"refusing to run: SOYMUTDB_APP_ENV is "
            f"{os.environ.get('SOYMUTDB_APP_ENV')!r}; this script writes to a "
            "development database only",
            file=sys.stderr,
        )
        return 2

    try:
        import httpx
        from app.core.config import get_settings
        from app.core.database import get_session_factory
        from app.core.outbox_dispatcher import poll_outbox_once
        from app.core.security import create_access_token
        from app.main import app as fastapi_app
        from app.utils.s3 import get_s3_client
        from httpx import ASGITransport
    except Exception as exc:  # noqa: BLE001 - deliberate
        # Any import-time failure (a missing dependency, or the product's own
        # production Settings guards) must read as a refusal, not a traceback.
        print(
            "refusing to run: the application configuration did not load "
            f"({type(exc).__name__}); fix the configuration or run against dev",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    try:
        target = assert_isolated_target(settings)
    except VerificationError as exc:
        print(f"refusing to run: {exc}", file=sys.stderr)
        return 2

    session_factory = get_session_factory()
    bucket = export_bucket()
    evidence: dict[str, Any] = {
        "target": target,
        "export_bucket": bucket,
        "steps": [],
    }

    fixture = await seed()
    evidence["fixture"] = fixture
    evidence["steps"].append("seeded isolated fixture")

    s3 = get_s3_client()
    evidence["bucket"] = ensure_bucket(s3, bucket)

    # A real token, so get_current_user and the RBAC dependency below are the
    # product's own. No login flow is exercised.
    token = create_access_token(fixture["user_id"])

    # ASGITransport does not run the app lifespan, so no background dispatcher
    # competes with the poll_outbox_once() calls below.
    async with httpx.AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://chain-verification.local",
    ) as client:
        evidence["anonymous_export"] = await submit_anonymous_export(client)
        evidence["steps"].append("anonymous export rejected with 401")
        accepted, export_id = await submit_authenticated_export(
            client, token, ASSEMBLY_V4
        )
        evidence["authenticated_export"] = accepted
        evidence["steps"].append("authenticated export accepted with 202")

    event = await read_outbox_event(export_id)
    if str(event.status) != "pending":
        raise VerificationError(f"new outbox row is {event.status}, expected pending")
    evidence["outbox_before_dispatch"] = outbox_evidence(event)
    evidence["steps"].append("outbox row persisted as pending")

    dispatched = await poll_outbox_once()
    if dispatched != 1:
        raise VerificationError(
            f"poll_outbox_once processed {dispatched} events, expected 1"
        )
    after = await read_outbox_event(export_id)
    evidence["outbox_after_dispatch"] = outbox_evidence(after)
    evidence["steps"].append("poll_outbox_once sent 1 event to the broker")

    evidence["worker_result"] = task = await wait_for_task(
        str(event.event_id), task_timeout
    )
    evidence["steps"].append("worker finished with AsyncResult SUCCESS")

    s3_path = task["s3_path"] or ""
    if not s3_path.startswith(EXPORT_PREFIX):
        raise VerificationError(
            f"artifact key {s3_path!r} is outside {EXPORT_PREFIX!r}"
        )
    # s3_path is the object key; the bucket is a separate coordinate.
    head_before = s3.head_object(Bucket=bucket, Key=s3_path)
    body = s3.get_object(Bucket=bucket, Key=s3_path)["Body"].read()
    evidence["artifact"] = inspect_artifact(
        body,
        published_id=fixture["published_release"]["id"],
        draft_id=fixture["draft_release"]["id"],
        public_id=fixture["mutant_lines"]["public"]["public_id"],
        assembly_v4=ASSEMBLY_V4,
        assembly_v5=ASSEMBLY_V5,
    )
    evidence["artifact"]["s3"] = {
        "bucket": bucket,
        "key": s3_path,
        "etag": head_before["ETag"],
        "bytes": head_before["ContentLength"],
    }
    evidence["steps"].append("artifact read back from S3 and inspected")

    # Idempotency: the sent event must not be claimed again and the artifact
    # must not be rewritten.
    if await poll_outbox_once() != 0:
        raise VerificationError("second poll_outbox_once processed an event")
    final = await read_outbox_event(export_id)
    if str(final.status) != "sent" or final.attempt_count != after.attempt_count:
        raise VerificationError(
            f"outbox row changed after the second poll (status={final.status}, "
            f"attempts={final.attempt_count})"
        )
    if s3.head_object(Bucket=bucket, Key=s3_path)["ETag"] != head_before["ETag"]:
        raise VerificationError("artifact was rewritten by a duplicate dispatch")
    evidence["replay"] = {
        "second_poll_processed": 0,
        "outbox_status": str(final.status),
        "attempt_count": final.attempt_count,
        "artifact_etag_unchanged": True,
    }
    evidence["steps"].append("second poll re-sent nothing; artifact unchanged")

    evidence["verified"] = True
    emit(evidence, evidence_out)
    return 0


async def main() -> int:
    from sqlalchemy.exc import SQLAlchemyError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the worker's AsyncResult (default: 120).",
    )
    parser.add_argument(
        "--evidence-out",
        help="Write the redacted JSON evidence to this path as well as stdout.",
    )
    args = parser.parse_args()

    def fail(message: str) -> int:
        print(
            json.dumps({"verified": False, "failure": message}, indent=2),
            file=sys.stderr,
        )
        return 1

    try:
        return await run(args.task_timeout, args.evidence_out)
    except VerificationError as exc:
        # A statement about the chain, not a bug in the script.
        return fail(str(exc))
    except SQLAlchemyError as exc:
        # An unreachable database is an environment problem, not a verdict.
        return fail(
            f"could not reach the isolated database ({type(exc).__name__}). "
            "Start PostgreSQL and confirm SOYMUTDB_DATABASE_URL names the "
            "migrated soymutdb_chain_* database."
        )
    except (ConnectionError, OSError) as exc:
        # The broker and S3 clients raise these when a local service is down.
        return fail(
            f"could not reach a local service ({type(exc).__name__}). Start "
            "Redis and MinIO/S3 and confirm the broker, result backend and S3 "
            "endpoint variables."
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

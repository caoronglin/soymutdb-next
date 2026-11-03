"""Celery lifecycle for immutable NCBI BLAST+ index construction.

The operator builder (:mod:`soymutdb_worker.blast_index`) already does staging
-> ``makeblastdb`` -> ``blastdbcmd`` validation -> locked atomic rename. This
task is the *only* path that invokes it at runtime: builds never happen inside
an HTTP request, and PostgreSQL remains authoritative for publication.

State machine (persisted in ``blast_databases.build_status``)::

    pending -> building -> validating -> publishing -> published
                    \\         \\            \\
                     +---------+------------+----> failed

Only ``published`` rows are selectable by the search service (the legacy
``ready`` spelling of pre-existing catalogs reads as published). A rebuild
produces a new content-addressed identity; the old index directory is never
mutated or overwritten. Failures clean staging, record a sanitized reason, and
leave any previously published identity intact.

Object-storage choice: **indexes stay on the worker-local immutable volume**,
not in MinIO. They are multi-gigabyte, read-only, content-addressed directories
consumed in-process by the NCBI binaries; shipping them through the object store
would add a second, unsynchronized copy of authoritative state. The catalog
stores only the 64-character identity and public provenance, never a path.
MinIO continues to hold raw search results and uploaded FASTA sources.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from celery import Task
from soymutdb_jobs import blast_catalog_state as state
from sqlalchemy import select

from soymutdb_worker.blast_catalog_store import BlastCatalogStore, CatalogStateError
from soymutdb_worker.blast_index import (
    BuildLimits,
    BuildMetadata,
    IndexBuildError,
    build_index,
    verify_index,
)
from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.shared import BLAST_INDEX_BUILD_TASK
from soymutdb_worker.tables import blast_databases
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client, parse_s3_path

logger = logging.getLogger(__name__)

#: Immutable index root on the worker volume. Must already exist and be owned
#: by the worker principal; never derived from a request or catalog row.
BLAST_INDEX_ROOT = Path(get_setting("BLAST_INDEX_ROOT", "/data/blast/ncbi-indexes"))
BLAST_MAKEBLASTDB_BIN = get_setting("BLAST_MAKEBLASTDB_BIN", "makeblastdb")
BLAST_BLASTDBCMD_BIN = get_setting("BLAST_BLASTDBCMD_BIN", "blastdbcmd")
#: Uploaded source FASTA objects live under this bucket/prefix. Only a bounded
#: ``blast-sources/<key>`` reference from the control plane is accepted;
#: arbitrary local paths and other buckets are refused.
BLAST_SOURCE_BUCKET = get_setting("S3_BLAST_BUCKET", "blast-dbs")
BLAST_SOURCE_PREFIX = "blast-sources/"
_IDENTITY = re.compile(r"[a-f0-9]{64}\Z")
_STAGING_PREFIXES = (".build-", ".verify-")


def _scrub(message: str) -> str:
    """Sanitize a builder failure: no raw FASTA, no local paths, no stderr."""
    clean = "".join(ch for ch in str(message) if ch.isprintable() or ch in "\n\t")
    return " ".join(clean.split())[:2000] or "index build failed"


def _source_key(value: str) -> str:
    """Accept only a bounded object key under the configured source prefix."""
    if not value or any(ch in value for ch in ("\n", "\r", "\x00", "\\")):
        raise ValueError("invalid source object reference")
    if not value.startswith(BLAST_SOURCE_PREFIX) or ".." in value.split("/"):
        raise ValueError("source object must be under the BLAST source prefix")
    return value


def _download_source(object_ref: str, destination: Path) -> None:
    """Stream one verified source object to a private staging file."""
    key = _source_key(object_ref)
    s3 = get_s3_client()
    bucket, _ = parse_s3_path(f"{BLAST_SOURCE_BUCKET}/")
    with destination.open("xb") as handle:
        s3.download_fileobj(bucket, key, handle)


def _cleanup_staging(root: Path) -> None:
    """Remove staging directories left by *this* failed attempt.

    Published identities are never touched. Only the well-known staging
    prefixes are swept; a concurrent builder owns its own directory, so this
    is deliberately called only on the failure path (where the worker has
    finished with its staging), not after a successful concurrent build.
    """
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(_STAGING_PREFIXES) and entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)


def _metadata(payload: dict) -> BuildMetadata:
    """Freeze provenance from the control-plane payload, not from a client."""
    return BuildMetadata(
        assembly_id=str(payload["assembly_id"]),
        assembly_version=str(payload["assembly_version"]),
        release_id=str(payload["release_id"]),
        annotation_version=str(payload["annotation_version"]),
        source_url=str(payload["source_url"]),
        source_version=str(payload["source_version"]),
        license=str(payload["license"]),
    )


@celery_app.task(
    bind=True,
    name=BLAST_INDEX_BUILD_TASK,
    queue="blast",
)
def build_blast_index(self: Task, payload: dict | None = None) -> dict:
    """Build, validate and atomically publish one immutable BLAST index.

    ``payload`` is the versioned outbox event body; the only fields consumed
    are identifiers, provenance and the source object reference. It never
    contains a local filesystem path. Re-delivery is idempotent: a row already
    ``ready`` with the expected identity is a no-op.
    """
    if not isinstance(payload, dict):
        raise ValueError("build_blast_index requires a versioned payload")
    body = payload.get("payload", payload)
    try:
        database_id = int(body["database_id"])
        db_type = str(body["db_type"])
        object_ref = str(body["source_object"])
        metadata = _metadata(body)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid BLAST index build request") from exc
    if db_type not in {"nucl", "prot"}:
        raise ValueError("db_type must be nucl or prot")

    root = BLAST_INDEX_ROOT
    if not root.is_dir():  # pragma: no cover - operator misconfiguration
        raise RuntimeError("BLAST index root is not available on this worker")

    limits = BuildLimits()
    limits.validate()
    metadata.validate()
    _source_key(object_ref)

    with get_db() as session:
        store = BlastCatalogStore(session)
        row = store.get(database_id)
        if row is None:
            raise CatalogStateError("BLAST catalog row not found")
        current = str(row["build_status"])
        if current == state.PUBLISHED and row["index_version"] == body.get("index_identity"):
            return {"database_id": database_id, "skipped": True, "reason": "already_published"}
        if not state.transition_allowed(current, state.BUILDING):
            raise CatalogStateError(
                f"BLAST catalog row is not buildable from {current!r}"
            )
        if not store.transition(database_id, expected=current, target=state.BUILDING):
            raise CatalogStateError("lost the build claim")
        self.update_state(state="STARTED", meta={"progress": 10})

    source = root / f".source-{database_id}.fasta"
    try:
        source.unlink(missing_ok=True)
        _download_source(object_ref, source)
        self.update_state(state="STARTED", meta={"progress": 25})

        # build_index performs staging, makeblastdb, blastdbcmd validation,
        # checksum inventory, fsync and locked atomic publication. It never
        # overwrites an existing identity; a replay verifies and reuses it.
        result = build_index(
            source, root, db_type, metadata,
            makeblastdb_bin=BLAST_MAKEBLASTDB_BIN,
            blastdbcmd_bin=BLAST_BLASTDBCMD_BIN,
            limits=limits,
        )
        identity = result["index_identity"]
        if not _IDENTITY.fullmatch(identity):
            raise IndexBuildError("invalid published index identity")
        self.update_state(state="STARTED", meta={"progress": 70})

        with get_db() as session:
            store = BlastCatalogStore(session)
            if not store.transition(
                database_id, expected=state.BUILDING, target=state.VALIDATING
            ):
                raise CatalogStateError("lost the validating claim")
            # Independent health check: re-verify the published manifest,
            # artifact checksums and database contents with blastdbcmd.
            verified = verify_index(
                root, identity, blastdbcmd_bin=BLAST_BLASTDBCMD_BIN, limits=limits
            )
            request = verified["manifest"]["request"]
            if not store.transition(
                database_id, expected=state.VALIDATING, target=state.PUBLISHING
            ):
                raise CatalogStateError("lost the publishing claim")
            published = store.publish(
                database_id,
                index_identity=identity,
                fasta_sha256=request["source_sha256"],
                sequence_count=int(request["sequence_count"]),
                total_length=int(request["letter_count"]),
                annotation_version=str(request["metadata"]["annotation_version"]),
            )
            if not published:
                raise CatalogStateError("lost the final publication claim")
        self.update_state(state="STARTED", meta={"progress": 100})
        logger.info("Published BLAST index %s for database %s", identity[:12], database_id)
        return {
            "database_id": database_id,
            "index_identity": identity,
            "reused": bool(result["reused"]),
            "build_status": state.PUBLISHED,
        }
    except Exception as exc:
        reason = _scrub(str(exc))
        logger.error("BLAST index build for database %s failed: %s", database_id, reason)
        # Clean every staging artifact this attempt may have left. The published
        # identity (if any) stays: a failed *validation* must not delete a live
        # index that a previous successful build published.
        _cleanup_staging(root)
        try:
            with get_db() as session:
                store = BlastCatalogStore(session)
                row = store.get(database_id)
                if row is not None:
                    current = str(row["build_status"])
                    if state.transition_allowed(current, state.FAILED):
                        store.transition(
                            database_id, expected=current, target=state.FAILED,
                            build_error=reason,
                        )
        except Exception as db_err:  # pragma: no cover - best effort
            logger.error("Failed to record BLAST build failure: %s", db_err)
        raise
    finally:
        source.unlink(missing_ok=True)


@celery_app.task(
    bind=True,
    name="soymutdb_worker.tasks.blast_index_tasks.check_blast_index_health",
    queue="cleanup",
)
def check_blast_index_health(self: Task) -> dict:
    """Periodically re-verify published immutable indexes and record health.

    A corrupt or missing index is marked ``failed`` with a sanitized reason so
    discovery stops selecting it; the identity itself is never repaired in
    place. Rebuild (new identity) is the only recovery.
    """
    root = BLAST_INDEX_ROOT
    if not root.is_dir():
        return {"checked": 0, "failed": 0, "skipped": "index_root_unavailable"}
    _cleanup_staging(root)
    checked = 0
    failed = 0
    with get_db() as session:
        rows = session.execute(
            select(blast_databases.c.id, blast_databases.c.index_version).where(
                blast_databases.c.build_status == state.PUBLISHED
            )
        ).all()
    for database_id, identity in rows:
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
            continue
        checked += 1
        try:
            verify_index(root, identity, blastdbcmd_bin=BLAST_BLASTDBCMD_BIN)
        except (IndexBuildError, OSError) as exc:
            failed += 1
            reason = _scrub(str(exc))
            with get_db() as session:
                store = BlastCatalogStore(session)
                row = store.get(int(database_id))
                if row is not None and state.transition_allowed(
                    str(row["build_status"]), state.FAILED
                ):
                    store.transition(
                        int(database_id), expected=str(row["build_status"]),
                        target=state.FAILED, build_error=f"health check failed: {reason}",
                    )
            continue
        with get_db() as session:
            BlastCatalogStore(session).mark_healthy(int(database_id))
    return {"checked": checked, "failed": failed}


__all__ = ["build_blast_index", "check_blast_index_health"]

"""Worker-only construction of immutable NCBI BLAST indexes.

This module is the *execution* half of the catalog build state machine. An
HTTP handler records a ``blast_index_builds`` row and an outbox event; that is
all it does. ``makeblastdb``/``blastdbcmd`` run only here, inside a Celery task
on the dedicated ``blast`` queue.

Storage decision (one path, not two): the reviewed source FASTA is read from
the existing MinIO object store, but the built index stays on the worker's
local volume ``SOYMUTDB_BLAST_INDEX_ROOT``. Index directories are never
uploaded to or downloaded from object storage. See docs/ops/blast-index-builder.md.

Each successful build publishes a new content-addressed identity. A rebuild
always creates a new ``blast_index_builds`` row and a new catalog row; an
existing published directory is never mutated or overwritten. Only a build
whose state reached ``published`` (or the legacy ``ready`` DIAMOND spelling)
may be selected for a search.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from celery import Task
from soymutdb_jobs.blast_catalog import (
    index_identity as validate_identity,
)
from soymutdb_jobs.blast_catalog import (
    public_source_url,
    validate_build_state,
)

from soymutdb_worker.blast_index import (
    BuildLimits,
    BuildMetadata,
    IndexBuildError,
    verify_index,
)
from soymutdb_worker.blast_index import (
    build_index as build_immutable_index,
)
from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.repositories import BlastIndexBuildStore
from soymutdb_worker.shared import BLAST_BUILD_INDEX_TASK
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client, parse_s3_path

logger = logging.getLogger(__name__)

#: Immutable index root lives on the worker's local volume. It is operator
#: configuration, never a payload value: an outbox event must not be able to
#: choose an arbitrary filesystem path.
INDEX_ROOT = Path(get_setting("BLAST_INDEX_ROOT", "/data/blast/ncbi-indexes"))
MAKEBLASTDB_BIN = get_setting("MAKEBLASTDB_BIN", "makeblastdb")
BLASTDBCMD_BIN = get_setting("BLASTDBCMD_BIN", "blastdbcmd")
#: Operator-supplied source FASTA prefix in the object store. A build request
#: may reference only keys under this prefix.
SOURCE_PREFIX = "blast-sources/"
MAX_SOURCE_BYTES = int(get_setting("BLAST_BUILD_MAX_SOURCE_BYTES", str(256 * 1024**2)))
#: A build whose worker died mid-flight keeps its claimed state forever unless a
#: redelivery after this lease closes it. A live attempt still inside the lease
#: is never touched; closing is explicit (failed + reason), never a second build.
BUILD_CLAIM_LEASE_SECONDS = int(get_setting("BLAST_BUILD_CLAIM_LEASE_SECONDS", "3600"))


class BuildRequestError(ValueError):
    """Sanitized build-request failure; never echoes paths or payload bytes."""


def _validate_source_key(key: str) -> str:
    if (
        not isinstance(key, str)
        or not key.startswith(SOURCE_PREFIX)
        or ".." in Path(key).parts
        or "\\" in key
        or any(ord(ch) < 32 for ch in key)
        or len(key) > 2048
    ):
        raise BuildRequestError("invalid source object key")
    return key


def _validate_metadata(raw: object) -> BuildMetadata:
    """Reject unfrozen or private provenance before any binary is invoked."""
    if not isinstance(raw, dict) or set(raw) != set(BuildMetadata.__dataclass_fields__):
        raise BuildRequestError("incomplete build metadata")
    try:
        metadata = BuildMetadata(**{k: raw[k] for k in BuildMetadata.__dataclass_fields__})
        metadata.validate()
    except (TypeError, IndexBuildError, ValueError) as exc:
        raise BuildRequestError(str(exc)) from None
    if public_source_url(metadata.source_url) is None:
        raise BuildRequestError("source_url must be public attribution")
    return metadata


def _download_source(key: str, destination: Path) -> str:
    """Stream one reviewed FASTA object with a bounded size, no shell."""
    _validate_source_key(key)
    bucket, object_key = parse_s3_path(key)
    if not bucket or not object_key:
        raise BuildRequestError("invalid source object key")
    client = get_s3_client()
    response = client.get_object(Bucket=bucket, Key=object_key)
    digest = hashlib.sha256()
    size = 0
    with destination.open("xb") as target, response["Body"] as body:
        for chunk in body.iter_chunks(chunk_size=1024 * 1024):
            size += len(chunk)
            if size > MAX_SOURCE_BYTES:
                raise BuildRequestError("source FASTA exceeds size limit")
            digest.update(chunk)
            target.write(chunk)
    if size == 0:
        raise BuildRequestError("empty source FASTA")
    return digest.hexdigest()


def _sanitize_error(exc: Exception) -> str:
    """Child stderr and local paths must never reach the catalog record."""
    if isinstance(exc, IndexBuildError):
        return str(exc)
    if isinstance(exc, BuildRequestError):
        return str(exc)
    return f"{type(exc).__name__}: index build failed"


def _remove_unpublished_index(directory: Path) -> None:
    """Remove an index this attempt materialized but never published.

    Strict on purpose: a half-built index left on the immutable volume is more
    dangerous than a failed build, so a cleanup failure must surface instead of
    being silently ignored. A symlink is refused rather than followed.
    """
    if directory.is_symlink():
        raise OSError("refusing to remove a symlinked index directory")
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass  # Already gone; nothing left behind.


@celery_app.task(bind=True, name=BLAST_BUILD_INDEX_TASK, queue="blast")
def build_index(self: Task, build_id: str | None = None, **kwargs: object) -> dict:
    """Build, validate and atomically publish one immutable NCBI index.

    ``build_id`` is the only request-supplied identifier. Everything else
    (paths, binaries, provenance) is read from the authoritative build row in
    PostgreSQL and operator configuration, so a forged outbox event cannot
    repoint the builder at an arbitrary path.

    The whole build runs in a private staging directory. Any failure clears
    staging and the unpublished content-addressed directory this attempt
    created, then records ``failed`` with a sanitized reason; a published or
    reused index is never deleted or repaired implicitly.
    """
    if not build_id:
        raise BuildRequestError("build_id is required")
    try:
        identifier = str(uuid.UUID(build_id))
    except (ValueError, TypeError, AttributeError):
        raise BuildRequestError("invalid build_id") from None

    with get_db() as session:
        store = BlastIndexBuildStore(session)
        observed = store.get_state(identifier)
        if observed is None:
            raise BuildRequestError("unknown build request")
        state, request = observed
        validate_build_state(state)
        if state in {"published", "failed", "ready"}:
            return {"build_id": identifier, "skipped": True, "state": state}
        if state in {"building", "validating"}:
            # A redelivery must not start a second builder. If the original
            # attempt's lease has expired, close the claim explicitly so an
            # admin can submit a new immutable build instead of staring at a
            # permanently stuck row.
            if store.expire_stale_claim(identifier, BUILD_CLAIM_LEASE_SECONDS):
                return {"build_id": identifier, "skipped": True, "state": "failed"}
            return {"build_id": identifier, "skipped": True, "state": state}
        if not store.transition(identifier, "building", expected="pending"):
            return {"build_id": identifier, "skipped": True, "state": state}

    self.update_state(state="STARTED", meta={"progress": 10})
    staging_root = None
    # The builder publishes the content-addressed directory with an atomic
    # rename *before* the catalog guard runs. Track the one this attempt
    # created so a failure before publication can remove it again. A reused
    # (already published) identity belongs to another attempt and is never
    # deleted here.
    owned_index: Path | None = None
    published = False
    try:
        metadata = _validate_metadata(request["build_metadata"])
        db_type = request["db_type"]
        if db_type not in {"nucl", "prot"}:
            raise BuildRequestError("invalid db_type")
        source_key = _validate_source_key(request["source_object_key"])

        index_root = INDEX_ROOT
        if not index_root.is_absolute() or index_root.is_symlink():
            raise BuildRequestError("index root must be an absolute local directory")
        index_root.mkdir(parents=True, exist_ok=True)

        staging_root = Path(tempfile.mkdtemp(prefix=".blast-build-"))
        source = staging_root / "source.fasta"
        source_sha256 = _download_source(source_key, source)
        self.update_state(state="STARTED", meta={"progress": 30})

        limits = BuildLimits(max_source_bytes=MAX_SOURCE_BYTES)
        result = build_immutable_index(
            source, index_root, db_type, metadata,
            makeblastdb_bin=MAKEBLASTDB_BIN,
            blastdbcmd_bin=BLASTDBCMD_BIN,
            limits=limits,
        )
        identity = validate_identity(result["index_identity"])
        if not result["reused"]:
            owned_index = index_root / identity
        self.update_state(state="STARTED", meta={"progress": 60})

        with get_db() as session:
            store = BlastIndexBuildStore(session)
            if not store.transition(identifier, "validating", expected="building"):
                return {"build_id": identifier, "skipped": True, "state": "building"}
        # Independent re-verification of every artifact checksum and BLAST
        # content before publication. The builder already validated its own
        # output; this is the state machine's explicit validation stage.
        verified = verify_index(
            index_root, identity, blastdbcmd_bin=BLASTDBCMD_BIN, limits=limits
        )
        manifest_request = verified["manifest"]["request"]
        if manifest_request["source_sha256"] != source_sha256:
            raise BuildRequestError("source checksum mismatch during validation")
        self.update_state(state="STARTED", meta={"progress": 85})

        # ``validating -> publishing`` is a required step: the publication
        # write below is guarded on exactly that state, so skipping it would
        # reject every build. Publishing is the last claim a builder takes
        # before it binds the identity to the catalog row.
        with get_db() as session:
            store = BlastIndexBuildStore(session)
            if not store.transition(identifier, "publishing", expected="validating"):
                return {"build_id": identifier, "skipped": True, "state": "validating"}

        with get_db() as session:
            store = BlastIndexBuildStore(session)
            publish_ok = store.publish(
                identifier,
                identity=identity,
                source_sha256=source_sha256,
                sequence_count=manifest_request["sequence_count"],
                total_length=manifest_request["letter_count"],
                database_id=request["database_id"],
            )
        if not publish_ok:
            raise BuildRequestError("publication rejected by guarded state transition")
        published = True
        self.update_state(state="STARTED", meta={"progress": 100})
        logger.info("Published immutable BLAST index %s for build %s", identity, identifier)
        return {
            "build_id": identifier,
            "state": "published",
            "index_identity": identity,
            "index_prefix": result["index_prefix"],
            "reused": result["reused"],
        }
    except Exception as exc:
        reason = _sanitize_error(exc)
        logger.error("BLAST index build %s failed: %s", identifier, reason)
        try:
            with get_db() as session:
                BlastIndexBuildStore(session).fail(identifier, reason=reason)
        except Exception as db_err:
            logger.error("Failed to record BLAST index build failure: %s", type(db_err).__name__)
        raise
    finally:
        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)
        if owned_index is not None and not published:
            # The directory was created by this attempt but never bound to a
            # published catalog row, so it is an unreachable orphan. Removing
            # it keeps a failed build from leaving half-published state behind;
            # published/reused identities are deliberately left untouched.
            # A cleanup failure is fatal, not silently swallowed.
            _remove_unpublished_index(owned_index)


__all__ = ["build_index", "BuildRequestError"]

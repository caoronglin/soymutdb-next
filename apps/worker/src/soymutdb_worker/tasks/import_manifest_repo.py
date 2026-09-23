"""Sync import-manifest repository for the worker (ADR-0005 / P2-3).

The API persists the manifest with an async SQLAlchemy session; the Celery worker
drives the same lifecycle over its sync session while it runs an import. Both
sides import only the framework-neutral contract in ``soymutdb_import_protocol``
(statuses, transitions, fingerprint) so the worker never imports the API runtime
(H4), and the state machine is enforced identically on both sides.

This repository is deliberately narrow: it selects/inserts/updates the columns
the import protocol needs and never creates schema (migrations own the table).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from soymutdb_import_protocol import (
    ImportManifestStatus,
    can_transition,
    compute_import_fingerprint,
    is_portal_visible_status,
)
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from soymutdb_worker.tables import import_manifests


class InvalidManifestTransition(Exception):
    """Raised when a manifest state transition is not permitted (mirrors the API)."""


class ManifestRow(dict):
    """A manifest row as a plain mapping keyed by column name."""

    @property
    def import_id(self) -> str:
        return str(self["import_id"])

    @property
    def status(self) -> str:
        return str(self["status"])

    @property
    def fingerprint(self) -> str:
        return str(self["fingerprint"])


_FINGERPRINT_FIELDS = (
    "source_sha256",
    "release_id",
    "assembly_id",
    "importer_version",
    "schema_version",
    "normalization_version",
    "config_hash",
)


def _fingerprint_for(fields: dict) -> str:
    return compute_import_fingerprint(**{name: fields[name] for name in _FINGERPRINT_FIELDS})


def start_or_resume(
    session: Session, *, import_id: str | None = None, **fields: object
) -> tuple[ManifestRow, bool]:
    """Return ``(manifest, created)`` for a logical import (idempotent start).

    A retry with the same semantic fingerprint returns the existing manifest
    unchanged; the unique index on ``fingerprint`` wins any insert race, and the
    winner is re-read so a concurrent creator is not double-inserted.
    """
    fingerprint = _fingerprint_for(fields)
    existing = _find_by_fingerprint(session, fingerprint)
    if existing is not None:
        return existing, False

    values = {name: fields.get(name) for name in _FINGERPRINT_FIELDS}
    values.update(
        {
            "import_id": import_id or uuid.uuid4().hex,
            "fingerprint": fingerprint,
            "status": ImportManifestStatus.CREATED.value,
            "started_at": fields.get("started_at") or datetime.now(UTC),
            "expected_rows": fields.get("expected_rows"),
            "written_rows": fields.get("written_rows"),
        }
    )
    try:
        session.execute(import_manifests.insert(), values)
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = _find_by_fingerprint(session, fingerprint)
        if winner is None:
            raise
        return winner, False
    row = _find_by_fingerprint(session, fingerprint)
    assert row is not None  # just inserted
    return row, True


# PostgreSQL advisory-lock namespaces are signed 32-bit integers. The
# task-level fence in ingest.py owns its own namespace; this one serializes
# different Celery deliveries that share a SEMANTIC FINGERPRINT (ADR-0005):
# the same logical import must have at most one active writer/finalizer, and
# "Celery usually does not redeliver" is not a proof.
MANIFEST_LOCK_NAMESPACE = 0x494D5032


def _manifest_lock_key(fingerprint: str) -> int:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big", signed=False) - 2**31


@contextmanager
def manifest_lock(session: Session, fingerprint: str) -> Iterator[None]:
    """Hold the per-fingerprint session advisory lock around an import.

    ``pg_advisory_lock`` blocks until the key is free: a second worker waits for
    the first finalize, then re-reads the manifest and sees PUBLISHED.

    The lock lives on its OWN connection, not the business session: SQLAlchemy
    returns a Session's connection to the pool at every commit, so a lock taken
    through the session would be unlocked from a different connection (or leak
    on the old one) as soon as a manifest transition commits. A dedicated
    ``engine.connect()`` pins one physical connection for the whole critical
    section. If the unlock cannot be proven, the connection is invalidated so
    PostgreSQL releases the lock with the socket instead of returning a
    locked connection to the pool.
    """
    key = _manifest_lock_key(fingerprint)
    parameters = {"namespace": MANIFEST_LOCK_NAMESPACE, "key": key}
    connection = session.get_bind().connect()
    connection.execute(text("SELECT pg_advisory_lock(:namespace, :key)"), parameters)
    try:
        yield
    finally:
        unlocked = False
        try:
            unlocked = bool(
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :key)"), parameters
                ).scalar_one()
            )
        finally:
            if unlocked:
                connection.close()
            else:  # pragma: no cover - only on an unlock anomaly
                connection.invalidate()
        if not unlocked:  # pragma: no cover - only on an unlock anomaly
            raise RuntimeError(
                f"advisory lock for fingerprint {fingerprint[:12]}… was not owned at release"
            )


def transition(
    session: Session, manifest: ManifestRow, target: ImportManifestStatus
) -> ManifestRow:
    """Advance a manifest to ``target`` if allowed; persist + refresh the row."""
    current = manifest.status
    if not can_transition(current, target):
        raise InvalidManifestTransition(f"{current} -> {target.value}")
    values: dict[str, object] = {"status": target.value, "updated_at": datetime.now(UTC)}
    if target is ImportManifestStatus.PUBLISHED:
        values["completed_at"] = datetime.now(UTC)
    session.execute(
        update(import_manifests)
        .where(import_manifests.c.import_id == manifest.import_id)
        .values(**values)
    )
    session.commit()
    updated = get(session, manifest.import_id)
    assert updated is not None
    return updated


def record_counts(session: Session, manifest: ManifestRow, *, written_rows: int) -> ManifestRow:
    session.execute(
        update(import_manifests)
        .where(import_manifests.c.import_id == manifest.import_id)
        .values(written_rows=written_rows, updated_at=datetime.now(UTC))
    )
    session.commit()
    return get(session, manifest.import_id)  # type: ignore[return-value]


def mark_failed(session: Session, manifest: ManifestRow, failure_code: str) -> ManifestRow:
    return transition_or_fail(
        session, manifest, ImportManifestStatus.FAILED, failure_code
    )


def transition_or_fail(
    session: Session, manifest: ManifestRow, target: ImportManifestStatus, failure_code: str
) -> ManifestRow:
    if not can_transition(manifest.status, target):
        raise InvalidManifestTransition(f"{manifest.status} -> {target.value}")
    session.execute(
        update(import_manifests)
        .where(import_manifests.c.import_id == manifest.import_id)
        .values(
            status=target.value,
            failure_code=failure_code,
            updated_at=datetime.now(UTC),
        )
    )
    session.commit()
    return get(session, manifest.import_id)  # type: ignore[return-value]


def is_published(manifest: ManifestRow) -> bool:
    return is_portal_visible_status(manifest.status)


def _find_by_fingerprint(session: Session, fingerprint: str) -> ManifestRow | None:
    result = session.execute(
        select(*import_manifests.c).where(import_manifests.c.fingerprint == fingerprint)
    ).mappings().first()
    return ManifestRow(dict(result)) if result is not None else None


def get(session: Session, import_id: str) -> ManifestRow | None:
    result = session.execute(
        select(*import_manifests.c).where(import_manifests.c.import_id == import_id)
    ).mappings().first()
    return ManifestRow(dict(result)) if result is not None else None

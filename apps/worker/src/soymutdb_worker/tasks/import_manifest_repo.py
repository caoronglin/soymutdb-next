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

import uuid
from datetime import UTC, datetime

from soymutdb_import_protocol import (
    ImportManifestStatus,
    can_transition,
    compute_import_fingerprint,
    is_portal_visible_status,
)
from sqlalchemy import select, update
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

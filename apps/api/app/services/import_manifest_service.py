"""Import manifest control-plane service (ADR-0005 / Phase 2 P2-1).

Idempotency contract: a logical import is keyed by its semantic fingerprint.
``start_or_resume`` returns the existing manifest for a fingerprint, so a retry
never creates a second logical import. State transitions are guarded by an
explicit allowed-transition map, and only ``PUBLISHED`` is visible to the
portal (publish-visibility rule).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from soymutdb_import_protocol import (
    can_transition,
    is_portal_visible_status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.import_manifest import (
    ImportManifest,
    ImportManifestStatus,
)
from .import_fingerprint import compute_import_fingerprint

# Fingerprint inputs, passed through to compute_import_fingerprint.
_FINGERPRINT_FIELDS = (
    "source_sha256",
    "release_id",
    "assembly_id",
    "importer_version",
    "schema_version",
    "normalization_version",
    "config_hash",
)


class InvalidManifestTransition(Exception):
    """Raised when a manifest state transition is not permitted."""


__all__ = [
    "InvalidManifestTransition",
    "can_transition",
    "find_by_fingerprint",
    "is_portal_visible",
    "start_or_resume",
    "transition",
]


async def find_by_fingerprint(
    db: AsyncSession, fingerprint: str
) -> ImportManifest | None:
    result = await db.execute(
        select(ImportManifest).where(ImportManifest.fingerprint == fingerprint)
    )
    return result.scalar_one_or_none()


async def start_or_resume(
    db: AsyncSession, *, import_id: str | None = None, **fields: object
) -> tuple[ImportManifest, bool]:
    """Return ``(manifest, created)`` for a logical import.

    Idempotent: if a manifest already exists for the computed fingerprint it is
    returned unchanged with ``created=False``; a concurrent creator that wins
    the unique-fingerprint race is tolerated by re-reading the winner.
    """
    fingerprint = compute_import_fingerprint(
        **{name: fields[name] for name in _FINGERPRINT_FIELDS}  # type: ignore[arg-type]
    )
    existing = await find_by_fingerprint(db, fingerprint)
    if existing is not None:
        return existing, False

    manifest = ImportManifest(
        import_id=import_id or uuid.uuid4().hex,
        fingerprint=fingerprint,
        status=ImportManifestStatus.CREATED.value,
        **fields,
    )
    db.add(manifest)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = await find_by_fingerprint(db, fingerprint)
        if winner is None:
            raise
        return winner, False
    await db.refresh(manifest)
    return manifest, True


def is_portal_visible(manifest: ImportManifest) -> bool:
    """Publish-visibility rule: the portal sees only PUBLISHED imports."""
    return is_portal_visible_status(manifest.status)


async def transition(
    db: AsyncSession, manifest: ImportManifest, target: ImportManifestStatus
) -> ImportManifest:
    """Advance a manifest to ``target`` if the transition is allowed."""
    if not can_transition(manifest.status, target):
        raise InvalidManifestTransition(f"{manifest.status} -> {target.value}")
    manifest.status = target.value
    if target is ImportManifestStatus.PUBLISHED:
        manifest.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(manifest)
    return manifest

"""P2-1 / ADR-0005: import manifest control plane (PostgreSQL-backed).

The manifest is the exactly-once guard for imports. It must default to CREATED,
expose the ADR-0005 resumable states, and enforce a unique semantic fingerprint
so the same logical import cannot be recorded twice.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_manifest import (
    RESUMABLE_STATES,
    ImportManifest,
    ImportManifestStatus,
)
from app.services.import_fingerprint import compute_import_fingerprint


def _fingerprint(source_sha256: str = "a" * 64) -> str:
    return compute_import_fingerprint(
        source_sha256=source_sha256,
        release_id=1,
        assembly_id=2,
        importer_version="imp-1",
        schema_version="sch-1",
        normalization_version="norm-1",
        config_hash="cfg-1",
    )


def _manifest(*, import_id: str, fingerprint: str) -> ImportManifest:
    return ImportManifest(
        import_id=import_id,
        fingerprint=fingerprint,
        source_sha256="a" * 64,
        release_id=1,
        assembly_id=2,
        importer_version="imp-1",
        schema_version="sch-1",
        normalization_version="norm-1",
        config_hash="cfg-1",
    )


async def test_manifest_defaults_to_created(db_session: AsyncSession) -> None:
    manifest = _manifest(import_id=uuid.uuid4().hex, fingerprint=_fingerprint())
    db_session.add(manifest)
    await db_session.commit()

    stored = (
        await db_session.execute(
            select(ImportManifest).where(
                ImportManifest.import_id == manifest.import_id
            )
        )
    ).scalar_one()
    assert stored.status == ImportManifestStatus.CREATED.value
    assert stored.expected_rows is None
    assert stored.created_at is not None


def test_resumable_states_are_created_and_failed() -> None:
    assert RESUMABLE_STATES == {
        ImportManifestStatus.CREATED,
        ImportManifestStatus.FAILED,
    }


async def test_duplicate_fingerprint_is_rejected(db_session: AsyncSession) -> None:
    """Same semantic input must not create a second logical import."""
    fingerprint = _fingerprint(source_sha256="c" * 64)
    db_session.add(_manifest(import_id=uuid.uuid4().hex, fingerprint=fingerprint))
    await db_session.flush()

    db_session.add(_manifest(import_id=uuid.uuid4().hex, fingerprint=fingerprint))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

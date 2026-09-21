"""P2-1 / ADR-0005: import manifest control-plane service (PostgreSQL-backed)."""


import pytest
from app.models.import_manifest import ImportManifestStatus
from app.services.import_manifest_service import (
    InvalidManifestTransition,
    can_transition,
    find_by_fingerprint,
    is_portal_visible,
    start_or_resume,
    transition,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _fields(source_sha256: str = "a" * 64, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_sha256": source_sha256,
        "release_id": 1,
        "assembly_id": 2,
        "importer_version": "imp-1",
        "schema_version": "sch-1",
        "normalization_version": "norm-1",
        "config_hash": "cfg-1",
    }
    base.update(over)
    return base


async def test_start_creates_then_is_idempotent(db_session: AsyncSession) -> None:
    fields = _fields(source_sha256="d" * 64)
    first, created1 = await start_or_resume(db_session, **fields)
    assert created1 is True
    assert first.status == ImportManifestStatus.CREATED.value

    second, created2 = await start_or_resume(db_session, **fields)
    assert created2 is False
    assert second.import_id == first.import_id  # same logical import, no duplicate

    found = await find_by_fingerprint(db_session, first.fingerprint)
    assert found is not None and found.import_id == first.import_id


async def test_distinct_semantics_create_distinct_manifests(
    db_session: AsyncSession,
) -> None:
    a, _ = await start_or_resume(db_session, **_fields(source_sha256="e" * 64))
    b, _ = await start_or_resume(
        db_session, **_fields(source_sha256="e" * 64, release_id=7)
    )
    assert a.import_id != b.import_id
    assert a.fingerprint != b.fingerprint


async def test_allowed_transition_and_guarded_invalid(
    db_session: AsyncSession,
) -> None:
    manifest, _ = await start_or_resume(db_session, **_fields(source_sha256="f" * 64))
    advanced = await transition(db_session, manifest, ImportManifestStatus.PARSING)
    assert advanced.status == ImportManifestStatus.PARSING.value

    with pytest.raises(InvalidManifestTransition):
        await transition(db_session, advanced, ImportManifestStatus.PUBLISHED)


async def test_publish_visibility_only_after_published(
    db_session: AsyncSession,
) -> None:
    manifest, _ = await start_or_resume(db_session, **_fields(source_sha256="1" * 64))
    assert is_portal_visible(manifest) is False
    await transition(db_session, manifest, ImportManifestStatus.PARSING)
    await transition(db_session, manifest, ImportManifestStatus.WRITING)
    await transition(db_session, manifest, ImportManifestStatus.VERIFYING)
    published = await transition(db_session, manifest, ImportManifestStatus.PUBLISHED)
    assert is_portal_visible(published) is True
    assert published.completed_at is not None


def test_retry_from_failed_is_allowed() -> None:
    assert can_transition(ImportManifestStatus.FAILED.value, ImportManifestStatus.CREATED)
    assert not can_transition(
        ImportManifestStatus.PUBLISHED.value, ImportManifestStatus.CREATED
    )
    assert not can_transition("bogus", ImportManifestStatus.PARSING)

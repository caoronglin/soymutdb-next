"""V02: public_id issuance and publication guard.

Covers:
- issuance never changes an already-issued public_id;
- a candidate collision retries with a fresh candidate and never overwrites
  the already-issued identifier;
- concurrent issuance through independent PG connections resolves the unique
  conflict without corrupting either record;
- publishing a release that still contains a mutant line without a
  public_id fails and leaves the release state machine untouched;
- publishing a fully-identified release succeeds.

Requires the real PostgreSQL fixture (``SOYMUTDB_TEST_DATABASE_URL`` or
testcontainers); no SQLite or in-memory substitute is involved.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.core.public_ids import generate_public_id
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease, DataSet, ImportStatus, ReleaseDataSet
from app.models.variant import MutantLine
from app.services.public_id_service import ensure_public_id
from app.services.release_service import ReleaseNotReady, publish_release


@pytest_asyncio.fixture
async def fresh_session(db_connection):
    """A session on the same outer transaction that has not yet autobegun,
    mirroring a fresh per-request session for ``publish_release``."""
    factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def publication_setup(db_session):
    """A previous published release plus a READY release prepared for publish."""
    previous = Release(
        version="pid-previous-release",
        name="previous release",
        status=ReleaseStatus.PUBLISHED,
        active_at=None,
        manifest={"version": "pid-previous", "provenance": [{"sha256": "a" * 64}]},
    )
    target = Release(
        version="pid-target-release",
        name="target release",
        status=ReleaseStatus.READY,
        manifest={"version": "pid-target", "provenance": [{"sha256": "b" * 64}]},
    )
    db_session.add_all([previous, target])
    await db_session.flush()

    db_session.add(ActiveRelease(id=1, release_id=previous.id))
    dataset = DataSet(
        type="mutant-lines",
        release_id=target.id,
        source_objects=[{"sha256": "c" * 64, "etag": "etag-1"}],
        status=ImportStatus.READY,
    )
    db_session.add(dataset)
    await db_session.flush()
    db_session.add(ReleaseDataSet(release_id=target.id, data_set_id=dataset.id))
    await db_session.flush()
    return previous, target


@pytest.mark.asyncio
async def test_ensure_public_id_never_reassigns_issued_value(db_session):
    line = MutantLine(name="pid-issued", public_id="SMKEEP001")
    db_session.add(line)
    await db_session.flush()

    result = await ensure_public_id(db_session, line)
    assert result == "SMKEEP001"
    assert line.public_id == "SMKEEP001"


@pytest.mark.asyncio
async def test_ensure_public_id_retries_on_candidate_collision(
    db_session, monkeypatch
):
    """A candidate that collides with an issued id must not steal it."""
    holder = MutantLine(name="pid-holder", public_id="SMCOLLID01")
    pending = MutantLine(name="pid-pending", public_id=None)
    db_session.add_all([holder, pending])
    await db_session.flush()
    holder_id, pending_id = holder.id, pending.id

    calls = {"n": 0}

    def fake_generate() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "SMCOLLID01"  # collides with the holder
        return generate_public_id()

    monkeypatch.setattr(
        "app.services.public_id_service.generate_public_id", fake_generate
    )

    issued = await ensure_public_id(db_session, pending)
    assert issued != "SMCOLLID01"
    await db_session.flush()

    # The holder's issued id is untouched; the pending line got a fresh one.
    reloaded = (
        await db_session.execute(
            select(MutantLine).where(MutantLine.id.in_([holder_id, pending_id]))
        )
    ).scalars().all()
    by_id = {row.id: row.public_id for row in reloaded}
    assert by_id[holder_id] == "SMCOLLID01"
    assert by_id[pending_id] == issued


@pytest.mark.asyncio
async def test_concurrent_issuance_resolves_unique_conflict(test_engine):
    """Two independent PG connections race for the same candidate.

    Both issuers receive the same first candidate; the unique constraint
    rejects the loser, which retries with a fresh candidate. Both lines end
    with distinct, non-null public ids and no data corruption.
    """
    seeded = [{"name": "pid-race-a"}, {"name": "pid-race-b"}]
    async with test_engine.begin() as conn:
        await conn.execute(insert(MutantLine), seeded)

    calls = {"n": 0}

    def fake_generate() -> str:
        calls["n"] += 1
        if calls["n"] <= 2:
            return "SMRACE0001"  # both concurrent issuers pick the same id
        return generate_public_id()

    import app.services.public_id_service as service_module

    original = service_module.generate_public_id
    service_module.generate_public_id = fake_generate
    try:
        results: dict[str, str | None] = {}

        async def issue(line_name: str) -> None:
            factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
            async with factory() as session:
                line = (
                    await session.execute(
                        select(MutantLine).where(MutantLine.name == line_name)
                    )
                ).scalar_one()
                results[line_name] = await ensure_public_id(session, line)
                # Commit so the loser's concurrent unique check observes the
                # winner's committed id and retries with a fresh candidate.
                await session.commit()

        import asyncio

        await asyncio.gather(issue("pid-race-a"), issue("pid-race-b"))
    finally:
        service_module.generate_public_id = original
        async with test_engine.begin() as conn:
            await conn.execute(
                delete(MutantLine).where(
                    MutantLine.name.in_(["pid-race-a", "pid-race-b"])
                )
            )

    assert calls["n"] >= 2
    assert results["pid-race-a"] and results["pid-race-b"]
    assert results["pid-race-a"] != results["pid-race-b"]


@pytest.mark.asyncio
async def test_publish_release_fails_when_line_missing_public_id(
    publication_setup, db_session, fresh_session
):
    previous, target = publication_setup
    db_session.add(
        MutantLine(name="pid-unissued", public_id=None, release_id=target.id)
    )
    await db_session.flush()

    with pytest.raises(ReleaseNotReady, match="no public_id"):
        await publish_release(
            fresh_session, release_id=target.id, actor_id=None, reason="test publish"
        )

    await db_session.flush()
    status = (
        await db_session.execute(
            select(Release.status).where(Release.id == target.id)
        )
    ).scalar_one()
    pointer = (
        await db_session.execute(select(ActiveRelease.release_id).where(ActiveRelease.id == 1))
    ).scalar_one()
    assert status == ReleaseStatus.READY.value
    assert pointer == previous.id


@pytest.mark.asyncio
async def test_publish_release_succeeds_when_all_lines_have_public_id(
    publication_setup, db_session, fresh_session
):
    previous, target = publication_setup
    db_session.add(
        MutantLine(
            name="pid-ready",
            public_id=generate_public_id(),
            release_id=target.id,
        )
    )
    await db_session.flush()

    published = await publish_release(
        fresh_session, release_id=target.id, actor_id=None, reason="test publish"
    )
    assert published.status == ReleaseStatus.PUBLISHED.value
    pointer = (
        await db_session.execute(select(ActiveRelease.release_id).where(ActiveRelease.id == 1))
    ).scalar_one()
    assert pointer == target.id

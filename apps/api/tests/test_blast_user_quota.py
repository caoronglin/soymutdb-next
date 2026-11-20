"""Account resource reservations serialize across real PostgreSQL transactions."""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import NotFoundError, RateLimitExceededError
from app.models.auth import User
from app.models.blast import BlastDatabase, BlastJob
from app.models.content import Release
from app.models.genomic import Assembly
from app.models.outbox import OutboxEvent
from app.schemas.blast import BlastSubmitRequest
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


@pytest.fixture
async def quota_data(test_engine, monkeypatch):
    from app.services import blast_service

    monkeypatch.setattr(blast_service.settings, "blast_max_active_jobs_per_user", 3)
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:20]
    async with factory() as session:
        release = Release(version=f"quota-{suffix}", name="quota", status="published")
        owner = User(username=f"quota-{suffix}", email=f"quota-{suffix}@example.org",
                     password_hash="unused")
        session.add_all([release, owner])
        await session.flush()
        assembly = Assembly(name=f"quota-{suffix}", version="v4", release_id=release.id)
        session.add(assembly)
        await session.flush()
        catalog = BlastDatabase(name=f"quota_{suffix}", db_type="prot", assembly_id=assembly.id,
                                file_path="/private/unused", engine="diamond", build_status="ready")
        session.add(catalog)
        await session.commit()
    context = ReleaseContext(release_id=release.id, assembly_id=assembly.id, assembly=assembly.name)
    try:
        yield factory, owner.id, catalog.id, context
    finally:
        async with factory() as session:
            jobs = (await session.scalars(select(BlastJob.id).where(
                BlastJob.database_id == catalog.id,
            ))).all()
            if jobs:
                await session.execute(delete(OutboxEvent).where(
                    OutboxEvent.aggregate_id.in_([str(job) for job in jobs]),
                ))
            await session.execute(delete(BlastJob).where(BlastJob.database_id == catalog.id))
            await session.execute(delete(BlastDatabase).where(BlastDatabase.id == catalog.id))
            await session.execute(delete(Assembly).where(Assembly.id == assembly.id))
            await session.execute(delete(Release).where(Release.id == release.id))
            await session.execute(delete(User).where(User.id == owner.id))
            await session.commit()


def submission(database_id):
    return BlastSubmitRequest(engine="diamond", database_id=database_id,
                              query_sequence="MKVLAAGIVGLNLGGK")


def job(owner, catalog, status="pending", expiry="future"):
    return BlastJob(
        user_id=owner, database_id=catalog, program="blastp", query_sequence="MKVLAAGIVGLNLGGK",
        status=status, parameters={}, submitted_at=datetime.now(UTC),
        expires_at=None if expiry is None else datetime.now(UTC) + timedelta(
            days=-1 if expiry == "past" else 1,
        ),
    )


async def test_account_quota_counts_only_pending_running_unexpired_or_legacy_null(quota_data):
    factory, owner, catalog, context = quota_data
    async with factory() as session:
        active = [job(owner, catalog), job(owner, catalog, "running"),
                  job(owner, catalog, expiry=None)]
        session.add_all([*active, job(owner, catalog, "completed"), job(owner, catalog, "failed"),
                         job(owner, catalog, expiry="past"), job(owner, catalog, "expired")])
        await session.commit()
    async with factory() as session:
        with pytest.raises(RateLimitExceededError) as error:
            await BlastService().submit_job(session, owner, submission(catalog),
                                            release_context=context)
        assert error.value.status_code == 429
        assert error.value.retry_after == 60
        await session.rollback()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(BlastJob).where(
            BlastJob.user_id == owner,
        )) == 7
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id.in_([str(entry.id) for entry in active]),
        )) == 0
        completed = await session.get(BlastJob, active[0].id)
        completed.status = "completed"
        await session.commit()
    async with factory() as session:
        accepted = await BlastService().submit_job(session, owner, submission(catalog),
                                                   release_context=context)
        assert accepted.job_id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id == accepted.job_id,
        )) == 1


async def test_concurrent_separate_transactions_reserve_only_one_remaining_slot(quota_data):
    factory, owner, catalog, context = quota_data
    async with factory() as session:
        session.add_all([job(owner, catalog), job(owner, catalog, "running")])
        await session.commit()
    start = asyncio.Event()

    async def submit():
        async with factory() as session:
            await start.wait()
            try:
                result = await BlastService().submit_job(session, owner, submission(catalog),
                                                         release_context=context)
                return result.job_id
            except RateLimitExceededError:
                await session.rollback()
                return None

    tasks = [asyncio.create_task(submit()) for _ in range(4)]
    start.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=20)
    accepted = [result for result in results if result]
    assert len(accepted) == 1
    async with factory() as session:
        jobs = (await session.scalars(select(BlastJob.id).where(BlastJob.user_id == owner))).all()
        assert len(jobs) == 3
        assert await session.scalar(select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id.in_([str(entry) for entry in jobs]),
        )) == 1


async def test_missing_locked_account_cannot_create_jobs_and_public_skips_user_cap(quota_data):
    factory, _, catalog, context = quota_data
    async with factory() as session:
        with pytest.raises(NotFoundError, match="account not found"):
            await BlastService().submit_job(session, uuid.uuid4(), submission(catalog),
                                            release_context=context)
        await session.rollback()
    async with factory() as session:
        public = await BlastService().submit_job(session, None, submission(catalog),
                                                 release_context=context)
        assert public.job_id


@pytest.mark.parametrize("value", [0, 21])
def test_account_quota_configuration_is_bounded(value):
    with pytest.raises(ValidationError):
        Settings(blast_max_active_jobs_per_user=value)

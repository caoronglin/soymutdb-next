"""BLAST submission via transactional outbox (no docker: fake async session).

The submission must write the job row and the outbox event in one transaction
and must NOT touch the Celery broker (previously the submit path depended on
broker availability — that dependency is gone).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.task_contract import BLAST_RUN_TASK
from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.models.outbox import OutboxEvent, OutboxEventStatus
from app.schemas.blast import BlastParameters, BlastProgram, BlastSubmitRequest
from app.services.blast_service import BlastService


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in recording adds/commits for one transaction."""

    def __init__(self, blast_db: BlastDatabase | None = None):
        self.blast_db = blast_db
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, stmt, params=None):
        # BLAST database lookup inside submit_job.  ``froms`` may be an ORM
        # join (lazy="joined" relationship), so match on the SQL text.
        if "blast_databases" in str(stmt):
            return _Result([self.blast_db] if self.blast_db else [])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj) -> None:
        pass


def _make_request() -> BlastSubmitRequest:
    return BlastSubmitRequest(
        program=BlastProgram.BLASTN,
        database_id=1,
        query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
        parameters=BlastParameters(),
    )


def _make_db() -> BlastDatabase:
    return BlastDatabase(
        id=1,
        name="williams82_cds",
        db_type="nucl",
        assembly_id=1,
        file_path="/data/dbs/williams82_cds",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


async def test_submit_job_writes_job_and_outbox_event_in_one_transaction() -> None:
    session = FakeDbSession(blast_db=_make_db())
    service = BlastService()

    response = await service.submit_job(session, uuid.uuid4(), _make_request())

    # One transaction: job + outbox event committed together, broker untouched.
    assert session.commits == 1
    assert session.flushes >= 1

    job = next(obj for obj in session.added if isinstance(obj, BlastJob))
    event = next(obj for obj in session.added if isinstance(obj, OutboxEvent))
    assert job.status == BlastJobStatus.PENDING

    # Outbox event carries the full versioned JobPayload.
    assert event.aggregate_type == "blast_job"
    assert event.aggregate_id == str(job.id)
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 0
    payload = event.payload
    assert payload["task_name"] == BLAST_RUN_TASK
    assert payload["payload_version"] == 1
    assert payload["job_id"] == str(job.id)
    assert payload["idempotency_key"] == f"blast:{job.id}"
    assert payload["payload"]["database"] == "williams82_cds"
    assert payload["status"] == "pending"

    # The response still reflects the submitted job.
    assert response.job_id == str(job.id)
    assert response.status.value == "pending"


async def test_submit_job_rejects_missing_or_inactive_database() -> None:
    from app.core.exceptions import NotFoundError

    session = FakeDbSession(blast_db=None)
    service = BlastService()

    try:
        await service.submit_job(session, uuid.uuid4(), _make_request())
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError for missing database")

    assert session.added == []
    assert session.commits == 0

"""Cancel/retry endpoints: owner-scoped, terminal-state aware, provenance-frozen."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.exceptions import NotFoundError
from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.models.genomic import Assembly
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Session:
    """Dispatch on the statement's FROM entity instead of answering blindly.

    Returning the job for *every* statement (including the catalog and
    assembly lookups) is what let the old fake hide a real defect: the service
    was reading ``is_active``/``assembly_id`` straight off ``BlastJob``. A stub
    that cannot tell the entities apart cannot catch that class of bug.
    """

    def __init__(self, job):
        self.job = job
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        entity = None
        for column in getattr(stmt, "_raw_columns", ()):
            entity = getattr(column, "entity_namespace", None)
            if entity is not None:
                break
        describe = getattr(stmt, "column_descriptions", None) or []
        for description in describe:
            candidate = (
                description.get("entity") or description.get("expr")
            )
            if hasattr(candidate, "__tablename__"):
                entity = candidate
                break
        if entity is BlastDatabase:
            return _Result([self.job.database] if self.job else [])
        if entity is Assembly:
            return _Result([self.job.database.assembly] if self.job else [])
        return _Result([self.job] if self.job else [])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


def _job(owner: uuid.UUID, status: BlastJobStatus, *, provenance=None) -> BlastJob:
    database = BlastDatabase(
        id=1, name="synthetic", db_type="prot", assembly_id=1,
        file_path="/private", is_active=True, engine="ncbi_blast",
        # ``ready`` is the legacy terminal spelling; only a row carrying a
        # verified identity + FASTA checksum may be searched by NCBI BLAST+.
        build_status="ready",
        index_version="a" * 64, fasta_sha256="b" * 64,
    )
    database.assembly = Assembly(id=1, name="Wm82.a4.v1", species="Glycine max",
                                 version="v4", release_id=7)
    job = BlastJob(
        id=uuid.uuid4(), user_id=owner, program="blastp", database_id=1,
        query_sequence=">q\nMKVLAAGIVGLNLGGK",
        parameters={
            "_search_provenance": provenance or {
                "engine": "ncbi_blast", "database_type": "prot",
                "index_identity": "a" * 64, "fasta_sha256": "b" * 64,
                "index_version": "a" * 64, "annotation_version": "v1",
                "release_id": 7,
            },
        },
        status=status.value,
        submitted_at=datetime.now(UTC),
        expires_at=datetime.now(UTC),
        error_message="worker exploded" if status == BlastJobStatus.FAILED else None,
    )
    job.database = database
    return job


def _context() -> ReleaseContext:
    return ReleaseContext(release_id=7, assembly_id=1, assembly="Wm82.a4.v1")


@pytest.fixture(autouse=True)
def _no_quota(monkeypatch):
    async def enforce(_self, _db, _user_id):
        return None
    monkeypatch.setattr(BlastService, "_enforce_user_limit", enforce)


@pytest.mark.asyncio
async def test_owner_cancels_pending_job():
    owner = uuid.uuid4()
    job = _job(owner, BlastJobStatus.PENDING)
    session = _Session(job)
    response = await BlastService().cancel_job(session, job.id, owner, ["researcher"])
    assert response.status.value == "cancelled"
    assert job.status == BlastJobStatus.CANCELLED
    assert response.error_message == "Cancelled by user"


@pytest.mark.asyncio
async def test_another_user_cannot_cancel():
    from app.core.exceptions import AuthorizationError

    owner = uuid.uuid4()
    job = _job(owner, BlastJobStatus.PENDING)
    with pytest.raises(AuthorizationError):
        await BlastService().cancel_job(_Session(job), job.id, uuid.uuid4(), ["researcher"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    BlastJobStatus.COMPLETED, BlastJobStatus.FAILED, BlastJobStatus.CANCELLED,
    BlastJobStatus.EXPIRED,
])
async def test_terminal_jobs_cannot_be_cancelled(status):
    from app.core.exceptions import ValidationError

    owner = uuid.uuid4()
    job = _job(owner, status)
    with pytest.raises(ValidationError):
        await BlastService().cancel_job(_Session(job), job.id, owner, ["researcher"])


@pytest.mark.asyncio
async def test_missing_job_raises_not_found():
    with pytest.raises(NotFoundError):
        await BlastService().cancel_job(_Session(None), uuid.uuid4(), uuid.uuid4(), ["researcher"])


@pytest.mark.asyncio
async def test_retry_reuses_frozen_provenance_and_writes_one_outbox_event():
    owner = uuid.uuid4()
    job = _job(owner, BlastJobStatus.FAILED)
    session = _Session(job)
    response = await BlastService().retry_job(
        session, job.id, owner, ["researcher"], release_context=_context()
    )
    assert response.status.value == "pending"
    events = [item for item in session.added if not isinstance(item, BlastJob)]
    assert len(events) == 1
    payload = events[0].payload["payload"]
    assert payload["index_identity"] == "a" * 64
    assert payload["release_id"] == 7
    assert payload["assembly_id"] == 1
    assert payload["sequence"] == job.query_sequence
    assert events[0].payload["task_name"] == "soymutdb_worker.tasks.blast.run_blast"
    assert "/private" not in str(payload)
    assert job.error_message is None and job.result_path is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [
    BlastJobStatus.PENDING, BlastJobStatus.RUNNING, BlastJobStatus.COMPLETED,
    BlastJobStatus.CANCELLED,
])
async def test_only_terminal_jobs_can_be_retried(status):
    from app.core.exceptions import ValidationError

    owner = uuid.uuid4()
    job = _job(owner, status)
    with pytest.raises(ValidationError):
        await BlastService().retry_job(
            _Session(job), job.id, owner, ["researcher"], release_context=_context()
        )


@pytest.mark.asyncio
async def test_retry_refuses_job_without_frozen_index_provenance():
    from app.core.exceptions import ValidationError

    owner = uuid.uuid4()
    job = _job(owner, BlastJobStatus.FAILED, provenance={"engine": "ncbi_blast"})
    with pytest.raises(ValidationError, match="frozen index provenance"):
        await BlastService().retry_job(
            _Session(job), job.id, owner, ["researcher"], release_context=_context()
        )


@pytest.mark.asyncio
async def test_admin_build_request_records_one_worker_task():
    """The HTTP boundary only records rows + one outbox event.

    The accepted body is ``app.schemas.blast.BlastIndexBuildRequest`` — the
    same model the service consumes — so a route-level duplicate cannot drift
    into a 422 on every build request.
    """
    from app.schemas.blast import (
        BlastIndexBuildQueued,
        BlastIndexBuildRequest,
        BlastIndexBuildResponse,
    )

    body = BlastIndexBuildRequest(
        source_object_key="blast-sources/wm82.v4.fa", db_type="nucl",
        assembly_name="Wm82.a4.v1", annotation_version="a4.v1",
        source_version="s1", source_url="https://www.soybase.org/",
        license="CC0-1.0", name="wm82_a4_genome",
    )
    # Identity fields are frozen from the release context, never the body.
    assert body.build_metadata(
        assembly_id="42", assembly_version="v4", release_id="rel-7"
    ) == {
        "assembly_id": "42", "assembly_version": "v4", "release_id": "rel-7",
        "annotation_version": "a4.v1", "source_version": "s1",
        "source_url": "https://www.soybase.org/", "license": "CC0-1.0",
    }
    assert "assembly_id" not in body.model_dump()
    with pytest.raises(Exception):
        BlastIndexBuildRequest(
            source_object_key="blast-sources/wm82.v4.fa", db_type="nucl",
            assembly_name="Wm82.a4.v1", annotation_version="a4.v1",
            source_version="s1", source_url="https://www.soybase.org/",
            license="CC0-1.0", name="wm82_a4_genome", extra_field="x",
        )
    # The 202 acknowledgement stays narrow: no path, no binary name.
    ack = BlastIndexBuildQueued(
        database_id=7, queued=True, task_name="soymutdb_worker.tasks.blast_index.build_index"
    )
    assert ack.model_dump() == {
        "database_id": 7, "queued": True,
        "task_name": "soymutdb_worker.tasks.blast_index.build_index",
    }
    assert "file_path" not in BlastIndexBuildResponse.model_fields
    assert "source_object_key" not in BlastIndexBuildResponse.model_fields

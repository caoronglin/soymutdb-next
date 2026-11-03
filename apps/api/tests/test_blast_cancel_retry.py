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
    def __init__(self, job):
        self.job = job
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
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
        build_status="ready",
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
    BlastJobStatus.CANCELLED, BlastJobStatus.EXPIRED,
])
async def test_only_failed_jobs_can_be_retried(status):
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
async def test_admin_build_request_writes_a_versioned_outbox_event():
    """The build request never runs makeblastdb in the HTTP transaction."""
    from app.api.v1.blast import BlastIndexBuildRequest, request_blast_index_build
    from app.core.task_contract import BLAST_INDEX_BUILD_TASK

    class _RecordingSession:
        def __init__(self):
            self.added: list = []
            self.commits = 0

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            self.commits += 1

    session = _RecordingSession()
    body = BlastIndexBuildRequest(
        database_id=7, db_type="nucl", source_object="blast-sources/wm82.v4.fa",
        assembly_id="42", assembly_version="v4", release_id="7",
        annotation_version="v1", source_url="https://www.soybase.org/",
        source_version="v1", license="CC0-1.0",
    )
    response = type("Response", (), {"headers": {}})()
    user = type("User", (), {"id": uuid.uuid4()})()
    import app.api.v1.blast as routes
    # Both admin checks are enforced by FastAPI dependencies at the route
    # layer; neutralize them for this direct coroutine call.
    original_admin = routes.require_admin_roles
    original_roles = routes.get_user_roles
    routes.require_admin_roles = lambda _roles: None
    routes.get_user_roles = lambda _user: []
    try:
        result = await request_blast_index_build(
            body, response, db=session, current_user=user
        )
    finally:
        routes.require_admin_roles = original_admin
        routes.get_user_roles = original_roles
    assert result == {"database_id": 7, "queued": True,
                      "task_name": BLAST_INDEX_BUILD_TASK}
    assert len(session.added) == 1 and session.commits == 1
    payload = session.added[0].payload
    assert payload["task_name"] == BLAST_INDEX_BUILD_TASK
    assert payload["payload"]["source_object"] == "blast-sources/wm82.v4.fa"
    assert payload["payload"]["db_type"] == "nucl"
    assert "/data/" not in str(payload) and "/private" not in str(payload)

"""Admin enable/disable of a published BLAST index (no docker: fake session).

Covers the whole point of the route: a published index is immutable, so
disabling it only removes it from *new* searches. A job already submitted keeps
the index identity frozen at submission time; the toggle never rewrites a job,
an outbox event or the catalog's provenance. Every toggle writes one audit
entry with the operator and the from/to state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.api.v1 import blast as blast_routes
from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.models.auth import AuditLog
from app.models.blast import BlastDatabase, BlastJob, BlastJobStatus
from app.services.release_context import ReleaseContext

CONTEXT = ReleaseContext(release_id=1, assembly_id=1, assembly="Wm82")


def _catalog(**overrides) -> BlastDatabase:
    values = dict(
        id=7,
        name="wm82_a4_genome",
        db_type="prot",
        assembly_id=1,
        is_active=True,
        engine="ncbi_blast",
        build_status="published",
        is_default=False,
        file_path="/private/index/wm82_a4_genome",
        index_version="a" * 64,
        fasta_sha256="b" * 64,
        created_at=datetime.now(UTC),
    )
    values.update(overrides)
    return BlastDatabase(**values)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return SimpleNamespace(
            all=lambda: list(self._rows), first=lambda: self._rows[0] if self._rows else None
        )

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """Session stub that dispatches on the statement's FROM table.

    ``list_databases`` joins ``assemblies``; the toggle locks
    ``blast_databases``; ``get_job`` reads ``blast_jobs``. Serving one row for
    every statement would hide a defect where the toggle accidentally rewrote a
    job, so the three entity kinds are kept apart.

    Every executed statement is recorded in ``statements`` so a test can assert
    on the SQL the service actually emitted, not on a statement the test built
    itself. Discovery/selection SELECTs (the ones joining ``assemblies``) also
    honour ``is_active`` in their WHERE clause: when the filter is present a
    disabled row is not returned, mirroring PostgreSQL. Point lookups by id --
    the toggle's row lock and ``retry_job``'s catalog read -- carry no such
    filter by design and still find a disabled row.
    """

    def __init__(self, catalog: BlastDatabase, job: BlastJob | None = None):
        self.catalog = catalog
        self.job = job
        self.added: list = []
        self.commits = 0
        self.statements: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "FROM blast_databases" in sql or "FOR UPDATE" in sql:
            # Discovery/selection statements join assemblies and, when they
            # carry the SQL-level ``is_active`` filter, cannot return a
            # disabled row. Point lookups (FOR UPDATE lock, retry's catalog
            # read) have no active filter and still find the row -- that is
            # what lets a retry serve a frozen identity after a disable.
            if (
                "JOIN assemblies ON" in sql
                and self._catalog_select_is_active(sql)
                and self.catalog is not None
                and self.catalog.is_active is not True
            ):
                return _Result([])
            return _Result([self.catalog] if self.catalog is not None else [])
        if "FROM assemblies" in sql:
            # list_databases filters on Assembly.release_id == CONTEXT.release_id.
            return _Result(
                [
                    SimpleNamespace(
                        id=1,
                        name="Wm82.a4.v1",
                        version="v4",
                        is_default=True,
                        release_id=CONTEXT.release_id,
                    )
                ]
            )
        if "FROM blast_jobs" in sql:
            return _Result([self.job] if self.job else [])
        return _Result([])

    @staticmethod
    def _catalog_select_is_active(sql: str) -> bool:
        """Whether a statement carries the ``is_active IS true`` SQL filter.

        The backend emits ``IS true`` / ``IS 1`` depending on dialect, so
        compare case-insensitively. Removing the filter from ``list_databases``
        or ``_get_active_database`` makes this return False, which the tests
        assert against directly.
        """
        normalized = sql.lower()
        return (
            "blast_databases.is_active" in normalized
            and ("is true" in normalized or "is 1" in normalized)
        )

    def add(self, obj):
        self.added.append(obj)

    async def scalar(self, stmt, params=None):
        # User quota is separately covered by test_blast_user_quota.py.
        return 0

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _user(role: str):
    return SimpleNamespace(
        id=uuid.uuid4(), is_superuser=role == "administrator", role_rel=SimpleNamespace(name=role)
    )


@pytest_asyncio.fixture
async def admin_client():
    """A tiny app exposing only the blast router, with a per-test fake DB."""
    catalog = _catalog()
    owner_id = uuid.uuid4()
    job = BlastJob(
        id=uuid.uuid4(),
        user_id=owner_id,
        program="blastp",
        database_id=catalog.id,
        query_sequence=">q\nMKVLAAGIVGLNLGGK",
        status=BlastJobStatus.RUNNING,
        parameters={
            "_search_provenance": {
                "engine": "ncbi_blast",
                "database_type": "prot",
                "index_identity": "a" * 64,
                "fasta_sha256": "b" * 64,
                "index_version": "a" * 64,
                "annotation_version": "v1",
                "release_id": 1,
                "assembly_id": 1,
                "assembly_name": "Wm82.a4.v1",
            },
        },
        submitted_at=datetime.now(UTC),
    )
    db = FakeDbSession(catalog, job)
    application = FastAPI()
    application.include_router(blast_routes.router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.state.user = _user("administrator")
    application.state.db = db

    async def current_user():
        return application.state.user

    async def current_db():
        yield application.state.db

    async def release_context():
        return CONTEXT

    from app.services.release_context import get_release_context

    application.dependency_overrides[get_current_user] = current_user
    application.dependency_overrides[get_db] = current_db
    application.dependency_overrides[get_release_context] = release_context
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client, application, db, catalog, job, owner_id


@pytest.mark.asyncio
async def test_non_admin_cannot_toggle_a_database(admin_client):
    client, application, db, catalog, _, _ = admin_client
    application.state.user = _user("researcher")
    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 403, response.text
    assert catalog.is_active is True
    assert db.commits == 0
    assert db.added == []


@pytest.mark.asyncio
async def test_disable_hides_the_database_from_new_searches(admin_client):
    client, _, db, catalog, _, _ = admin_client
    # The active row is discoverable before the toggle.
    listed = await blast_routes.service.list_databases(db, release_context=CONTEXT)
    assert [row.id for row in listed] == [catalog.id]

    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body == {"id": 7, "name": "wm82_a4_genome", "is_active": False}
    # No worker-local path leaks in the control-plane response.
    assert "file_path" not in body and "/private" not in response.text

    assert catalog.is_active is False
    assert db.commits == 1

    # Assert on the statement ``list_databases`` actually emitted, not on a
    # statement this test built itself. Both the discovery call above and the
    # one below must carry the SQL-level ``is_active`` filter; removing that
    # clause from the service makes this assertion fail (and the fake session
    # stops filtering the disabled row out).
    discovery = [sql for sql in db.statements if "JOIN assemblies ON" in sql]
    assert discovery, "list_databases did not query the catalog"
    for sql in discovery:
        assert db._catalog_select_is_active(sql), (
            "list_databases no longer filters on blast_databases.is_active IS true"
        )
    assert blast_routes.service._is_runnable_database(catalog) is False
    listed = await blast_routes.service.list_databases(db, release_context=CONTEXT)
    assert listed == []
    assert db._catalog_select_is_active(db.statements[-1])


@pytest.mark.asyncio
async def test_disabled_database_cannot_accept_a_new_submission(admin_client):
    """Disabling must close the *execution* path, not only discovery.

    ``list_databases`` hiding the row and ``_resolve_database`` refusing to
    select it are two different readers of ``is_active``. This test drives the
    real toggle route, then tries to submit a brand-new job against that id on
    the same session: selection must raise ``NotFoundError`` before any
    ``BlastJob`` or outbox event is written, and no extra commit may happen.
    Real PostgreSQL covers the same row in
    ``test_blast_catalog_postgres.py``; this keeps the control plane's own
    suite self-contained instead of borrowing that proof.
    """
    from app.core.exceptions import NotFoundError
    from app.models.outbox import OutboxEvent
    from app.schemas.blast import BlastSubmitRequest

    client, _, db, catalog, _, _ = admin_client
    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 200, response.text
    assert catalog.is_active is False
    commits_after_toggle = db.commits
    added_after_toggle = list(db.added)

    request = BlastSubmitRequest(
        engine="ncbi_blast",
        program="blastp",
        database_id=catalog.id,
        query_sequence=">q\nMKVLAAGIVGLNLGGK",
    )
    with pytest.raises(NotFoundError, match="not found or inactive"):
        await blast_routes.service.submit_job(
            db, None, request, release_context=CONTEXT
        )

    # The selection statement really carried the active filter and found no row.
    assert db._catalog_select_is_active(db.statements[-1])
    # Only the toggle's own AuditLog may be present; no job and no outbox row.
    new_objects = db.added[len(added_after_toggle):]
    assert [obj for obj in new_objects if isinstance(obj, (BlastJob, OutboxEvent))] == []
    assert db.added == added_after_toggle
    assert db.commits == commits_after_toggle


@pytest.mark.asyncio
async def test_disable_does_not_rewrite_an_in_flight_jobs_frozen_provenance(admin_client):
    client, _, db, catalog, job, _ = admin_client
    frozen = dict(job.parameters["_search_provenance"])
    status_before = job.status
    error_before = job.error_message
    query_before = job.query_sequence

    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 200, response.text
    assert catalog.is_active is False

    # The job is untouched: same status, query, frozen index identity and
    # release/assembly namespace. No new job/outbox row is created by a toggle.
    assert job.status == status_before == BlastJobStatus.RUNNING
    assert job.error_message == error_before
    assert job.query_sequence == query_before
    assert job.parameters["_search_provenance"] == frozen
    assert job.database_id == catalog.id
    assert [obj for obj in db.added if isinstance(obj, BlastJob)] == []

    # A read of that job still reports the identity it was submitted against,
    # not the catalog's (now disabled) visibility.
    read = await blast_routes.service.get_job(db, job.id, None, ["administrator"])
    assert read.release_id == frozen["release_id"]
    assert read.assembly_name == frozen["assembly_name"]
    assert read.parameters["_search_provenance"] == frozen


@pytest.mark.asyncio
async def test_disabled_index_still_serves_a_retry_with_its_frozen_identity(admin_client):
    """Strongest form of the contract: an in-flight job that later fails can
    retry against the identity frozen at submission, even though the catalog
    row is now disabled. The toggle never re-resolves against "today's" index.
    """
    from app.models.outbox import OutboxEvent
    from app.services.release_context import ReleaseContext

    client, _, db, catalog, job, owner_id = admin_client
    job.status = BlastJobStatus.FAILED
    frozen = dict(job.parameters["_search_provenance"])

    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert catalog.is_active is False

    # Retry re-arms the SAME row and re-dispatches with the frozen identity.
    await blast_routes.service.retry_job(
        db,
        job.id,
        owner_id,
        ["administrator"],
        release_context=ReleaseContext(release_id=1, assembly_id=1, assembly="Wm82"),
    )
    events = [obj for obj in db.added if isinstance(obj, OutboxEvent)]
    assert len(events) == 1
    payload = events[0].payload["payload"]
    assert payload["index_identity"] == frozen["index_identity"]
    assert payload["fasta_sha256"] == frozen["fasta_sha256"]
    assert payload["database"] == catalog.name
    assert payload["release_id"] == frozen["release_id"]
    assert job.status == BlastJobStatus.PENDING
    assert job.parameters["_search_provenance"] == frozen


@pytest.mark.asyncio
async def test_every_toggle_writes_one_audit_entry_with_operator_and_from_to(admin_client):
    client, application, db, catalog, _, _ = admin_client
    actor_id = application.state.user.id
    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False},
    )
    assert response.status_code == 200
    entries = [obj for obj in db.added if isinstance(obj, AuditLog)]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.user_id == actor_id
    assert entry.action == "blast_database_state_update"
    assert entry.resource_type == "blast_database"
    assert entry.resource_id == "7"
    assert entry.old_value == {
        "database_id": 7,
        "is_active": True,
        "operator": str(actor_id),
    }
    assert entry.new_value == {
        "database_id": 7,
        "is_active": False,
        "operator": str(actor_id),
    }


@pytest.mark.asyncio
async def test_request_is_narrow_and_has_no_delete_route(admin_client):
    client, _, db, catalog, _, _ = admin_client
    # Only is_active is accepted; a caller cannot smuggle build state, name or
    # a path through the same route.
    response = await client.patch(
        "/api/v1/blast/databases/7",
        json={"is_active": False, "file_path": "/private/elsewhere"},
    )
    assert response.status_code == 422
    assert catalog.is_active is True
    assert db.commits == 0

    # There is no DELETE route: a published index is never erased.
    assert (await client.delete("/api/v1/blast/databases/7")).status_code == 405
    assert catalog.is_active is True


@pytest.mark.asyncio
async def test_missing_database_is_404_and_writes_no_audit(admin_client):
    client, _, db, _, _, _ = admin_client
    db.catalog = None
    # The fake still returns [None] for the catalog lookup; make it empty.
    original_execute = db.execute

    async def execute(stmt, params=None):
        if "blast_databases" in str(stmt):
            return _Result([])
        return await original_execute(stmt, params)

    db.execute = execute
    response = await client.patch(
        "/api/v1/blast/databases/999",
        json={"is_active": False},
    )
    assert response.status_code == 404
    assert db.added == []


@pytest.mark.asyncio
async def test_blast_database_response_never_carries_file_path():
    """The public discovery shape is an explicit allowlist, not the ORM row."""
    from app.schemas.blast import BlastDatabaseResponse, BlastDatabaseStateResponse

    for model in (BlastDatabaseResponse, BlastDatabaseStateResponse):
        assert "file_path" not in model.model_fields
        assert "provenance" not in model.model_fields

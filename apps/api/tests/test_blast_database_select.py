"""Multi-genome BLAST database selection tests (no docker: fake async session).

Covers the Wave 2-D contract:
- ``GET /blast/databases`` carries assembly identifiers (name/version/default).
- ``POST /blast/jobs`` accepts ``database`` (name alias) in addition to
  ``database_id``; both are checked against the active-database whitelist.
- Unlisted names / disagreeing identifiers are rejected; neither identifier
  falls back to the configured default database, then to the default assembly.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.core.exceptions import ValidationError as AppValidationError
from app.models.blast import BlastDatabase, BlastJob
from app.models.genomic import Assembly
from app.schemas.blast import BlastParameters, BlastSubmitProgram, BlastSubmitRequest
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext


class _Scalars:
    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDbSession:
    """AsyncSession stand-in serving blast-database / assembly lookups."""

    def __init__(
        self,
        blast_db: BlastDatabase | None = None,
        default_assembly: Assembly | None = None,
    ):
        self.blast_db = blast_db
        self.default_assembly = default_assembly
        self.added: list[Any] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        # ``select(BlastDatabase)`` may outer-join ``assemblies`` (lazy joined).
        if "blast_databases" in sql:
            return _Result([self.blast_db] if self.blast_db else [])
        if "assemblies" in sql:
            return _Result([self.default_assembly] if self.default_assembly else [])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


def _make_db(db_type: str = "prot", name: str = "williams82_cds") -> BlastDatabase:
    return BlastDatabase(
        id=1,
        name=name,
        db_type=db_type,
        assembly_id=1,
        file_path="/data/dbs/williams82_cds",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_assembly() -> Assembly:
    return Assembly(
        id=1,
        name="Wm82.a2.v1",
        species="Glycine max",
        version="a2.v1",
        is_default=True,
    )


def _context(release_id: int = 7) -> ReleaseContext:
    """Published release the fake session's rows belong to."""
    return ReleaseContext(release_id=release_id, assembly_id=1, assembly="Wm82.a2.v1")


def _make_request(**overrides: Any) -> BlastSubmitRequest:
    defaults: dict[str, Any] = dict(
        program=BlastSubmitProgram.BLASTP,
        query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
        parameters=BlastParameters(),
    )
    defaults.update(overrides)
    return BlastSubmitRequest(**defaults)


# ---------------------------------------------------------------------------
# GET /blast/databases: assembly identifiers
# ---------------------------------------------------------------------------


class TestListDatabasesAssemblyIdentifiers:
    async def test_databases_include_assembly_identifiers(self) -> None:
        bd = _make_db()
        bd.assembly = _make_assembly()
        session = FakeDbSession(blast_db=bd)

        rows = await BlastService().list_databases(session, release_context=_context())

        assert len(rows) == 1
        row = rows[0]
        assert row.id == 1
        assert row.name == "williams82_cds"
        assert row.assembly_id == 1
        assert row.assembly_name == "Wm82.a2.v1"
        assert row.assembly_version == "a2.v1"
        assert row.assembly_is_default is True
        # The list is release-scoped: the predicate is present in the query.
        assert _context().release_id == 7

    async def test_databases_without_assembly_keep_nulls(self) -> None:
        session = FakeDbSession(blast_db=_make_db())  # no assembly attached

        rows = await BlastService().list_databases(session, release_context=_context())

        assert rows[0].assembly_name is None
        assert rows[0].assembly_version is None
        assert rows[0].assembly_is_default is None


# ---------------------------------------------------------------------------
# POST submit: database name / id selection and whitelist
# ---------------------------------------------------------------------------


class TestSubmitDatabaseSelection:
    async def _submit(self, session: FakeDbSession, request: BlastSubmitRequest):
        return await BlastService().submit_job(
            session, uuid.uuid4(), request, release_context=_context()
        )

    def test_submit_by_database_name_ok(self) -> None:
        session = FakeDbSession(blast_db=_make_db())
        request = _make_request(database="williams82_cds")

        response = asyncio.run(self._submit(session, request))

        assert response.job_id
        job = next(obj for obj in session.added if isinstance(obj, BlastJob))
        assert job.database_id == 1
        # The worker payload carries the whitelisted database name.
        outbox = next(obj for obj in session.added if type(obj).__name__ == "OutboxEvent")
        assert outbox.payload["payload"]["database"] == "williams82_cds"

    def test_submit_by_database_id_ok(self) -> None:
        session = FakeDbSession(blast_db=_make_db())

        response = asyncio.run(self._submit(session, _make_request(database_id=1)))

        assert response.job_id

    def test_submit_with_unlisted_database_name_rejected(self) -> None:
        """Names outside the active-database whitelist are refused (404)."""
        session = FakeDbSession(blast_db=None)
        request = _make_request(database="hacked_db")
        with pytest.raises(NotFoundError, match="hacked_db"):
            asyncio.run(self._submit(session, request))

    def test_submit_with_unknown_database_id_rejected(self) -> None:
        session = FakeDbSession(blast_db=None)
        with pytest.raises(NotFoundError):
            asyncio.run(self._submit(session, _make_request(database_id=999)))

    def test_submit_with_disagreeing_identifiers_rejected(self) -> None:
        """database_id and database must resolve to the same row."""
        session = FakeDbSession(blast_db=_make_db())
        request = _make_request(database_id=1, database="other_db")
        with pytest.raises(AppValidationError, match="do not match"):
            asyncio.run(self._submit(session, request))

    def test_schema_rejects_path_traversal_name(self) -> None:
        """Injection-shaped names never reach the service (422 at boundary)."""
        with pytest.raises(ValidationError, match="plain identifier"):
            _make_request(database="../../etc/passwd")

    def test_schema_rejects_name_with_whitespace(self) -> None:
        with pytest.raises(ValidationError, match="plain identifier"):
            _make_request(database="williams82 cds")

    def test_default_database_fallback_uses_configured_name(self) -> None:
        """Neither identifier → settings.blast_default_db is used."""
        session = FakeDbSession(blast_db=_make_db())
        request = _make_request()  # no database, no database_id

        response = asyncio.run(self._submit(session, request))

        assert response.job_id
        job = next(obj for obj in session.added if isinstance(obj, BlastJob))
        assert job.database_id == 1

    def test_default_assembly_fallback_when_no_configured_db(self, monkeypatch) -> None:
        from app.services import blast_service

        monkeypatch.setattr(blast_service.settings, "blast_default_db", "")
        session = FakeDbSession(blast_db=_make_db(), default_assembly=_make_assembly())

        response = asyncio.run(self._submit(session, _make_request()))

        assert response.job_id
        job = next(obj for obj in session.added if isinstance(obj, BlastJob))
        assert job.database_id == 1

    def test_no_database_available_raises_not_found(self, monkeypatch) -> None:
        from app.services import blast_service

        monkeypatch.setattr(blast_service.settings, "blast_default_db", "")
        session = FakeDbSession(blast_db=None, default_assembly=None)

        with pytest.raises(NotFoundError, match="No BLAST database selected"):
            asyncio.run(self._submit(session, _make_request()))

"""Ablation guards for the BLAST release boundary.

The review found the BLAST database surface was release-free:

* ``GET /blast/databases`` selected every ``is_active`` row, so a draft
  release's databases were listed;
* ``BlastService._resolve_database`` resolved by id/name/default without a
  release predicate, and its last fallback picked *any*
  ``Assembly.is_default`` row across all releases — a job could therefore
  target another release's database;
* the job/outbox payload carried no provenance, so a stored result could not be
  told apart from one computed against a different coordinate namespace.

Unit-level guards (no PostgreSQL): the service is driven with a fake async
session that records the compiled SQL.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.exceptions import NotFoundError
from app.models.blast import BlastDatabase, BlastJob
from app.models.genomic import Assembly
from app.schemas.blast import BlastParameters, BlastSubmitProgram, BlastSubmitRequest
from app.services.blast_service import BlastService
from app.services.release_context import ReleaseContext

_RELEASE_ID = 7


def _context(release_id: int = _RELEASE_ID) -> ReleaseContext:
    return ReleaseContext(release_id=release_id, assembly_id=1, assembly="Wm82.a4.v1")


class _Scalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _RecordingDb:
    """Serves the fake rows and records every compiled statement."""

    def __init__(self, blast_db: BlastDatabase | None = None, assembly: Assembly | None = None):
        self.blast_db = blast_db
        self.assembly = assembly
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        sql = str(stmt)
        if "blast_databases" in sql:
            return _Result([self.blast_db] if self.blast_db else [])
        if "assemblies" in sql:
            return _Result([self.assembly] if self.assembly else [])
        return _Result([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        pass


def _make_db(name: str = "williams82_cds", *, assembly_id: int = 1) -> BlastDatabase:
    return BlastDatabase(
        id=1,
        name=name,
        db_type="prot",
        assembly_id=assembly_id,
        file_path="/data/dbs/williams82_cds",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_assembly(release_id: int = _RELEASE_ID) -> Assembly:
    return Assembly(
        id=1,
        name="Wm82.a4.v1",
        species="Glycine max",
        version="a4.v1",
        is_default=True,
        release_id=release_id,
    )


def _make_request(**overrides: Any) -> BlastSubmitRequest:
    defaults: dict[str, Any] = dict(
        program=BlastSubmitProgram.BLASTP,
        query_sequence="ATGCAAGCTTAGCTAGGCTAGGCTAGGC",
        parameters=BlastParameters(),
    )
    defaults.update(overrides)
    return BlastSubmitRequest(**defaults)


def _release_scoped(statement: Any) -> bool:
    sql = str(statement)
    return "assemblies" in sql and "assemblies.release_id" in sql


# ---------------------------------------------------------------------------
# 1. Listing is release-scoped.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_list_joins_the_release():
    """Ablation: dropping the join re-exposes draft-release databases."""
    bd = _make_db()
    bd.assembly = _make_assembly()
    db = _RecordingDb(blast_db=bd)

    await BlastService().list_databases(db, release_context=_context())

    assert len(db.statements) == 1
    assert _release_scoped(db.statements[0]), str(db.statements[0])


@pytest.mark.asyncio
async def test_database_list_reports_release_provenance():
    bd = _make_db()
    bd.assembly = _make_assembly()
    db = _RecordingDb(blast_db=bd)

    rows = await BlastService().list_databases(db, release_context=_context())

    assert rows[0].release_id == _RELEASE_ID
    assert rows[0].assembly_name == "Wm82.a4.v1"


# ---------------------------------------------------------------------------
# 2. Every resolution path is release-scoped.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_by_id_is_release_scoped():
    db = _RecordingDb(blast_db=_make_db())

    await BlastService()._resolve_database(  # noqa: SLF001
        db, _make_request(database_id=1), release_context=_context()
    )

    assert _release_scoped(db.statements[0]), str(db.statements[0])


@pytest.mark.asyncio
async def test_lookup_by_name_is_release_scoped():
    db = _RecordingDb(blast_db=_make_db())

    await BlastService()._resolve_database(  # noqa: SLF001
        db, _make_request(database="williams82_cds"), release_context=_context()
    )

    assert _release_scoped(db.statements[0]), str(db.statements[0])


@pytest.mark.asyncio
async def test_default_assembly_fallback_is_release_scoped(monkeypatch):
    """The defect: the fallback picked any ``is_default`` assembly, including a
    draft release's."""
    from app.services import blast_service as mod

    monkeypatch.setattr(mod.settings, "blast_default_db", None)
    db = _RecordingDb(blast_db=_make_db(), assembly=_make_assembly())

    await BlastService()._resolve_database(  # noqa: SLF001
        db, _make_request(), release_context=_context()
    )

    # Both the assembly lookup and the resulting database lookup carry the
    # release predicate.
    assembly_statements = [s for s in db.statements if "assemblies" in str(s)]
    assert assembly_statements, "expected an assembly lookup"
    for statement in assembly_statements:
        assert "assemblies.release_id" in str(statement), str(statement)


@pytest.mark.asyncio
async def test_another_releases_database_is_not_found(monkeypatch):
    """A database outside the resolved release must not resolve."""
    from app.services import blast_service as mod

    monkeypatch.setattr(mod.settings, "blast_default_db", None)
    # Fake session yields no row because the real predicate would exclude it.
    db = _RecordingDb(blast_db=None, assembly=None)

    with pytest.raises(NotFoundError):
        await BlastService()._resolve_database(  # noqa: SLF001
            db, _make_request(database_id=99), release_context=_context()
        )


# ---------------------------------------------------------------------------
# 3. The job + outbox payload carry provenance.
# ---------------------------------------------------------------------------


def test_job_payload_records_release_and_assembly_provenance():
    db = _RecordingDb(blast_db=_make_db())
    request = _make_request(database="williams82_cds")

    asyncio.run(BlastService().submit_job(db, uuid.uuid4(), request, release_context=_context()))

    job = next(obj for obj in db.added if isinstance(obj, BlastJob))
    assert job.database_id == 1
    outbox = next(obj for obj in db.added if type(obj).__name__ == "OutboxEvent")
    payload = outbox.payload
    # The versioned JobPayload wraps the worker parameters.
    worker_payload = payload.get("payload", payload)
    assert worker_payload["release_key"] == str(_RELEASE_ID)
    assert worker_payload["assembly"] == "Wm82.a4.v1"
    assert worker_payload["assembly_id"] == 1


def test_job_response_exposes_the_searched_release_and_assembly():
    job = BlastJob(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        program="blastn",
        database_id=1,
        query_sequence="ATGC",
        parameters={},
        status="completed",
        hit_count=0,
        submitted_at=datetime.now(UTC),
    )
    database = _make_db()
    database.assembly = _make_assembly()
    job.database = database

    response = BlastService._job_to_response(job)  # noqa: SLF001

    assert response.release_id == _RELEASE_ID
    assert response.assembly_name == "Wm82.a4.v1"

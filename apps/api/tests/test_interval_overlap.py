"""Interval overlap + format inspection + engine-toggle tests.

No PostgreSQL: a faithful in-memory AsyncSession stand-in returns published
gene rows.  This tests the visibility/coordinate contract, not SQL itself.
"""

from __future__ import annotations

import base64
import importlib.util
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ExceptionHandler

from app.api.v1.tools_sequence import router as sequence_router
from app.core.exceptions import (
    ServiceUnavailableError,
    SoyMutDBError,
    soy_mut_db_exception_handler,
)
from app.schemas import sequence_tools as s
from app.services import interval_overlap_service
from app.services.release_context import ReleaseContext

WHEEL_AVAILABLE = importlib.util.find_spec("soymutdb_bio_core") is not None
requires_wheel = pytest.mark.skipif(
    not WHEEL_AVAILABLE, reason="compiled bio-core wheel not installed"
)


class _Gene:
    def __init__(self, start: int, end: int, accession: str) -> None:
        self.start = start
        self.end = end
        self.accession = accession
        self.gene_pk = 999  # private key, must never leak


class _Result:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeDb:
    """Returns one assembly, one chromosome, then three overlapping genes."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            class _A:
                id = 7
                name = "GmWm82.a2.v1"
                version = "a2.v1"
                release_id = 11
            return _Result(_A())
        if self.calls == 2:
            class _C:
                id = 3
                name = "chr1"
            return _Result(_C())
        return _Result([
            _Gene(10, 20, "Glyma.01G000100"),
            _Gene(10, 20, "Glyma.01G000200"),  # duplicate interval
            _Gene(19, 30, "Glyma.01G000300"),
        ])


@pytest.mark.asyncio
@requires_wheel
async def test_overlap_count_vs_union_coverage() -> None:
    payload = s.OverlapRequest(
        assembly="GmWm82.a2.v1",
        reference_name="chr1",
        regions=[s.IntervalRegion(start=10, end=30)],
    )
    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    result = await interval_overlap_service.overlap(cast(AsyncSession, _FakeDb()), payload, ctx)
    assert result.assembly == "GmWm82.a2.v1"
    assert result.release == "11"
    q = result.queries[0]
    assert q.overlap_count == 3, "duplicate records count separately"
    # 1-based inclusive genes [10,20], [19,30] -> half-open [9,20), [18,30);
    # query [10,30] -> [9,30). Union of overlaps = [9,30) = 21 bp.
    assert q.covered_bp == 21, "coverage is the union, not a record count"
    assert q.hits is not None, "hits mode must return the hit list"
    assert {h.public_id for h in q.hits} == {
        "Glyma.01G000100", "Glyma.01G000200", "Glyma.01G000300"
    }
    assert all(h.start in (10, 19) for h in q.hits)
    # Pin both endpoints: contract for the conversion from the kernel's
    # 0-based half-open (start0, end0) to 1-based inclusive (start, end).
    assert {(h.start, h.end) for h in q.hits} == {(10, 20), (19, 30)}


@pytest.mark.asyncio
@requires_wheel
async def test_private_gene_pk_never_leaks() -> None:
    payload = s.OverlapRequest(
        assembly="GmWm82.a2.v1",
        reference_name="chr1",
        regions=[s.IntervalRegion(start=10, end=20)],
    )
    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    result = await interval_overlap_service.overlap(cast(AsyncSession, _FakeDb()), payload, ctx)
    body = result.model_dump_json()
    assert "gene_pk" not in body
    assert "999" not in body


class _Empty:
    """A DB stand-in whose first N lookups return rows, then None (404)."""

    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.calls = 0

    async def execute(self, stmt):
        value = self.rows[self.calls] if self.calls < len(self.rows) else None
        self.calls += 1
        return _Result(value)


class _Assembly:
    id = 7
    name = "GmWm82.a2.v1"
    version = "a2.v1"
    release_id = 11


@pytest.mark.asyncio
async def test_unpublished_assembly_fails_closed() -> None:
    """No kernel needed to decide an assembly is not published (404)."""
    payload = s.OverlapRequest(
        assembly="not-published",
        reference_name="chr1",
        regions=[s.IntervalRegion(start=1, end=10)],
    )
    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    with pytest.raises(SoyMutDBError) as exc:
        await interval_overlap_service.overlap(cast(AsyncSession, _Empty([])), payload, ctx)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unpublished_assembly_404_wins_over_missing_engine(
    monkeypatch,
) -> None:
    """A 404 is a release-boundary fact, not an engine-availability symptom.

    Regression: ``overlap()`` used to call ``bridge.require()`` as its first
    statement. With the wheel absent that raised 503 before any DB lookup, so
    an unpublished assembly was indistinguishable from a broken kernel. The
    old test asserted 404 but could only reach it by stubbing ``require()``.
    """
    import app.services.bio_core_bridge as bridge

    def _unavailable():
        raise ServiceUnavailableError("engine down")

    monkeypatch.setattr(bridge, "require", _unavailable)
    payload = s.OverlapRequest(
        assembly="not-published",
        reference_name="chr1",
        regions=[s.IntervalRegion(start=1, end=10)],
    )
    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    db = _Empty([])
    with pytest.raises(SoyMutDBError) as exc:
        await interval_overlap_service.overlap(cast(AsyncSession, db), payload, ctx)
    assert exc.value.status_code == 404
    assert db.calls == 1, "the assembly lookup must precede any engine check"


@pytest.mark.asyncio
async def test_unknown_chromosome_404_wins_over_missing_engine(monkeypatch) -> None:
    """The chromosome check is also a visibility decision, made before 503."""
    import app.services.bio_core_bridge as bridge

    def _unavailable():
        raise ServiceUnavailableError("engine down")

    monkeypatch.setattr(bridge, "require", _unavailable)
    payload = s.OverlapRequest(
        assembly="GmWm82.a2.v1",
        reference_name="not-a-chromosome",
        regions=[s.IntervalRegion(start=1, end=10)],
    )
    ctx = ReleaseContext(release_id=11, assembly_id=7, assembly="GmWm82.a2.v1")
    db = _Empty([_Assembly()])
    with pytest.raises(SoyMutDBError) as exc:
        await interval_overlap_service.overlap(cast(AsyncSession, db), payload, ctx)
    assert exc.value.status_code == 404
    assert db.calls == 2, "both visibility lookups must precede any engine check"


def _app() -> FastAPI:
    application = FastAPI()
    application.include_router(sequence_router, prefix="/api/v1")
    application.add_exception_handler(
        SoyMutDBError, cast(ExceptionHandler, soy_mut_db_exception_handler)
    )
    return application


@requires_wheel
@pytest.mark.asyncio
async def test_inspect_fasta_via_http() -> None:
    data = base64.b64encode(b">g1\nACGT\n>g2\nAAAA\n").decode()
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools/sequence/inspect", json={"fmt": "fasta", "data": data}
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["record_count"] == 2
    assert body["records"][0]["name"] == "g1"


@requires_wheel
@pytest.mark.asyncio
async def test_inspect_rejects_malformed_fastq() -> None:
    data = base64.b64encode(b"@r\nACGT\n+\n!!!\n").decode()
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools/sequence/inspect", json={"fmt": "fastq", "data": data}
        )
    assert r.status_code == 422
    assert r.json()["error"]["details"]["code"] == "INVALID_RECORD"


@pytest.mark.asyncio
async def test_python_engine_is_a_real_engine(monkeypatch) -> None:
    """SOYMUTDB_BIO_ENGINE=python selects the Biopython engine, which computes.

    The engine used to be a documented dead end: the Rust kernel was the only
    implementation, so `python` had to fail closed rather than answer with
    made-up numbers. It is now a real implementation, so the contract is the
    opposite: the engine is available and returns results.
    """
    import app.services.bio_core_bridge as bridge

    monkeypatch.setattr(bridge, "_engine_setting", lambda: "python")
    monkeypatch.setattr(bridge, "_module", bridge._UNSET)
    st = bridge.status()
    assert st.available is True
    assert st.engine == "biopython"

    core = bridge.require()
    assert core.reverse_complement("ATGC", "dna", False) == "GCAT"


async def test_an_unavailable_engine_still_fails_closed(monkeypatch) -> None:
    """No engine at all must be a 503, never a silent empty success."""
    import app.services.bio_core_bridge as bridge

    monkeypatch.setattr(bridge, "_engine_setting", lambda: "python")
    monkeypatch.setattr(bridge, "_module", None)

    st = bridge.status()
    assert st.available is False

    with pytest.raises(SoyMutDBError) as exc:
        bridge.require()
    assert exc.value.status_code == 503

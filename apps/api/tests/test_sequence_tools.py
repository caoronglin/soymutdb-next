"""Sequence Tools endpoint tests (HTTP-level, no database required).

Mounts only the new router on a minimal FastAPI app with the same exception
handlers as production.  The compiled Rust wheel is a hard dependency: when
it is absent the compute endpoints must return a structured 503 and never a
fake success.  Tests that need real kernel results are skipped (with a reason)
when the wheel is unavailable, so a missing wheel can never pass as green.
"""

from __future__ import annotations

import importlib.util

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.tools_sequence import router
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
)

WHEEL_AVAILABLE = importlib.util.find_spec("soymutdb_bio_core") is not None

requires_wheel = pytest.mark.skipif(
    not WHEEL_AVAILABLE, reason="compiled bio-core wheel not installed"
)


def _app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    return application


@pytest.fixture
async def client():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_capabilities_always_available(client: AsyncClient) -> None:
    r = await client.get("/api/v1/tools/sequence/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert "available" in body
    assert body["coordinate_system_public"] == "1-based-inclusive"
    assert body["genetic_codes"] == [1]
    assert "match" in body["programs"]


@pytest.mark.asyncio
async def test_request_validation_is_bounded(client: AsyncClient) -> None:
    # Empty sequence, too-long pattern, invalid k, bad coordinate policy.
    r = await client.post(
        "/api/v1/tools/sequence/reverse-complement", json={"sequence": ""}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/tools/sequence/match",
        json={"pattern": "A" * 257, "target": {"kind": "inline", "sequence": "ACGT"}},
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/tools/sequence/kmers", json={"sequence": "ACGT", "k": 99}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/tools/sequence/translate",
        json={"sequence": "ATG", "genetic_code_id": 0},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_arbitrary_paths_or_urls_accepted(client: AsyncClient) -> None:
    # A discriminated union must reject an unrecognised target kind.
    r = await client.post(
        "/api/v1/tools/sequence/match",
        json={
            "pattern": "ACGT",
            "target": {"kind": "region", "assembly": "x", "region": "chr1:1-2"},
        },
    )
    assert r.status_code == 422


@requires_wheel
@pytest.mark.asyncio
async def test_reverse_complement_iupac(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/reverse-complement", json={"sequence": "ATGCRY"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sequence"] == "RYGCAT"
    assert body["length"] == 6
    assert body["engine"]["engine"] == "soymutdb-bio-core"


@requires_wheel
@pytest.mark.asyncio
async def test_stats_denominator_is_explicit(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tools/sequence/stats", json={"sequence": "ACGTNN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["denominator"] == 4
    assert body["gc_fraction"] == 0.5
    assert body["ambiguous_count"] == 2


@requires_wheel
@pytest.mark.asyncio
async def test_kmer_spec_golden(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/kmers", json={"sequence": "ACGTACGTNACG", "k": 4}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total_windows"], body["valid_windows"], body["skipped_windows"]) == (9, 5, 4)
    assert body["distinct_kmers"] == 3


@requires_wheel
@pytest.mark.asyncio
async def test_alignment_is_not_blast(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/align", json={"query": "ACGT", "target": "ACGT"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cigar"] == "4M"
    assert body["identity"] == 1.0


@requires_wheel
@pytest.mark.asyncio
async def test_unimplemented_genetic_code_is_a_structured_error(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/translate",
        json={"sequence": "ATG", "genetic_code_id": 11},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["code"] == "UNKNOWN_GENETIC_CODE"


@requires_wheel
@pytest.mark.asyncio
async def test_match_overlapping_hits(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/match",
        json={
            "pattern": "AA",
            "target": {"kind": "inline", "sequence": "AAAA"},
            "both_strands": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert [h["start"] for h in body["matches"]] == [1, 2, 3]
    assert body["coordinate_system"] == "1-based-inclusive"


@pytest.mark.asyncio
async def test_missing_wheel_fails_closed(monkeypatch) -> None:
    """A missing wheel must be a 503, never a silent empty success."""
    import app.services.bio_core_bridge as bridge

    monkeypatch.setattr(bridge, "_module", None)
    r = await AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://test"
    ).post("/api/v1/tools/sequence/reverse-complement", json={"sequence": "ACGT"})
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "service_unavailable"
    assert "not installed" in r.json()["error"]["details"]["reason"]

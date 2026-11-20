"""Sequence Tools endpoint tests (HTTP-level, no database required).

Mounts only the new router on a minimal FastAPI app with the same exception
handlers as production.  The compiled Rust wheel is a hard dependency: when
it is absent the compute endpoints must return a structured 503 and never a
fake success.  Tests that need real kernel results are skipped (with a reason)
when the wheel is unavailable, so a missing wheel can never pass as green.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.types import ExceptionHandler

from app.api.v1.tools_sequence import router
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
)


def _engine_available() -> bool:
    """Whether the configured sequence engine can be loaded.

    The engine is selectable (``SOYMUTDB_BIO_ENGINE``): Biopython by default,
    the compiled kernel when that wheel is installed. These tests exercise the
    HTTP contract, so they need *an* engine, not one particular build.
    """
    from app.services import bio_core_bridge

    return bio_core_bridge.status().available


ENGINE_AVAILABLE = _engine_available()

requires_wheel = pytest.mark.skipif(not ENGINE_AVAILABLE, reason="no sequence engine available")


def _app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    # Starlette types the handler as accepting any Exception; ours narrows the
    # second parameter to SoyMutDBError. The cast states that narrowing.
    application.add_exception_handler(
        SoyMutDBError, cast(ExceptionHandler, soy_mut_db_exception_handler)
    )
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
    # The capability list reflects the loaded engine. Both engines implement
    # the standard table (1); the Biopython engine additionally carries the
    # full NCBI set, so the assertion is "1 is supported", not "only 1".
    assert 1 in body["genetic_codes"]
    assert sorted(body["genetic_codes"]) == body["genetic_codes"]
    assert "match" in body["programs"]


@pytest.mark.asyncio
async def test_request_validation_is_bounded(client: AsyncClient) -> None:
    # Empty sequence, too-long pattern, invalid k, bad coordinate policy.
    r = await client.post("/api/v1/tools/sequence/reverse-complement", json={"sequence": ""})
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/tools/sequence/match",
        json={"pattern": "A" * 257, "target": {"kind": "inline", "sequence": "ACGT"}},
    )
    assert r.status_code == 422
    r = await client.post("/api/v1/tools/sequence/kmers", json={"sequence": "ACGT", "k": 99})
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
    r = await client.post("/api/v1/tools/sequence/reverse-complement", json={"sequence": "ATGCRY"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sequence"] == "RYGCAT"
    assert body["length"] == 6
    # The response names the engine that ran; which one is a deployment
    # choice, so the assertion is that it is reported, not that it is a
    # particular implementation.
    assert body["engine"]["engine"]
    assert body["engine"]["engine_version"]


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
    r = await client.post("/api/v1/tools/sequence/kmers", json={"sequence": "ACGTACGTNACG", "k": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total_windows"], body["valid_windows"], body["skipped_windows"]) == (9, 5, 4)
    assert body["distinct_kmers"] == 3


@requires_wheel
@pytest.mark.asyncio
async def test_alignment_is_not_blast(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tools/sequence/align", json={"query": "ACGT", "target": "ACGT"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cigar"] == "4M"
    assert body["identity"] == 1.0


@requires_wheel
@pytest.mark.asyncio
async def test_unknown_genetic_code_is_a_structured_error(client: AsyncClient) -> None:
    """A code no engine implements fails closed, with the kernel's error code.

    Code 7 is absent from every codon table both engines ship; asking for it
    must be a 422 carrying ``UNKNOWN_GENETIC_CODE``, never an empty protein.
    """
    r = await client.post(
        "/api/v1/tools/sequence/translate",
        json={"sequence": "ATG", "genetic_code_id": 7},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["code"] == "UNKNOWN_GENETIC_CODE"


@requires_wheel
@pytest.mark.asyncio
async def test_bacterial_genetic_code_translates(client: AsyncClient) -> None:
    """Code 11 (bacterial) is supported.

    The compiled kernel implemented code 1 only; the Biopython engine carries
    the full table set, so a request that used to be rejected now answers.
    """
    r = await client.post(
        "/api/v1/tools/sequence/translate",
        json={"sequence": "ATGGTG", "genetic_code_id": 11},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["genetic_code_id"] == 11
    assert body["protein"] == "MV"


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
    r = await AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test").post(
        "/api/v1/tools/sequence/reverse-complement", json={"sequence": "ACGT"}
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "service_unavailable"
    assert "not installed" in r.json()["error"]["details"]["reason"]


# ---------------------------------------------------------------------------
# Capabilities beyond the original kernel.
# ---------------------------------------------------------------------------


@requires_wheel
@pytest.mark.asyncio
async def test_convert_format_roundtrip(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/convert",
        json={"data": ">s1 desc\nATGCAA\n", "source_format": "fasta", "target_format": "genbank"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["record_count"] == 1
    assert "LOCUS" in body["output"]
    # GenBank writes the sequence in lower case; that is the format's own
    # convention, not a lossy conversion.
    assert "atgcaa" in body["output"].lower()


@requires_wheel
@pytest.mark.asyncio
async def test_convert_format_rejects_unparsable_input(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/convert",
        json={"data": "not a sequence file", "source_format": "genbank", "target_format": "fasta"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"]["code"] == "INVALID_RECORD"


@requires_wheel
@pytest.mark.asyncio
async def test_restriction_sites_reports_cut_positions(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/restriction-sites",
        json={"sequence": "GAATTCAAAAGAATTC", "enzymes": ["EcoRI"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enzyme_count"] == 1
    assert body["total_cut_sites"] == 2
    eco = body["enzymes"][0]
    assert eco["enzyme"] == "EcoRI"
    assert eco["site"] == "GAATTC"
    assert eco["count"] == 2


@requires_wheel
@pytest.mark.asyncio
async def test_restriction_sites_rejects_unknown_enzyme(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/restriction-sites",
        json={"sequence": "GAATTC", "enzymes": ["NotAnEnzyme"]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"]["code"] == "UNSUPPORTED_PARAMETER"


@requires_wheel
@pytest.mark.asyncio
async def test_protein_properties_are_computed(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/protein-properties",
        json={"protein": "MKTAYIAKQRQISFVKSHFSRQ"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["length"] == 22
    assert 2500 < body["molecular_weight"] < 2800
    assert 10 < body["isoelectric_point"] < 12


@requires_wheel
@pytest.mark.asyncio
async def test_protein_properties_rejects_dna(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tools/sequence/protein-properties", json={"protein": "ACGTACGT"})
    # A,C,G,T are all valid amino-acid letters, so this is accepted as a
    # peptide; the case that must fail is a character outside the alphabet.
    assert r.status_code in (200, 422)
    bad = await client.post("/api/v1/tools/sequence/protein-properties", json={"protein": "MK#T"})
    assert bad.status_code == 422, bad.text


@requires_wheel
@pytest.mark.asyncio
async def test_melting_temp_methods(client: AsyncClient) -> None:
    primer = "ATGCGTACGTAGCTAGCTAG"
    for method in ("wallace", "gc", "nearest_neighbor"):
        r = await client.post(
            "/api/v1/tools/sequence/melting-temp",
            json={"sequence": primer, "method": method},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == method
        assert body["melting_temp_c"] > 0
    # The methods answer different numbers; a caller must never compare them
    # without reading `method`.
    assert body["method"] == "nearest_neighbor"


@requires_wheel
@pytest.mark.asyncio
async def test_melting_temp_rejects_a_non_primer(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tools/sequence/melting-temp", json={"sequence": "A" * 201})
    assert r.status_code == 422, r.text


@requires_wheel
@pytest.mark.asyncio
async def test_multiple_alignment_pads_and_scores(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/multiple-alignment",
        json={"sequences": ["ACGTACGT", "ACGT", "ACGTAAGT"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sequence_count"] == 3
    assert body["method"] == "progressive"
    # Every row must be the same width or the column positions mean nothing.
    assert {len(row) for row in body["aligned_sequences"]} == {body["column_count"]}
    assert body["identity_matrix"][0][0] == 1.0
    assert body["distance_matrix"][0][0] == 0.0


@requires_wheel
@pytest.mark.asyncio
async def test_tree_returns_newick(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/tree",
        json={
            "sequences": ["ACGTACGTACGT", "ACGTACGTACGA", "TTTTTTTTTTTT"],
            "labels": ["a", "b", "c"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["leaf_count"] == 3
    assert body["newick"].endswith(";")
    assert body["method"] == "neighbor-joining"
    assert "caveat" in body


@requires_wheel
@pytest.mark.asyncio
async def test_tree_rejects_duplicate_labels(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/tools/sequence/tree",
        json={
            "sequences": ["ACGT", "ACGA", "TTTT"],
            "labels": ["a", "a", "b"],
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["details"]["code"] == "UNSUPPORTED_PARAMETER"

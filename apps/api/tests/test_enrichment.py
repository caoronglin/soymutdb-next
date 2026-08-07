"""Tests for the GO/KEGG enrichment tool (Wave 2-B).

Strategy: statistics (hypergeometric right-tail p-values, Benjamini-Hochberg
correction) are verified against hand-computed values; the service layer is
exercised with in-memory annotation mappings (no database); the HTTP route is
tested through a minimal FastAPI app with an overridden ``get_db`` dependency,
so no testcontainers / PostgreSQL is required.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.tools_enrichment import router as enrichment_router
from app.core.database import get_db
from app.schemas.enrichment import EnrichmentRequest
from app.services import enrichment_service
from app.services.enrichment_service import (
    benjamini_hochberg,
    compute_enrichment,
    fetch_annotations,
    hypergeom_sf,
)

# ---------------------------------------------------------------------------
# Hypergeometric survival function (hand-computed references)
# ---------------------------------------------------------------------------


def _comb(n: int, k: int) -> int:
    return math.comb(n, k)


def test_hypergeom_sf_matches_hand_computation():
    """N=20, K=5, n=4, k=2: P(X>=2) = (C(5,2)C(15,2) + C(5,3)C(15,1) + C(5,4)C(15,0)) / C(20,4)."""
    expected = (
        _comb(5, 2) * _comb(15, 2)
        + _comb(5, 3) * _comb(15, 1)
        + _comb(5, 4) * _comb(15, 0)
    ) / _comb(20, 4)
    assert expected == 1205 / 4845
    assert hypergeom_sf(N=20, K=5, n=4, k=2) == pytest.approx(expected, abs=1e-12)


def test_hypergeom_sf_small_case_full_hand_sum():
    """N=10, K=3, n=4, k=3: only X=3 is possible above k -> C(3,3)C(7,1)/C(10,4)."""
    expected = _comb(3, 3) * _comb(7, 1) / _comb(10, 4)  # 7/210
    assert expected == pytest.approx(1 / 30, abs=1e-12)
    assert hypergeom_sf(N=10, K=3, n=4, k=3) == pytest.approx(expected, abs=1e-12)


def test_hypergeom_sf_boundary_cases():
    """Edge cases mirroring scipy: k at/below min overlap -> 1.0; above max -> 0.0."""
    # N=10, K=4, n=4: min overlap = max(0, 4+4-10) = 0.
    assert hypergeom_sf(N=10, K=4, n=4, k=0) == 1.0
    # max overlap = min(4, 4) = 4; k=5 impossible.
    assert hypergeom_sf(N=10, K=4, n=4, k=5) == 0.0
    # N=10, K=8, n=4: min overlap = 2 -> P(X >= 2) == 1.0
    assert hypergeom_sf(N=10, K=8, n=4, k=2) == 1.0


def test_hypergeom_sf_agrees_with_bruteforce_sum():
    """Cross-check against an explicit sum of math.comb PMFs for a larger case."""
    N, K, n, k = 50, 12, 9, 4
    total = _comb(N, n)
    expected = sum(
        _comb(K, x) * _comb(N - K, n - x) for x in range(k, min(n, K) + 1)
    ) / total
    assert hypergeom_sf(N=N, K=K, n=n, k=k) == pytest.approx(expected, abs=1e-12)


def test_hypergeom_sf_single_draw_is_binomial():
    """n=1 reduces to a Bernoulli: P(X >= 1) = K/N."""
    assert hypergeom_sf(N=100, K=17, n=1, k=1) == pytest.approx(0.17, abs=1e-12)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg correction (hand-computed references)
# ---------------------------------------------------------------------------


def test_benjamini_hochberg_hand_computed():
    """p = [0.01, 0.02, 0.05, 0.10], m=4 -> q = [0.04, 0.04, 0.0667, 0.10]."""
    q = benjamini_hochberg([0.01, 0.02, 0.05, 0.10])
    assert q[0] == pytest.approx(0.01 * 4 / 1, abs=1e-12)  # 0.04
    assert q[1] == pytest.approx(0.02 * 4 / 2, abs=1e-12)  # 0.04
    assert q[2] == pytest.approx(0.05 * 4 / 3, abs=1e-12)  # 0.06666...
    assert q[3] == pytest.approx(0.10 * 4 / 4, abs=1e-12)  # 0.10
    # Monotone: q-values non-decreasing in p-value order.
    assert all(q[i] <= q[i + 1] for i in range(3))


def test_benjamini_hochberg_preserves_order_and_empty():
    assert benjamini_hochberg([]) == []
    unsorted = [0.5, 0.01, 0.2]
    q = benjamini_hochberg(unsorted)
    assert len(q) == 3
    # Same ordering as input, monotone after sorting by p.
    order = sorted(range(3), key=lambda i: unsorted[i])
    assert q[order[0]] <= q[order[1]] <= q[order[2]]


# ---------------------------------------------------------------------------
# Core enrichment computation (in-memory annotations)
# ---------------------------------------------------------------------------

# Background of 10 genes; three terms with K = 3, 4, 2.
_BG_TERMS: dict[str, set[str]] = {
    f"g{i}": set() for i in range(1, 11)
}
_BG_TERMS["g1"] |= {"A", "B"}
_BG_TERMS["g2"] |= {"A", "B"}
_BG_TERMS["g3"] |= {"A", "B"}
_BG_TERMS["g4"] |= {"B"}
_BG_TERMS["g9"] |= {"C"}
_BG_TERMS["g10"] |= {"C"}
_TERM_NAMES = {"A": "Term A", "B": "Term B", "C": "Term C"}


def test_compute_enrichment_known_small_set():
    """Input g1..g4: term A k=3/K=3, term B k=4/K=4, term C k=0/K=2.

    N=10, n=4.
    p_A = C(3,3)C(7,1)/C(10,4) = 7/210 = 0.03333
    p_B = C(4,4)C(6,0)/C(10,4) = 1/210 = 0.004762
    BH (m=3): q_B = p_B*3/1, q_A = p_A*3/2, q_C = 1.0.
    """
    result = compute_enrichment(
        ["g1", "g2", "g3", "g4"],
        _BG_TERMS,
        _TERM_NAMES,
        ontology="go",
        p_threshold=0.05,
        max_terms=20,
    )
    assert result.ontology == "go"
    assert result.input_genes == 4
    assert result.background_genes == 10
    assert result.message is None

    p_B = _comb(4, 4) * _comb(6, 0) / _comb(10, 4)
    p_A = _comb(3, 3) * _comb(7, 1) / _comb(10, 4)
    assert p_B == pytest.approx(1 / 210, abs=1e-12)
    assert p_A == pytest.approx(7 / 210, abs=1e-12)

    terms = {t.id: t for t in result.terms}
    assert set(terms) == {"A", "B"}  # C (p=1.0) filtered out by threshold

    # p-values match hand computation.
    assert terms["A"].p_value == pytest.approx(p_A, abs=1e-12)
    assert terms["B"].p_value == pytest.approx(p_B, abs=1e-12)

    # Only terms hit by input genes are tested (k=0 terms never enter the
    # test set, matching clusterProfiler semantics) -> BH over m=2 terms.
    assert terms["B"].q_value == pytest.approx(p_B * 2 / 1, abs=1e-12)
    assert terms["A"].q_value == pytest.approx(p_A * 2 / 2, abs=1e-12)

    # Sorted by q-value ascending: B (more significant) first.
    assert [t.id for t in result.terms] == ["B", "A"]

    # Gene membership and names.
    assert terms["A"].gene_count == 3
    assert set(terms["A"].genes) == {"g1", "g2", "g3"}
    assert terms["A"].name == "Term A"
    assert terms["B"].gene_count == 4
    assert set(terms["B"].genes) == {"g1", "g2", "g3", "g4"}


def test_compute_enrichment_max_terms_and_genes_truncation():
    """max_terms truncates; member genes list is capped at 20."""
    # 25 members on one term, 30 terms total.
    gene_to_terms: dict[str, set[str]] = {}
    term_names: dict[str, str] = {}
    input_genes: list[str] = []
    for i in range(1, 31):
        term = f"T{i:02d}"
        term_names[term] = f"Term {i}"
        members = [f"g{j:02d}" for j in range(1, 26)]
        for m in members:
            gene_to_terms.setdefault(m, set()).add(term)
    # Give every input gene the same 30 terms -> identical p-values; sort by id.
    input_genes = [f"g{j:02d}" for j in range(1, 26)]

    result = compute_enrichment(
        input_genes,
        gene_to_terms,
        term_names,
        ontology="kegg",
        p_threshold=1.0,
        max_terms=5,
    )
    assert len(result.terms) == 5
    first = result.terms[0]
    assert len(first.genes) == 20  # capped
    assert first.gene_count == 25
    assert result.ontology == "kegg"


def test_compute_enrichment_deduplicates_input():
    result = compute_enrichment(
        ["g1", "g2", "g1", "g3", "g2", "g4"],
        _BG_TERMS,
        _TERM_NAMES,
        ontology="go",
        p_threshold=0.05,
    )
    assert result.input_genes == 4  # duplicates removed


def test_compute_enrichment_no_annotated_input_genes():
    """Input genes without any annotations -> empty terms + message."""
    result = compute_enrichment(
        ["x1", "x2"],
        _BG_TERMS,
        _TERM_NAMES,
        ontology="go",
        p_threshold=0.05,
    )
    assert result.terms == []
    assert result.input_genes == 2
    assert result.background_genes == 10
    assert result.message is not None
    assert "GO" in result.message


def test_compute_enrichment_empty_annotation_table():
    """No annotations available at all -> empty terms + explicit message."""
    result = compute_enrichment(
        ["g1", "g2"],
        {},
        {},
        ontology="kegg",
        p_threshold=0.05,
    )
    assert result.terms == []
    assert result.background_genes == 0
    assert result.message is not None
    assert "annotations" in result.message


def test_compute_enrichment_partially_annotated_input():
    """Unannotated input genes are excluded from the tested set, not errors."""
    # g1..g4 annotated; "ghost" has no annotations.
    result = compute_enrichment(
        ["g1", "g2", "g3", "g4", "ghost"],
        _BG_TERMS,
        _TERM_NAMES,
        ontology="go",
        p_threshold=0.05,
    )
    assert result.input_genes == 5
    assert result.terms  # still computed from the 4 annotated genes


# ---------------------------------------------------------------------------
# Annotation loading (mocked session)
# ---------------------------------------------------------------------------


def _mock_db(has_table: bool, rows: list[tuple[Any, Any, Any]]) -> AsyncMock:
    class _FakeResult:
        def __init__(self, all_rows):
            self._all_rows = all_rows

        def all(self):
            return self._all_rows

    db = AsyncMock()
    connection = AsyncMock()
    connection.run_sync = AsyncMock(side_effect=lambda fn: has_table)
    db.connection.return_value = connection
    db.execute.return_value = _FakeResult(rows)
    return db


async def test_fetch_annotations_table_missing_returns_empty():
    db = _mock_db(has_table=False, rows=[])
    gene_to_terms, term_names = await fetch_annotations(db, "go")
    assert gene_to_terms == {}
    assert term_names == {}
    db.execute.assert_not_awaited()


async def test_fetch_annotations_parses_rows():
    rows = [
        ("Glyma.01G000100", "GO:0008150", "biological_process"),
        ("Glyma.01G000100", "GO:0003674", "molecular_function"),
        ("Glyma.01G000200", "GO:0008150", "biological_process"),
    ]
    db = _mock_db(has_table=True, rows=rows)
    gene_to_terms, term_names = await fetch_annotations(db, "go")
    assert gene_to_terms == {
        "Glyma.01G000100": {"GO:0008150", "GO:0003674"},
        "Glyma.01G000200": {"GO:0008150"},
    }
    assert term_names == {
        "GO:0008150": "biological_process",
        "GO:0003674": "molecular_function",
    }
    # term_name NULL falls back to the term id.
    rows_null = [("Glyma.01G000100", "GO:0009999", None)]
    gene_to_terms, term_names = await fetch_annotations(
        _mock_db(has_table=True, rows=rows_null), "go"
    )
    assert term_names["GO:0009999"] == "GO:0009999"


# ---------------------------------------------------------------------------
# HTTP route (mini app, no database)
# ---------------------------------------------------------------------------


def _make_app() -> Any:
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError

    from app.core.exceptions import validation_exception_handler

    app = FastAPI(title="Enrichment Test API")
    app.include_router(enrichment_router, prefix="/api/v1")
    app.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    return app


def _make_client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_enrichment_route_validation_empty_genes_422():
    """POST with empty genes list must fail with 422."""
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment", json={"genes": []}
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert any("genes" in e["field"] for e in body["errors"])


async def test_enrichment_route_validation_blank_gene_422():
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"genes": ["Glyma.01G000100", "   "]},
        )
    assert response.status_code == 422


async def test_enrichment_route_defaults_and_success(monkeypatch):
    """Happy path: mocked annotations produce a correct term list.

    Background N=20 (g1..g20); term B: K=4 (g1..g4); term A: K=10 (g1..g10).
    Input g1..g4 (n=4):
      p_B = C(4,4)C(16,0)/C(20,4) = 1/4845 ~= 0.000206
      p_A = C(10,4)C(10,0)/C(20,4) = 210/4845 ~= 0.04334
    BH over m=2 terms: q_B = p_B*2, q_A = p_A*2/2 = p_A.
    """
    gene_to_terms: dict[str, set[str]] = {f"g{i}": set() for i in range(1, 21)}
    for i in range(1, 5):
        gene_to_terms[f"g{i}"] |= {"A", "B"}
    for i in range(5, 11):
        gene_to_terms[f"g{i}"] |= {"A"}
    term_names = {"A": "Term A", "B": "Term B"}

    async def fake_fetch(db, ontology):
        assert ontology == "go"  # default
        return gene_to_terms, term_names

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)

    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"genes": ["g1", "g2", "g3", "g4"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ontology"] == "go"
    assert body["input_genes"] == 4
    assert body["background_genes"] == 20
    term_ids = [t["id"] for t in body["terms"]]
    assert term_ids == ["B", "A"]  # sorted by q-value ascending
    term_b = next(t for t in body["terms"] if t["id"] == "B")
    assert term_b["p_value"] == pytest.approx(1 / 4845, abs=1e-12)
    assert term_b["q_value"] == pytest.approx(2 / 4845, abs=1e-12)
    assert term_b["gene_count"] == 4


async def test_enrichment_route_kegg_ontology_and_unknown_genes(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_fetch(db, ontology):
        captured["ontology"] = ontology
        return {}, {}

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"genes": ["nope1"], "ontology": "kegg"},
        )
    assert response.status_code == 200
    body = response.json()
    assert captured["ontology"] == "kegg"
    assert body["terms"] == []
    assert body["message"] is not None  # explicit no-annotation note


def test_enrichment_request_schema_limits():
    with pytest.raises(Exception):
        EnrichmentRequest(genes=[])
    with pytest.raises(Exception):
        EnrichmentRequest(genes=["g1"] * 501)
    with pytest.raises(Exception):
        EnrichmentRequest(genes=["g1"], ontology="kegg", p_threshold=1.5)
    ok = EnrichmentRequest(genes=[" g1 ", "g2", "g1"], max_terms=50)
    assert ok.genes == ["g1", "g2", "g1"]



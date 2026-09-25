"""Tests for the GO/KEGG enrichment tool (Wave 2-B).

Strategy: statistics (hypergeometric right-tail p-values, Benjamini-Hochberg
correction, GSEA running-sum ES / NES / p-value) are verified against
hand-computed values; the service layer is exercised with in-memory
annotation mappings (no database); the HTTP route is tested through a
minimal FastAPI app with an overridden ``get_db`` dependency, so no
testcontainers / PostgreSQL is required.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.tools_enrichment import router as enrichment_router
from app.core.database import get_db
from app.core.exceptions import ServiceUnavailableError
from app.schemas.enrichment import EnrichmentRequest
from app.services import enrichment_service
from app.services.enrichment_service import (
    benjamini_hochberg,
    compute_enrichment,
    compute_gsea_enrichment,
    fetch_annotation_source,
    fetch_annotations,
    gsea_term_stat,
    hypergeom_sf,
)
from app.services.release_context import ReleaseContext, get_release_context

# ---------------------------------------------------------------------------
# Hypergeometric survival function (hand-computed references)
# ---------------------------------------------------------------------------


async def _empty_annotation_source(db, ontology, *, assembly_id, release_id):
    return None


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


def _mock_db(
    has_table: bool,
    rows: list[tuple[Any, Any, Any]],
    columns: list[str] | None = None,
) -> AsyncMock:
    class _FakeResult:
        def __init__(self, all_rows):
            self._all_rows = all_rows

        def all(self):
            return self._all_rows

    db = AsyncMock()
    connection = AsyncMock()
    if columns is None:
        columns = [
            "annotation_set_id",
            "assembly_id",
            "release_id",
            "gene_id",
            "term_id",
            "term_name",
            "ontology",
        ]
    connection.run_sync = AsyncMock(
        # run_sync returns the lambda result directly; the second lambda in
        # fetch_annotations returns a set of column names.
        side_effect=[has_table, set(columns)]
    )
    db.connection.return_value = connection
    db.execute.return_value = _FakeResult(rows)
    return db


async def test_fetch_annotations_table_missing_returns_empty():
    db = _mock_db(has_table=False, rows=[])
    gene_to_terms, term_names = await fetch_annotations(
        db, "go", assembly_id=5, release_id=7
    )
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
    gene_to_terms, term_names = await fetch_annotations(
        db, "go", assembly_id=5, release_id=7
    )
    assert db.execute.await_args.args[1] == {
        "ontology": "go",
        "assembly_id": 5,
        "release_id": 7,
    }
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
        _mock_db(has_table=True, rows=rows_null),
        "go",
        assembly_id=5,
        release_id=7,
    )
    assert term_names["GO:0009999"] == "GO:0009999"


async def test_fetch_annotations_fails_closed_without_assembly_column():
    db = _mock_db(
        has_table=True,
        rows=[],
        columns=["gene_id", "term_id", "term_name", "ontology"],
    )
    with pytest.raises(ServiceUnavailableError, match="provenance"):
        await fetch_annotations(db, "go", assembly_id=5, release_id=7)
    db.execute.assert_not_awaited()


async def test_fetch_annotations_fails_closed_without_release_column():
    db = _mock_db(
        has_table=True,
        rows=[],
        columns=["assembly_id", "gene_id", "term_id", "term_name", "ontology"],
    )
    with pytest.raises(ServiceUnavailableError, match="release provenance"):
        await fetch_annotations(db, "go", assembly_id=5, release_id=7)
    db.execute.assert_not_awaited()


async def test_fetch_annotations_fails_closed_without_source_set_reference():
    db = _mock_db(
        has_table=True,
        rows=[],
        columns=["assembly_id", "release_id", "gene_id", "term_id", "term_name", "ontology"],
    )
    with pytest.raises(ServiceUnavailableError, match="source, assembly, and release"):
        await fetch_annotations(db, "go", assembly_id=5, release_id=7)
    db.execute.assert_not_awaited()


async def test_fetch_annotations_fails_closed_when_provenance_cannot_be_checked():
    db = AsyncMock()
    connection = AsyncMock()
    connection.run_sync.side_effect = RuntimeError("database metadata unavailable")
    db.connection.return_value = connection

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await fetch_annotations(db, "go", assembly_id=5, release_id=7)

    assert exc_info.value.details == {"code": "annotation_provenance_unavailable"}
    db.execute.assert_not_awaited()


async def test_fetch_annotation_source_returns_matching_snapshot():
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def scalar_one(self):
            return self._rows[0][0]

    imported_at = datetime(2026, 9, 24, tzinfo=UTC)
    source = SimpleNamespace(
        id=11,
        source_name="SoyBase",
        source_version="2026-08",
        source_url="https://source.example/annotations/2026-08",
        source_sha256="a" * 64,
        row_count=1,
        imported_at=imported_at,
    )
    db = AsyncMock()
    connection = AsyncMock()
    connection.run_sync.side_effect = [
        (True, True),
        {
            "id",
            "assembly_id",
            "release_id",
            "ontology",
            "source_name",
            "source_version",
            "source_url",
            "source_sha256",
            "row_count",
            "imported_at",
        },
    ]
    db.connection.return_value = connection
    db.execute.side_effect = [
        _FakeResult([source]),
        _FakeResult([(1,)]),
        _FakeResult([]),
    ]

    result = await fetch_annotation_source(
        db, "go", assembly_id=5, release_id=7
    )

    assert result is not None
    assert result.name == "SoyBase"
    assert result.version == "2026-08"
    assert result.sha256 == "a" * 64
    assert result.imported_at == imported_at


async def test_fetch_annotation_source_rejects_mismatched_rows():
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def first(self):
            return self._rows[0] if self._rows else None

        def scalar_one(self):
            return self._rows[0][0]

    source = SimpleNamespace(
        id=11,
        source_name="SoyBase",
        source_version="2026-08",
        source_url="https://source.example/annotations/2026-08",
        source_sha256="a" * 64,
        row_count=1,
        imported_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    db = AsyncMock()
    connection = AsyncMock()
    connection.run_sync.side_effect = [
        (True, True),
        {
            "id",
            "assembly_id",
            "release_id",
            "ontology",
            "source_name",
            "source_version",
            "source_url",
            "source_sha256",
            "row_count",
            "imported_at",
        },
    ]
    db.connection.return_value = connection
    db.execute.side_effect = [
        _FakeResult([source]),
        _FakeResult([(1,)]),
        _FakeResult([(1,)]),
    ]

    with pytest.raises(ServiceUnavailableError, match="do not match"):
        await fetch_annotation_source(db, "go", assembly_id=5, release_id=7)


async def test_fetch_annotation_source_rejects_row_count_drift():
    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

        def scalar_one(self):
            return self._rows[0][0]

    source = SimpleNamespace(
        id=11,
        source_name="SoyBase",
        source_version="2026-08",
        source_url="https://source.example/annotations/2026-08",
        source_sha256="a" * 64,
        row_count=2,
        imported_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    db = AsyncMock()
    connection = AsyncMock()
    connection.run_sync.side_effect = [
        (True, True),
        {
            "id",
            "assembly_id",
            "release_id",
            "ontology",
            "source_name",
            "source_version",
            "source_url",
            "source_sha256",
            "row_count",
            "imported_at",
        },
    ]
    db.connection.return_value = connection
    db.execute.side_effect = [_FakeResult([source]), _FakeResult([(1,)])]

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await fetch_annotation_source(db, "go", assembly_id=5, release_id=7)

    assert exc_info.value.details == {"code": "annotation_source_row_count_mismatch"}


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
    async def override_release_context() -> ReleaseContext:
        return ReleaseContext(release_id=7, assembly_id=5, assembly="Wm82.v5")

    app.dependency_overrides[get_release_context] = override_release_context
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
            "/api/v1/tools/enrichment", json={"assembly_id": 5, "genes": []}
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert any("genes" in e["field"] for e in body["errors"])


async def test_enrichment_route_requires_assembly_id():
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment", json={"genes": ["G1"]}
        )
    assert response.status_code == 422
    assert any(
        error["field"].endswith("assembly_id") for error in response.json()["errors"]
    )


async def test_enrichment_route_validation_blank_gene_422():
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"assembly_id": 5, "genes": ["Glyma.01G000100", "   "]},
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

    async def fake_fetch(db, ontology, *, assembly_id, release_id):
        assert ontology == "go"  # default
        assert assembly_id == 5
        assert release_id == 7
        return gene_to_terms, term_names

    async def fake_resolve(db, assembly_id, release_id):
        assert release_id == 7
        return SimpleNamespace(id=assembly_id, name="Wm82.v5", version="v5")

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)
    monkeypatch.setattr(enrichment_service, "fetch_annotation_source", _empty_annotation_source)
    monkeypatch.setattr(enrichment_service, "_resolve_assembly", fake_resolve)

    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"assembly_id": 5, "genes": ["g1", "g2", "g3", "g4"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ontology"] == "go"
    assert body["assembly_id"] == 5
    assert body["assembly_name"] == "Wm82.v5"
    assert body["assembly_version"] == "v5"
    assert body["release_id"] == 7
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

    async def fake_fetch(db, ontology, *, assembly_id, release_id):
        captured["ontology"] = ontology
        captured["assembly_id"] = assembly_id
        captured["release_id"] = release_id
        return {}, {}

    async def fake_resolve(db, assembly_id, release_id):
        return SimpleNamespace(id=assembly_id, name="Wm82.v5", version="v5")

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)
    monkeypatch.setattr(enrichment_service, "fetch_annotation_source", _empty_annotation_source)
    monkeypatch.setattr(enrichment_service, "_resolve_assembly", fake_resolve)
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"assembly_id": 5, "genes": ["nope1"], "ontology": "kegg"},
        )
    assert response.status_code == 200
    body = response.json()
    assert captured["ontology"] == "kegg"
    assert captured["assembly_id"] == 5
    assert captured["release_id"] == 7
    assert body["assembly_id"] == 5
    assert body["release_id"] == 7
    assert body["terms"] == []
    assert body["message"] is not None  # explicit no-annotation note


def test_enrichment_request_schema_limits():
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=[])
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"] * 501)
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"], ontology="kegg", p_threshold=1.5)
    ok = EnrichmentRequest(assembly_id=5, genes=[" g1 ", "g2", "g1"], max_terms=50)
    assert ok.genes == ["g1", "g2", "g1"]


# ---------------------------------------------------------------------------
# GSEA (rank-based) statistics — hand-computed references
# ---------------------------------------------------------------------------

# Ranked input: g1..g8 with values 10..3 -> descending order g1 (10), g2 (9),
# g3 (8), g4 (7), g5 (6), g6 (5), g7 (4), g8 (3).  The walk step is +1/k at
# member positions and -1/(n-k) at non-member positions.
_GSEA_GENES = [f"g{i}" for i in range(1, 9)]
_GSEA_VALUES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0]


def _gsea_annotations(
    *term_members: set[str],
) -> tuple[dict[str, set[str]], dict[str, str]]:
    gene_to_terms: dict[str, set[str]] = {g: set() for g in _GSEA_GENES}
    term_names: dict[str, str] = {}
    for i, members in enumerate(term_members):
        term = f"T{i}"
        term_names[term] = f"Term {i}"
        for gene in members:
            gene_to_terms[gene].add(term)
    return gene_to_terms, term_names


def test_gsea_term_stat_hand_computed():
    """n=8, k=3, hits at descending-rank positions 2, 4, 5 (0-based 1, 3, 4).

    Running sum (hit +1/3, miss -1/5):
      pos 1..8: -0.2, +0.1333, -0.0667, +0.2667, +0.6, +0.4, +0.2, 0.0
    ES = +0.6, lambda = k(n-k)/n = 15/8 = 1.875
    NES = 0.6 * sqrt(1.875), p = exp(-2 * 1.875 * 0.36) = exp(-1.35)
    """
    es, nes, p = gsea_term_stat([1, 3, 4], k=3, n=8)
    lam = 3 * 5 / 8
    assert es == pytest.approx(0.6, abs=1e-12)
    assert nes == pytest.approx(0.6 * math.sqrt(lam), abs=1e-12)
    assert p == pytest.approx(math.exp(-1.35), abs=1e-12)
    assert p == pytest.approx(math.exp(-2.0 * lam * es * es), abs=1e-12)


def test_gsea_term_stat_all_members_at_top_is_es_one():
    """Members at positions 1..3 (0-based 0,1,2): walk peaks at +1.0."""
    es, nes, p = gsea_term_stat([0, 1, 2], k=3, n=8)
    assert es == pytest.approx(1.0, abs=1e-12)
    assert nes == pytest.approx(math.sqrt(15 / 8), abs=1e-12)
    assert p == pytest.approx(math.exp(-3.75), abs=1e-12)


def test_gsea_term_stat_all_members_at_bottom_is_negative():
    """Members at positions 6..8: walk troughs at -1.0 (same p as +1.0)."""
    es, nes, p = gsea_term_stat([5, 6, 7], k=3, n=8)
    assert es == pytest.approx(-1.0, abs=1e-12)
    assert nes == pytest.approx(-math.sqrt(15 / 8), abs=1e-12)
    assert p == pytest.approx(math.exp(-3.75), abs=1e-12)


def test_compute_gsea_enrichment_hand_computed():
    """Terms: T0={g2,g4,g5} (ES +0.6, p = exp(-1.35)) and T1={g1,g2,g3}
    (ES +1.0, p = exp(-3.75)).  n=8 ranked genes, m=2 tested terms:
      q_T1 = p_T1 * 2 / 1, q_T0 = p_T0 * 2 / 2 = p_T0.
    """
    gene_to_terms, term_names = _gsea_annotations(
        {"g2", "g4", "g5"}, {"g1", "g2", "g3"}
    )
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=20,
        min_genes=1,
    )
    assert result.mode == "gsea"
    assert result.ontology == "go"
    assert result.input_genes == 8
    assert result.background_genes == 8
    assert result.message is None

    # Sorted by q-value ascending: T1 (more significant) first.
    assert [t.id for t in result.terms] == ["T1", "T0"]

    t1, t0 = result.terms
    assert t1.es == pytest.approx(1.0, abs=1e-12)
    assert t1.p_value == pytest.approx(math.exp(-3.75), abs=1e-12)
    assert t1.q_value == pytest.approx(math.exp(-3.75) * 2, abs=1e-12)
    assert t1.size == 3

    assert t0.es == pytest.approx(0.6, abs=1e-12)
    assert t0.nes == pytest.approx(0.6 * math.sqrt(15 / 8), abs=1e-12)
    assert t0.p_value == pytest.approx(math.exp(-1.35), abs=1e-12)
    assert t0.q_value == pytest.approx(math.exp(-1.35), abs=1e-12)
    assert t0.size == 3
    assert set(t0.genes) == {"g2", "g4", "g5"}
    assert t0.name == "Term 0"


def test_compute_gsea_enrichment_p_threshold_filters():
    """p_threshold=0.05 keeps only T1 (p = exp(-3.75) ~ 0.0235 < 0.05)."""
    gene_to_terms, term_names = _gsea_annotations(
        {"g2", "g4", "g5"}, {"g1", "g2", "g3"}
    )
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=0.05,
        max_terms=20,
        min_genes=1,
    )
    assert [t.id for t in result.terms] == ["T1"]


def test_compute_gsea_enrichment_min_genes_filters():
    """Both terms have size 3; min_genes=4 excludes them -> empty + message."""
    gene_to_terms, term_names = _gsea_annotations(
        {"g2", "g4", "g5"}, {"g1", "g2", "g3"}
    )
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=20,
        min_genes=4,
    )
    assert result.terms == []
    assert result.message is not None
    assert "min_genes" in result.message


def test_compute_gsea_enrichment_all_genes_in_one_term_skipped():
    """k == n is degenerate (no background steps) -> term skipped + message."""
    gene_to_terms, term_names = _gsea_annotations(set(_GSEA_GENES))
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=20,
        min_genes=1,
    )
    assert result.terms == []
    assert result.message is not None


def test_compute_gsea_enrichment_deduplicates_keeping_first_value():
    """Duplicated g1: second value (999) must be ignored -> g1 still ranks
    at the top (value 10) and the term keeps ES = +1.0.  g4 is outside the
    term so the set is not degenerate (k=3 < n=4)."""
    genes = ["g1", "g2", "g1", "g3", "g4"]
    values = [10.0, 9.0, 999.0, 8.0, 1.0]
    gene_to_terms, term_names = _gsea_annotations({"g1", "g2", "g3"})
    result = compute_gsea_enrichment(
        genes,
        values,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=20,
        min_genes=1,
    )
    assert result.input_genes == 4
    assert result.terms[0].es == pytest.approx(1.0, abs=1e-12)
    assert result.terms[0].size == 3


def test_compute_gsea_enrichment_unannotated_genes_are_background_steps():
    """Genes without annotations still rank and only contribute miss steps.

    n=10 (g9 and g10 added, values 9.5 and 1.0).  Members of T0 at positions
    0, 2, 3 (values 10, 9, 8); the single miss before position 3 caps the
    walk at 1 - 1/7 = 6/7.
    """
    gene_to_terms, term_names = _gsea_annotations({"g1", "g2", "g3"})
    genes = _GSEA_GENES + ["g9", "g10"]
    values = _GSEA_VALUES + [9.5, 1.0]
    result = compute_gsea_enrichment(
        genes,
        values,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=20,
        min_genes=1,
    )
    assert result.input_genes == 10
    lam = 3 * 7 / 10
    t = result.terms[0]
    assert t.es == pytest.approx(6 / 7, abs=1e-12)
    assert t.nes == pytest.approx((6 / 7) * math.sqrt(lam), abs=1e-12)
    assert t.p_value == pytest.approx(math.exp(-2.0 * lam * (6 / 7) ** 2), abs=1e-12)
    assert set(t.genes) == {"g1", "g2", "g3"}


def test_compute_gsea_enrichment_empty_annotation_table():
    """No annotations at all -> empty terms + explicit message."""
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        {},
        {},
        ontology="kegg",
        p_threshold=1.0,
        max_terms=20,
        min_genes=1,
    )
    assert result.terms == []
    assert result.background_genes == 0
    assert result.message is not None
    assert "annotations" in result.message


def test_compute_gsea_enrichment_max_terms_truncates():
    """max_terms truncates the q-value-sorted list."""
    gene_to_terms: dict[str, set[str]] = {g: set() for g in _GSEA_GENES}
    term_names: dict[str, str] = {}
    for i in range(1, 11):
        term = f"T{i:02d}"
        term_names[term] = f"Term {i}"
        for g in ("g1", "g2", "g3"):
            gene_to_terms[g].add(term)
    result = compute_gsea_enrichment(
        _GSEA_GENES,
        _GSEA_VALUES,
        gene_to_terms,
        term_names,
        ontology="go",
        p_threshold=1.0,
        max_terms=5,
        min_genes=1,
    )
    assert len(result.terms) == 5


# ---------------------------------------------------------------------------
# GSEA request schema validation
# ---------------------------------------------------------------------------


def test_enrichment_request_gsea_schema_rules():
    # gsea mode without values -> error.
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"], mode="gsea")
    # values/genes length mismatch -> error.
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1", "g2"], mode="gsea", values=[1.0])
    # non-finite values -> error.
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"], mode="gsea", values=[float("nan")])
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"], mode="gsea", values=[float("inf")])
    # min_genes bounds.
    with pytest.raises(Exception):
        EnrichmentRequest(assembly_id=5, genes=["g1"], mode="gsea", values=[1.0], min_genes=0)
    # Happy path.
    ok = EnrichmentRequest(
        assembly_id=5,
        genes=["g1", "g2"], mode="gsea", values=[1.0, -2.5], min_genes=3
    )
    assert ok.values == [1.0, -2.5]
    assert ok.min_genes == 3
    # ora mode ignores values entirely.
    ok2 = EnrichmentRequest(assembly_id=5, genes=["g1"], mode="ora", values=[1.0])
    assert ok2.values == [1.0]


# ---------------------------------------------------------------------------
# GSEA HTTP route (mini app, no database)
# ---------------------------------------------------------------------------


async def test_enrichment_route_gsea_missing_values_422():
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"assembly_id": 5, "genes": ["g1", "g2"], "mode": "gsea"},
        )
    assert response.status_code == 422


async def test_enrichment_route_gsea_values_mismatch_422():
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={"assembly_id": 5, "genes": ["g1", "g2"], "mode": "gsea", "values": [1.0]},
        )
    assert response.status_code == 422


async def test_enrichment_route_gsea_non_finite_values_422():
    """1e999 is valid JSON but parses to +inf -> rejected by the schema
    validator (httpx refuses to serialize NaN/Infinity literals, so the raw
    body is sent via content=)."""
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            content=b'{"assembly_id": 5, "genes": ["g1"], "mode": "gsea", "values": [1e999]}',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422


async def test_enrichment_route_gsea_happy_path(monkeypatch):
    """GSEA mode over mocked annotations: T0={g1,g2,g3} on the 8-gene ranked
    list -> ES = +1.0, p = exp(-3.75); m=1 tested term -> q = p."""
    gene_to_terms, term_names = _gsea_annotations({"g1", "g2", "g3"})

    async def fake_fetch(db, ontology, *, assembly_id, release_id):
        assert ontology == "go"
        assert assembly_id == 5
        assert release_id == 7
        return gene_to_terms, term_names

    async def fake_resolve(db, assembly_id, release_id):
        assert release_id == 7
        return SimpleNamespace(id=assembly_id, name="Wm82.v5", version="v5")

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)
    monkeypatch.setattr(enrichment_service, "fetch_annotation_source", _empty_annotation_source)
    monkeypatch.setattr(enrichment_service, "_resolve_assembly", fake_resolve)
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={
                "assembly_id": 5,
                "genes": _GSEA_GENES,
                "values": _GSEA_VALUES,
                "mode": "gsea",
                "min_genes": 1,
                "p_threshold": 0.05,
                "max_terms": 20,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "gsea"
    assert body["ontology"] == "go"
    assert body["input_genes"] == 8
    assert body["background_genes"] == 8
    assert body["release_id"] == 7
    assert len(body["terms"]) == 1
    term = body["terms"][0]
    assert term["id"] == "T0"
    assert term["es"] == pytest.approx(1.0, abs=1e-12)
    assert term["nes"] == pytest.approx(math.sqrt(15 / 8), abs=1e-12)
    assert term["p_value"] == pytest.approx(math.exp(-3.75), abs=1e-12)
    assert term["q_value"] == pytest.approx(math.exp(-3.75), abs=1e-12)
    assert term["size"] == 3


async def test_enrichment_route_ora_mode_response_and_values_ignored(monkeypatch):
    """ORA mode (explicit) returns mode='ora' and ignores 'values'."""
    gene_to_terms: dict[str, set[str]] = {f"g{i}": set() for i in range(1, 21)}
    for i in range(1, 5):
        gene_to_terms[f"g{i}"] |= {"A"}
    term_names = {"A": "Term A"}

    async def fake_fetch(db, ontology, *, assembly_id, release_id):
        assert assembly_id == 5
        assert release_id == 7
        return gene_to_terms, term_names

    async def fake_resolve(db, assembly_id, release_id):
        assert release_id == 7
        return SimpleNamespace(id=assembly_id, name="Wm82.v5", version="v5")

    monkeypatch.setattr(enrichment_service, "fetch_annotations", fake_fetch)
    monkeypatch.setattr(enrichment_service, "fetch_annotation_source", _empty_annotation_source)
    monkeypatch.setattr(enrichment_service, "_resolve_assembly", fake_resolve)
    app = _make_app()

    async def override_get_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    async with _make_client(app) as client:
        response = await client.post(
            "/api/v1/tools/enrichment",
            json={
                "assembly_id": 5,
                "genes": ["g1", "g2", "g3", "g4"],
                "mode": "ora",
                "values": [1.0, 2.0, 3.0, 4.0],  # ignored in ora mode
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "ora"
    assert body["release_id"] == 7
    assert len(body["terms"]) == 1
    assert body["terms"][0]["gene_count"] == 4

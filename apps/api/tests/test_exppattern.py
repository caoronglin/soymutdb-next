"""Tests for the expression-pattern tool (``POST /api/v1/tools/exppattern``).

Covers: matrix structure, z-score scaling, clustering ordering (both SciPy
hierarchical and mean-sort fallback), missing-gene handling, condition
filtering, and the 50 genes × 200 conditions scale limit (422).
Uses mocked DB session — no PostgreSQL required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.exceptions import (
    SoyMutDBError,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)
from app.services import exppattern_service

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_exec_result(scalars_list=None):
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_list or []
    return r


def _make_lib(lib_id: int, name: str):
    lib = MagicMock()
    lib.id = lib_id
    lib.library_name = name
    lib.tissue = "leaf"
    lib.treatment = "control"
    return lib


def _make_expr(gene_id: str, library, fpkm: float | None):
    ed = MagicMock()
    ed.gene_id = gene_id
    ed.library_id = library.id
    ed.fpkm = fpkm
    ed.library = library
    return ed


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    default_result = _make_exec_result()
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


@pytest.fixture
def libraries():
    return [_make_lib(1, "Leaf Control"), _make_lib(2, "Root Drought")]


@pytest.fixture
async def client(mock_session):
    """Test client with the *mock_session* injected."""
    from app.api.v1.tools_exppattern import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _setup_data(mock_session, libraries, expr_rows):
    """Configure the two expected executes: libraries, then expression rows."""
    mock_session.execute.side_effect = [
        _make_exec_result(scalars_list=libraries),
        _make_exec_result(scalars_list=expr_rows),
    ]


# ---------------------------------------------------------------------------
# Matrix structure & values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMatrixStructure:
    async def test_matrix_structure_raw_values(
        self, client, mock_session, libraries
    ):
        """scale=none returns raw fpkm values in a gene × condition matrix."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G1", libraries[1], 20.0),
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G2", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1", "G2"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genes"] == ["G1", "G2"]
        assert data["conditions"] == ["Leaf Control", "Root Drought"]
        assert data["matrix"] == [[10.0, 20.0], [1.0, 3.0]]
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "input"
        assert data["missing_genes"] == []
        assert data["value_range"] == [1.0, 20.0]

    async def test_zscore_default(self, client, mock_session, libraries):
        """Default scale=zscore standardizes each gene row (ddof=0)."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 1.0),
                _make_expr("G1", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": ["G1"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scale"] == "zscore"
        # mean=2, std=1 -> [-1, 1]
        assert data["matrix"] == [[-1.0, 1.0]]

    async def test_zscore_constant_row_is_zero(self, client, mock_session, libraries):
        """A constant row has undefined z-score -> zeros (no NaN)."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 5.0),
                _make_expr("G1", libraries[1], 5.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": ["G1"]}
        )
        assert response.status_code == 200
        assert response.json()["matrix"] == [[0.0, 0.0]]

    async def test_condition_filtering(self, client, mock_session, libraries):
        """Passing conditions restricts the matrix columns to those libraries."""
        _setup_data(
            mock_session,
            [libraries[0]],
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G2", libraries[0], 2.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={
                "genes": ["G1", "G2"],
                "conditions": ["Leaf Control"],
                "scale": "none",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["conditions"] == ["Leaf Control"]
        assert data["matrix"] == [[10.0], [2.0]]

    async def test_duplicate_genes_deduplicated(self, client, mock_session, libraries):
        """Duplicate gene ids are returned once (row order preserved)."""
        _setup_data(
            mock_session,
            libraries,
            [_make_expr("G1", libraries[0], 10.0)],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1", "G1", "G2"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["genes"] == ["G1", "G2"]
        assert len(data["matrix"]) == 2


# ---------------------------------------------------------------------------
# Missing genes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMissingGenes:
    async def test_missing_gene_gets_null_row(
        self, client, mock_session, libraries
    ):
        """A gene without expression records yields a null row + annotation."""
        _setup_data(
            mock_session,
            libraries,
            [_make_expr("G1", libraries[0], 10.0)],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1", "G2"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["missing_genes"] == ["G2"]
        assert data["matrix"] == [[10.0, None], [None, None]]
        # value_range covers only non-null cells
        assert data["value_range"] == [10.0, 10.0]

    async def test_all_missing_value_range_none(self, client, mock_session, libraries):
        """All cells missing -> value_range is [None, None]."""
        _setup_data(mock_session, libraries, [])
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": ["G1"]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matrix"] == [[None, None]]
        assert data["value_range"] == [None, None]
        assert data["missing_genes"] == ["G1"]


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClustering:
    async def test_mean_sort_fallback(
        self, client, mock_session, libraries, monkeypatch
    ):
        """Without SciPy, rows are sorted by mean expression (annotated)."""
        monkeypatch.setattr(exppattern_service, "pdist", None)
        monkeypatch.setattr(exppattern_service, "linkage", None)
        monkeypatch.setattr(exppattern_service, "leaves_list", None)
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 10.0),
                _make_expr("G1", libraries[1], 20.0),
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G2", libraries[1], 3.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1", "G2"], "scale": "none", "cluster_rows": True},
        )
        assert response.status_code == 200
        data = response.json()
        # G1 mean=15 > G2 mean=2 -> G1 first
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "mean_sort"
        assert data["matrix"][0] == [10.0, 20.0]

    async def test_hierarchical_clustering(
        self, client, mock_session, libraries, monkeypatch
    ):
        """With SciPy available, linkage+leaves_list drive the row order."""
        fake_linkage = MagicMock(return_value=object())
        fake_leaves = MagicMock(return_value=[1, 0])
        fake_pdist = MagicMock(return_value=[1.0])
        monkeypatch.setattr(exppattern_service, "pdist", fake_pdist)
        monkeypatch.setattr(exppattern_service, "linkage", fake_linkage)
        monkeypatch.setattr(exppattern_service, "leaves_list", fake_leaves)
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G1", libraries[0], 1.0),
                _make_expr("G1", libraries[1], 3.0),
                _make_expr("G2", libraries[0], 10.0),
                _make_expr("G2", libraries[1], 20.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1", "G2"], "cluster_rows": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["clustering"] == "hierarchical"
        assert data["row_order"] == [1, 0]
        # distance computed on the imputed matrix (no NaN)
        assert fake_pdist.call_args.args[0] == [[-1.0, 1.0], [-1.0, 1.0]]

    async def test_no_clustering_when_disabled(
        self, client, mock_session, libraries
    ):
        """cluster_rows=false keeps input order and reports clustering=input."""
        _setup_data(
            mock_session,
            libraries,
            [
                _make_expr("G2", libraries[0], 1.0),
                _make_expr("G1", libraries[0], 10.0),
            ],
        )
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G2", "G1"], "scale": "none"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["row_order"] == [0, 1]
        assert data["clustering"] == "input"


# ---------------------------------------------------------------------------
# Scale limits (422)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestScaleLimits:
    async def test_too_many_genes_422(self, client, mock_session):
        """More than 50 genes is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": [f"G{i}" for i in range(51)]},
        )
        assert response.status_code == 422
        assert "error" in response.json()

    async def test_too_many_conditions_422(self, client, mock_session):
        """More than 200 conditions is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1"], "conditions": [f"L{i}" for i in range(201)]},
        )
        assert response.status_code == 422
        assert "error" in response.json()

    async def test_db_resolved_conditions_over_limit_422(
        self, client, mock_session
    ):
        """>200 libraries resolved from DB (no conditions given) -> 422."""
        libs = [_make_lib(i, f"L{i}") for i in range(201)]
        _setup_data(mock_session, libs, [])
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": ["G1"]}
        )
        assert response.status_code == 422
        data = response.json()
        assert data["error"]["code"] == "validation_error"

    async def test_empty_genes_422(self, client, mock_session):
        """Empty or blank-only genes list is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": []}
        )
        assert response.status_code == 422
        response = await client.post(
            "/api/v1/tools/exppattern", json={"genes": ["  "]}
        )
        assert response.status_code == 422

    async def test_invalid_scale_422(self, client, mock_session):
        """Unknown scale value is rejected with 422."""
        response = await client.post(
            "/api/v1/tools/exppattern",
            json={"genes": ["G1"], "scale": "log2"},
        )
        assert response.status_code == 422

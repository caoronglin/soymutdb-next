"""Tests for expression API endpoints (``/api/v1/expression/*``).

Covers: libraries list, library detail, gene expression, search.
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
    http_exception_handler,
    soy_mut_db_exception_handler,
    validation_exception_handler,
)

# ---------------------------------------------------------------------------
# Helper: create a mock DB session with sensible defaults
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return an ``AsyncMock``-backed session that returns empty results.

    All query methods (``execute``, ``scalar``, ``add``, ``commit``) are
    ``AsyncMock`` instances so they can be ``await``\ ed.
    """
    session = MagicMock()
    # Use AsyncMock for methods that are awaited
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    # Default return values for common query patterns
    default_result = MagicMock()
    default_result.scalars.return_value.all.return_value = []
    default_result.scalars.return_value.first.return_value = None
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    session.execute.return_value = default_result
    session.scalar.return_value = 0

    return session


def _make_exec_result(scalars_list=None, scalar_one=None, scalar_val=0):
    """Build a mock execution result with the given data."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_list or []
    r.scalar_one_or_none.return_value = scalar_one
    r.scalar.return_value = scalar_val
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_library():
    """Return a mock ExpressionLibrary dict-like object."""
    lib = MagicMock()
    lib.id = 1
    lib.sample_id = "SMPL001"
    lib.library_name = "Leaf Control Library"
    lib.tissue = "leaf"
    lib.treatment = "control"
    lib.developmental_stage = "V3"
    lib.study_ref = "PRJNA000001"
    lib.source = "RNA-Seq"
    lib.assembly_id = 1
    lib.extra_metadata = {"cultivar": "Williams 82"}
    return lib


@pytest.fixture
def mock_expression_data(mock_library):
    """Return a mock ExpressionData dict-like object."""
    ed = MagicMock()
    ed.id = 1
    ed.gene_id = "Glyma.01G000100"
    ed.library_id = 1
    ed.fpkm = 12.5
    ed.tpm = 25.0
    ed.raw_count = 150
    ed.library = mock_library
    return ed


@pytest.fixture
def mock_session():
    """Return a clean mock DB session for expression endpoints."""
    return _make_mock_session()


@pytest.fixture
async def client(mock_session):
    """Create a test client with the given *mock_session* injected.

    Tests access the mock session via the ``mock_session`` fixture to
    configure per-test return values.
    """
    from app.api.v1.expression import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    # Register exception handlers so NotFoundError etc. return proper JSON
    app.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/expression/libraries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListLibraries:
    """Tests for ``GET /api/v1/expression/libraries``."""

    async def test_list_libraries_empty(self, client, mock_session):
        """Listing libraries with no data returns empty list."""
        response = await client.get("/api/v1/expression/libraries")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_list_libraries_with_results(
        self, client, mock_session, mock_library
    ):
        """Listing libraries returns paginated results."""
        mock_session.scalar.return_value = 1  # total count

        # First execute: libraries list, Second: batch count rows
        lib_result = _make_exec_result(scalars_list=[mock_library])
        count_result = MagicMock()
        count_result.all.return_value = [(1, 5)]  # (library_id, count)
        mock_session.execute.side_effect = [lib_result, count_result]

        response = await client.get("/api/v1/expression/libraries")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["library_name"] == "Leaf Control Library"
        assert data["items"][0]["expression_data_count"] == 5

    async def test_list_libraries_filters(
        self, client, mock_session, mock_library
    ):
        """Filters (tissue, treatment) are passed through."""
        mock_session.scalar.return_value = 1
        lib_result = _make_exec_result(scalars_list=[mock_library])
        count_result = _make_exec_result(scalar_val=0)
        mock_session.execute.side_effect = [lib_result, count_result]

        response = await client.get(
            "/api/v1/expression/libraries?tissue=leaf&treatment=control"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1

    async def test_list_libraries_pagination(self, client, mock_session):
        """Pagination parameters are respected."""
        response = await client.get(
            "/api/v1/expression/libraries?page=2&page_size=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    async def test_list_libraries_invalid_page(self, client, mock_session):
        """Negative page returns 422."""
        response = await client.get("/api/v1/expression/libraries?page=-1")
        assert response.status_code == 422

    async def test_list_libraries_invalid_page_size(self, client, mock_session):
        """page_size over 200 returns 422."""
        response = await client.get("/api/v1/expression/libraries?page_size=500")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/expression/libraries/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetLibrary:
    """Tests for ``GET /api/v1/expression/libraries/{id}``."""

    async def test_get_library_found(self, client, mock_session, mock_library):
        """Existing library returns full detail."""
        find_result = _make_exec_result(scalar_one=mock_library)
        count_result = _make_exec_result(scalar_val=3)
        mock_session.execute.side_effect = [find_result, count_result]

        response = await client.get("/api/v1/expression/libraries/1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["library_name"] == "Leaf Control Library"
        assert data["expression_data_count"] == 3

    async def test_get_library_not_found(self, client, mock_session):
        """Missing library returns 404."""
        response = await client.get("/api/v1/expression/libraries/999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data

    async def test_get_library_invalid_id(self, client, mock_session):
        """Non-integer library ID returns 422."""
        response = await client.get("/api/v1/expression/libraries/abc")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/expression/genes/{gene_id}/expression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetGeneExpression:
    """Tests for ``GET /api/v1/expression/genes/{gene_id}/expression``."""

    async def test_gene_expression_found(
        self, client, mock_session, mock_expression_data
    ):
        """Existing gene returns expression data."""
        data_result = _make_exec_result(scalars_list=[mock_expression_data])
        mock_session.execute.return_value = data_result

        response = await client.get(
            "/api/v1/expression/genes/Glyma.01G000100/expression"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["gene_id"] == "Glyma.01G000100"
        assert len(data["expressions"]) == 1
        assert data["expressions"][0]["fpkm"] == 12.5
        assert data["expressions"][0]["tpm"] == 25.0

    async def test_gene_expression_empty(self, client, mock_session):
        """Gene with no expression data returns empty list."""
        response = await client.get(
            "/api/v1/expression/genes/Glyma.99G999999/expression"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["gene_id"] == "Glyma.99G999999"
        assert data["expressions"] == []

    async def test_gene_expression_filters(
        self, client, mock_session, mock_expression_data
    ):
        """Filters (tissue, treatment, fpkm range) are applied."""
        data_result = _make_exec_result(scalars_list=[mock_expression_data])
        mock_session.execute.return_value = data_result

        response = await client.get(
            "/api/v1/expression/genes/Glyma.01G000100/expression"
            "?tissue=leaf&treatment=control&min_fpkm=10&max_fpkm=100"
        )
        assert response.status_code == 200
        assert len(response.json()["expressions"]) == 1


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/expression/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchExpression:
    """Tests for ``GET /api/v1/expression/search``."""

    async def test_search_empty(self, client, mock_session):
        """Search with no matches returns empty list."""
        response = await client.get("/api/v1/expression/search")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_with_results(
        self, client, mock_session, mock_expression_data
    ):
        """Search returns matched expression data rows."""
        mock_session.scalar.return_value = 1  # total
        data_result = _make_exec_result(scalars_list=[mock_expression_data])
        mock_session.execute.return_value = data_result

        response = await client.get(
            "/api/v1/expression/search?gene_id=Glyma.01G000100"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["gene_id"] == "Glyma.01G000100"
        assert data["items"][0]["fpkm"] == 12.5

    async def test_search_with_filters(
        self, client, mock_session, mock_expression_data
    ):
        """Search filters (tissue, treatment, fpkm) are passed through."""
        mock_session.scalar.return_value = 1
        data_result = _make_exec_result(scalars_list=[mock_expression_data])
        mock_session.execute.return_value = data_result

        response = await client.get(
            "/api/v1/expression/search"
            "?tissue=leaf&treatment=control&min_fpkm=10&max_fpkm=100"
        )
        assert response.status_code == 200

    async def test_search_pagination(self, client, mock_session):
        """Search pagination parameters are respected."""
        response = await client.get(
            "/api/v1/expression/search?page=1&page_size=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_search_invalid_min_fpkm(self, client, mock_session):
        """Negative min_fpkm returns 422."""
        response = await client.get(
            "/api/v1/expression/search?min_fpkm=-1"
        )
        assert response.status_code == 422

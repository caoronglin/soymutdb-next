"""Tests for homolog API endpoints (``/api/v1/homologs/*``).

Covers: gene homologs list, homologs search.
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

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return a mock DB session with ``AsyncMock`` query methods."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    default_result = MagicMock()
    default_result.scalars.return_value.all.return_value = []
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    session.execute.return_value = default_result
    session.scalar.return_value = 0
    return session


def _make_gene(accession: str, gene_pk: int = 501):
    """A Gene row as resolved by ``find_by_accessions``.

    Genes are keyed by ``gene_pk`` (surrogate); ``accession`` is the
    assembly-scoped public identity. The endpoint resolves the accession
    first, so every gene-scoped test needs this row in its query stream.
    """
    gene = MagicMock()
    gene.gene_pk = gene_pk
    gene.accession = accession
    gene.assembly_id = 1
    return gene


def _result(rows):
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _gene_then(rows, accession="Glyma.01G000100", gene_pk=501):
    """Sequence the two executes of the gene-scoped endpoint.

    Order: accession -> gene resolution, then the homolog query.
    """
    return [_result([_make_gene(accession, gene_pk)]), _result(rows)]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_homolog():
    """Return a mock GeneHomolog dict-like object.

    ``GeneHomolog.gene_id`` is the surrogate ``gene_pk``; the response exposes
    the gene's assembly-scoped ``accession`` via the ``gene`` relationship.
    """
    h = MagicMock()
    h.id = 1
    h.gene_id = 501
    h.gene.accession = "Glyma.01G000100"
    h.homolog_species = "Arabidopsis thaliana"
    h.homolog_gene_id = "AT1G01010"
    h.homolog_type = "ortholog"
    h.source = "Ensembl"
    return h


@pytest.fixture
def mock_session():
    """Return a clean mock DB session for homolog endpoints."""
    return _make_mock_session()


@pytest.fixture
async def client(mock_session):
    """Create a test client with the given *mock_session* injected.

    Requires a valid ``gene_id`` path parameter — the homolog router expects
    the path ``/genes/{gene_id}/homologs``, NOT a top-level route.

    The test app includes both the homolog router (for search) and supports
    the nested ``/genes/{gene_id}/homologs`` URL.
    """
    from app.api.v1.homolog import router as homolog_router

    app = FastAPI()
    app.include_router(homolog_router, prefix="/api/v1")

    # Register exception handlers
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
# Tests: GET /api/v1/genes/{gene_id}/homologs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetGeneHomologs:
    """Tests for ``GET /api/v1/genes/{gene_id}/homologs``."""

    async def test_get_homologs_found(self, client, mock_session, mock_homolog):
        """Existing gene with homologs returns homolog list."""
        mock_session.execute.side_effect = _gene_then([mock_homolog])

        response = await client.get(
            "/api/v1/homologs/genes/Glyma.01G000100/homologs"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["gene_id"] == "Glyma.01G000100"
        assert len(data["homologs"]) == 1
        assert data["homologs"][0]["homolog_species"] == "Arabidopsis thaliana"
        assert data["homologs"][0]["homolog_type"] == "ortholog"

    async def test_get_homologs_empty(self, client, mock_session):
        """Gene with no homologs returns empty list."""
        mock_session.execute.side_effect = _gene_then(
            [], accession="Glyma.99G999999", gene_pk=999
        )
        response = await client.get(
            "/api/v1/homologs/genes/Glyma.99G999999/homologs"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["gene_id"] == "Glyma.99G999999"
        assert data["homologs"] == []

    async def test_get_homologs_multiple(self, client, mock_session):
        """Multiple homologs for a gene are all returned."""
        h1 = MagicMock()
        h1.homolog_species = "Arabidopsis thaliana"
        h1.homolog_gene_id = "AT1G01010"
        h1.homolog_type = "ortholog"
        h1.source = "Ensembl"

        h2 = MagicMock()
        h2.homolog_species = "Glycine max"
        h2.homolog_gene_id = "Glyma.02G000200"
        h2.homolog_type = "paralog"
        h2.source = "Ensembl"

        mock_session.execute.side_effect = _gene_then([h1, h2])

        response = await client.get(
            "/api/v1/homologs/genes/Glyma.01G000100/homologs"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["homologs"]) == 2

    async def test_get_homologs_uses_bounded_keyset_page(
        self, client, mock_session, mock_homolog
    ):
        next_homolog = MagicMock()
        next_homolog.id = 2
        next_homolog.homolog_species = "Glycine max"
        next_homolog.homolog_gene_id = "Glyma.02G000200"
        next_homolog.homolog_type = "paralog"
        next_homolog.source = "Ensembl"
        mock_session.execute.side_effect = _gene_then(
            [mock_homolog, next_homolog]
        )

        response = await client.get(
            "/api/v1/homologs/genes/Glyma.01G000100/homologs?limit=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["homologs"]) == 1
        assert data["has_more"] is True
        assert data["next_cursor"] == "1"

    async def test_get_homologs_unknown_gene_is_404(self, client, mock_session):
        """An accession that resolves to no gene must not disclose homologs."""
        mock_session.execute.side_effect = [_result([])]
        response = await client.get(
            "/api/v1/homologs/genes/Glyma.77G777777/homologs"
        )
        assert response.status_code == 404

    async def test_get_homologs_ambiguous_assembly_is_rejected(
        self, client, mock_session
    ):
        """The same accession in two assemblies must be disambiguated, not picked."""
        mock_session.execute.side_effect = [
            _result([_make_gene("Glyma.01G000100", 501), _make_gene("Glyma.01G000100", 601)])
        ]
        response = await client.get(
            "/api/v1/homologs/genes/Glyma.01G000100/homologs"
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"]["code"] == "ambiguous_assembly"

    async def test_get_homologs_rejects_unbounded_limit(self, client):
        response = await client.get(
            "/api/v1/homologs/genes/Glyma.01G000100/homologs?limit=201"
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/homologs/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchHomologs:
    """Tests for ``GET /api/v1/homologs/search``."""

    async def test_search_empty(self, client, mock_session):
        """Search with no matching data returns empty list."""
        response = await client.get("/api/v1/homologs/search")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_search_by_gene_id(self, client, mock_session, mock_homolog):
        """Search by gene_id returns matching homologs."""
        mock_session.scalar.return_value = 1
        mock_session.execute.side_effect = _gene_then([mock_homolog])

        response = await client.get(
            "/api/v1/homologs/search?gene_id=Glyma.01G000100"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["gene_id"] == "Glyma.01G000100"
        assert data["items"][0]["homolog_species"] == "Arabidopsis thaliana"

    async def test_search_by_species(self, client, mock_session, mock_homolog):
        """Search by homolog_species returns filtered results."""
        mock_session.scalar.return_value = 1
        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_homolog]
        mock_session.execute.return_value = result

        response = await client.get(
            "/api/v1/homologs/search?homolog_species=Arabidopsis+thaliana"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1

    async def test_search_by_type(self, client, mock_session, mock_homolog):
        """Search by homolog_type returns filtered results."""
        mock_session.scalar.return_value = 1
        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_homolog]
        mock_session.execute.return_value = result

        response = await client.get(
            "/api/v1/homologs/search?homolog_type=ortholog"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["homolog_type"] == "ortholog"

    async def test_search_combined_filters(
        self, client, mock_session, mock_homolog
    ):
        """Multiple search filters are applied together."""
        mock_session.scalar.return_value = 1
        mock_session.execute.side_effect = _gene_then([mock_homolog])

        response = await client.get(
            "/api/v1/homologs/search"
            "?gene_id=Glyma.01G000100"
            "&homolog_species=Arabidopsis+thaliana"
            "&homolog_type=ortholog"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1

    async def test_search_pagination(self, client, mock_session):
        """Search pagination parameters are respected."""
        response = await client.get(
            "/api/v1/homologs/search?page=2&page_size=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert data["page_size"] == 10

    async def test_search_invalid_page_size(self, client, mock_session):
        """page_size over 200 returns 422."""
        response = await client.get("/api/v1/homologs/search?page_size=500")
        assert response.status_code == 422

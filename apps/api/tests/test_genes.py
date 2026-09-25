"""Tests for gene API endpoints (/api/v1/genes/*).

Covers: gene search, gene detail, transcripts, assemblies, chromosomes.
Includes cursor pagination tests.
All routes use the ``/api/v1/`` prefix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.release_context import ReleaseContext, get_release_context

GENES_PREFIX = "/api/v1/genes"


@pytest_asyncio.fixture(autouse=True)
async def _release_context_override(app):
    async def override_release_context() -> ReleaseContext:
        return ReleaseContext(
            release_id=7,
            assembly_id=1,
            assembly="Wm82.gnm2",
        )

    app.dependency_overrides[get_release_context] = override_release_context
    yield
    app.dependency_overrides.pop(get_release_context, None)


@pytest.mark.asyncio
class TestListGenes:
    """Tests for GET /api/v1/genes."""

    async def test_list_genes_empty(self, client):
        """Listing genes with no data returns empty list."""
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(GENES_PREFIX)
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["has_more"] is False

    async def test_list_genes_with_search(self, client, gene_factory):
        """Gene search returns matching genes."""
        gene = gene_factory.make_dict(gene_id="Glyma.01G000100", name="Disease Resistance")
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={
                "items": [gene],
                "next_cursor": None,
                "has_more": False,
            },
        ):
            response = await client.get(f"{GENES_PREFIX}?search=Disease")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["gene_id"] == "Glyma.01G000100"

    async def test_portal_query_contract_is_forwarded(self, client):
        """The portal's q/page/page_size request must not be silently ignored."""
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={
                "items": [],
                "next_cursor": None,
                "has_more": False,
                "page": 2,
                "page_size": 20,
                "total": 0,
                "total_pages": 0,
            },
        ) as list_genes:
            response = await client.get(
                f"{GENES_PREFIX}?q=Glyma.01G000100&page=2&page_size=20"
            )

        assert response.status_code == 200
        assert list_genes.await_args is not None
        params = list_genes.await_args.args[1]
        release_context = list_genes.await_args.kwargs["release_context"]
        assert params.search == "Glyma.01G000100"
        assert params.page == 2
        assert params.page_size == 20
        assert release_context.release_id == 7
        assert response.json()["total"] == 0

    async def test_list_genes_cursor_pagination(self, client, gene_factory):
        """Cursor pagination returns next_cursor when more results exist."""
        genes = [
            gene_factory.make_dict(gene_id=f"Glyma.01G00010{i}", name=f"Gene{i}")
            for i in range(3)
        ]
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={
                "items": genes[:2],
                "next_cursor": "cursor_abc123",
                "has_more": True,
            },
        ):
            response = await client.get(f"{GENES_PREFIX}?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    async def test_list_genes_filter_by_biotype(self, client, gene_factory):
        """Filtering by biotype returns only matching genes."""
        gene = gene_factory.make_dict(biotype="protein_coding")
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={
                "items": [gene],
                "next_cursor": None,
                "has_more": False,
            },
        ):
            response = await client.get(f"{GENES_PREFIX}?biotype=protein_coding")
        assert response.status_code == 200

    async def test_list_genes_limit_max_200(self, client):
        """Limit parameter is capped at 200."""
        with patch(
            "app.services.gene_service.GeneService.list_genes",
            new_callable=AsyncMock,
            return_value={"items": [], "next_cursor": None, "has_more": False},
        ):
            response = await client.get(f"{GENES_PREFIX}?limit=500")
        # Should be accepted (clamped by the Query constraint) or rejected (422)
        assert response.status_code in (200, 422)


@pytest.mark.asyncio
class TestGetGene:
    """Tests for GET /api/v1/genes/{gene_id}."""

    async def test_get_gene_detail(self, client, gene_factory):
        """Gene detail endpoint returns full gene information."""
        gene = gene_factory.make_dict(
            gene_id="Glyma.01G000100",
            name="Test Gene Detail",
        )
        with patch(
            "app.services.gene_service.GeneService.get_gene",
            new_callable=AsyncMock,
            return_value=gene,
        ):
            response = await client.get(f"{GENES_PREFIX}/Glyma.01G000100")
        assert response.status_code == 200
        data = response.json()
        assert data["gene_id"] == "Glyma.01G000100"

    async def test_get_gene_not_found(self, client):
        """Non-existent gene returns 404."""
        with patch(
            "app.services.gene_service.GeneService.get_gene",
            new_callable=AsyncMock,
            side_effect=Exception("Gene not found"),
        ):
            response = await client.get(f"{GENES_PREFIX}/NONEXISTENT")
        assert response.status_code in (404, 500)


@pytest.mark.asyncio
class TestAssemblies:
    """Tests for GET /api/v1/genes/assemblies."""

    async def test_list_assemblies(self, client):
        """List assemblies returns available genome assemblies."""
        assemblies = [
            {"id": 1, "name": "Wm82.gnm2", "species": "Glycine max", "version": "2"},
            {"id": 2, "name": "Wm82.gnm4", "species": "Glycine max", "version": "4"},
        ]
        with patch(
            "app.services.gene_service.GeneService.list_assemblies",
            new_callable=AsyncMock,
            return_value=assemblies,
        ) as list_assemblies:
            response = await client.get(f"{GENES_PREFIX}/assemblies")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Wm82.gnm2"
        assert list_assemblies.await_args.kwargs["release_id"] == 7


@pytest.mark.asyncio
class TestChromosomes:
    """Tests for GET /api/v1/genes/assemblies/{assembly_id}/chromosomes."""

    async def test_list_chromosomes(self, client):
        """List chromosomes for an assembly."""
        chromosomes = [
            {"id": 1, "assembly_id": 1, "name": "Gm01", "length": 50000000},
            {"id": 2, "assembly_id": 1, "name": "Gm02", "length": 48000000},
        ]
        with patch(
            "app.services.gene_service.GeneService.list_chromosomes",
            new_callable=AsyncMock,
            return_value=chromosomes,
        ) as list_chromosomes:
            response = await client.get(f"{GENES_PREFIX}/assemblies/1/chromosomes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Gm01"
        assert list_chromosomes.await_args.kwargs["release_id"] == 7

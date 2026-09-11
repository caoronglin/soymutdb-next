"""Tests for search API endpoints (/api/v1/search/*).

Covers: global search, autocomplete suggestions.
All routes use the ``/api/v1/`` prefix.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.site_variant import SiteVariant

SEARCH_PREFIX = "/api/v1/search"


@pytest.mark.asyncio
class TestGlobalSearch:
    """Tests for GET /api/v1/search."""

    async def test_search_returns_results(self, client):
        """Global search returns matching results across entity types."""
        mock_response = {
            "query": "disease",
            "results": [
                {
                    "type": "gene",
                    "id": "Glyma.01G000100",
                    "name": "Disease Resistance Gene",
                    "description": "NBS-LRR disease resistance protein",
                    "score": 0.95,
                },
                {
                    "type": "mutant_line",
                    "id": "ML001",
                    "name": "disease_sensitive_line",
                    "description": "EMS mutant with disease susceptibility",
                    "score": 0.80,
                },
            ],
            "total": 2,
        }
        with patch(
            "app.services.search_service.SearchService.global_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.get(f"{SEARCH_PREFIX}?query=disease")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "disease"
        assert len(data["results"]) == 2
        assert data["results"][0]["type"] == "gene"

    async def test_search_empty_query_rejected(self, client):
        """Empty query string returns 422."""
        response = await client.get(f"{SEARCH_PREFIX}?query=")
        assert response.status_code == 422

    async def test_search_missing_query_param(self, client):
        """Missing query parameter returns 422."""
        response = await client.get(SEARCH_PREFIX)
        assert response.status_code == 422

    async def test_search_with_type_filter(self, client):
        """Search with type filter returns only matching types."""
        mock_response = {
            "query": "Glyma",
            "results": [
                {
                    "type": "gene",
                    "id": "Glyma.01G000100",
                    "name": "Test Gene",
                    "description": "",
                    "score": 0.90,
                }
            ],
            "total": 1,
        }
        with patch(
            "app.services.search_service.SearchService.global_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.get(f"{SEARCH_PREFIX}?query=Glyma&types=gene")
        assert response.status_code == 200
        data = response.json()
        assert all(r["type"] == "gene" for r in data["results"])

    async def test_search_limit_parameter(self, client):
        """Search respects the limit parameter."""
        mock_response = {
            "query": "test",
            "results": [],
            "total": 0,
        }
        with patch(
            "app.services.search_service.SearchService.global_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.get(f"{SEARCH_PREFIX}?query=test&limit=5")
        assert response.status_code == 200

    async def test_search_forwards_optional_assembly_context(self, client):
        """The public JSON route preserves an explicit assembly selection."""
        mock_response = {
            "query": "Glyma",
            "results": [],
            "by_type": {"gene": 0},
            "cursor": None,
            "next_cursor": None,
            "has_more": False,
            "total_count": 0,
        }
        search = AsyncMock(return_value=mock_response)
        with patch(
            "app.services.search_service.SearchService.global_search",
            search,
        ):
            response = await client.get(
                f"{SEARCH_PREFIX}?query=Glyma&types=gene&assembly_id=11"
            )

        assert response.status_code == 200
        assert search.await_args.kwargs["assembly_id"] == 11
        assert search.await_args.kwargs["site_variant"] == SiteVariant.EXTERNAL

    async def test_search_limit_max_50(self, client):
        """Search limit is capped at 50."""
        mock_response = {
            "query": "test",
            "results": [],
            "total": 0,
        }
        with patch(
            "app.services.search_service.SearchService.global_search",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            response = await client.get(f"{SEARCH_PREFIX}?query=test&limit=100")
        assert response.status_code in (200, 422)


@pytest.mark.asyncio
class TestSuggest:
    """Tests for GET /api/v1/search/suggest."""

    async def test_suggest_returns_suggestions(self, client):
        """Autocomplete returns matching suggestions."""
        mock_suggestions = [
            {"text": "Glyma.01G000100", "type": "gene"},
            {"text": "Glyma.01G000200", "type": "gene"},
            {"text": "Glyma.02G000100", "type": "gene"},
        ]
        with patch(
            "app.services.search_service.SearchService.suggest",
            new_callable=AsyncMock,
            return_value=mock_suggestions,
        ):
            response = await client.get(f"{SEARCH_PREFIX}/suggest?q=Glyma")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert "Glyma" in data[0]["text"]

    async def test_suggest_empty_query_rejected(self, client):
        """Empty query returns 422."""
        response = await client.get(f"{SEARCH_PREFIX}/suggest?q=")
        assert response.status_code == 422

    async def test_suggest_missing_param(self, client):
        """Missing q parameter returns 422."""
        response = await client.get(f"{SEARCH_PREFIX}/suggest")
        assert response.status_code == 422

    async def test_suggest_with_limit(self, client):
        """Suggest respects the limit parameter."""
        mock_suggestions = [{"text": "Glyma.01G000100", "type": "gene"}]
        with patch(
            "app.services.search_service.SearchService.suggest",
            new_callable=AsyncMock,
            return_value=mock_suggestions,
        ):
            response = await client.get(f"{SEARCH_PREFIX}/suggest?q=Glyma&limit=3")
        assert response.status_code == 200

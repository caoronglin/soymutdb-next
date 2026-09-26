from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import get_db
from app.search import ExternalSearchResponse, SearchSource, SourceResult, SourceStatus


def test_search_openapi_uses_canonical_parameters():
    operation = app.openapi()["paths"]["/api/v1/search"]["get"]
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert {"query", "types", "sources", "cursor", "limit"} <= names
    assert "page" not in names
    assert "page_size" not in names
    assert {"by_type", "next_cursor", "has_more", "total_count"} <= set(
        app.openapi()["components"]["schemas"]["GlobalSearchResponse"]["properties"]
    )


@pytest.mark.asyncio
async def test_external_json_preserves_source_degradation(monkeypatch):
    response = ExternalSearchResponse(
        query="Glyma",
        sources=[
            SourceResult(SearchSource.NCBI, SourceStatus.OK, hits=[]),
            SourceResult(
                SearchSource.UNIPROT,
                SourceStatus.CIRCUIT_OPEN,
                error_message="open",
            ),
        ],
    )
    aggregator = AsyncMock()
    aggregator.search.return_value = response
    monkeypatch.setattr(
        "app.api.v1.search.ExternalSearchAggregator",
        lambda redis, **scope: aggregator,
    )
    monkeypatch.setattr("app.api.v1.search.get_redis", lambda: object())
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            result = await client.get(
                "/api/v1/search",
                params={"query": "Glyma", "sources": "ncbi,uniprot", "format": "json"},
            )
    finally:
        app.dependency_overrides.clear()

    assert result.status_code == 200
    assert result.json()["sources"][1]["status"] == "circuit_open"
    assert result.json()["sources"][1]["error"] == "open"
    db.scalar.assert_awaited_once()
    aggregator.search.assert_awaited_once_with(
        "Glyma",
        sources=[SearchSource.NCBI, SearchSource.UNIPROT],
        limit_per_source=10,
    )

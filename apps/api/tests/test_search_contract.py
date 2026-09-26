import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.api.v1.search import global_search as global_search_endpoint
from app.core.exceptions import ServiceUnavailableError
from app.core.site_variant import SiteVariant
from app.schemas.search import GlobalSearchResponse, SearchResultItem, SearchResultType
from app.services.release_context import ReleaseContext
from app.services.search_service import SearchService, _contains_pattern


class _EmptyRows:
    def all(self) -> list[Any]:
        return []


class _CaptureDb:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyRows()


def _postgresql_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()


def test_search_response_has_url_by_type_and_cursor_fields():
    response = GlobalSearchResponse(
        query="G1",
        results=[
            SearchResultItem(
                type=SearchResultType.GENE,
                id="G1",
                url="/genes/G1",
            )
        ],
        by_type={"gene": 1},
        cursor=None,
        next_cursor=None,
        has_more=False,
        total_count=1,
    )

    assert response.results[0].url == "/genes/G1"
    assert response.by_type == {"gene": 1}
    assert response.total_count == 1


def test_gene_result_url_uses_the_real_route_and_preserves_assembly():
    assert SearchService._frontend_url(
        SearchResultType.GENE,
        "Glyma.01G000100",
        assembly_id=11,
    ) == "/genes/Glyma.01G000100?assembly=11"


def test_literal_like_patterns_preserve_match_mode_and_escape_wildcards():
    assert _contains_pattern("100%_\\") == r"%100\%\_\\%"


def test_global_search_signature_is_canonical():
    assert list(inspect.signature(SearchService.global_search).parameters) == [
        "self",
        "db",
        "query",
        "types",
        "cursor",
        "limit",
        "assembly_id",
        "site_variant",
    ]


def test_search_route_accepts_optional_assembly_id():
    assert "assembly_id" in inspect.signature(global_search_endpoint).parameters


@pytest.mark.asyncio
async def test_search_cache_is_bound_to_resolved_release_and_assembly():
    context = ReleaseContext(release_id=7, assembly_id=11, assembly="Wm82.v5")
    db = object()
    captured: dict[str, Any] = {}

    async def fake_get_or_set(name, ttl, loader, *, params=None):
        del loader
        captured.update({"name": name, "ttl": ttl, "params": params})
        return {
            "query": "Glyma",
            "results": [],
            "by_type": {"gene": 0},
            "cursor": None,
            "next_cursor": None,
            "has_more": False,
            "total_count": 0,
        }

    resolve = AsyncMock(return_value=context)
    with (
        patch("app.services.search_service.resolve_release_context", resolve),
        patch("app.services.search_service.get_or_set", fake_get_or_set),
    ):
        response = await SearchService().global_search(
            db,
            "Glyma",
            types=[SearchResultType.GENE],
        )

    resolve.assert_awaited_once_with(db)
    assert response.results == []
    assert captured["name"] == "search:global"
    assert captured["params"]["site_variant"] == "external"
    assert captured["params"]["release_id"] == 7
    assert captured["params"]["assembly_id"] is None


@pytest.mark.asyncio
async def test_search_without_a_published_release_fails_before_cache_lookup():
    unavailable = ServiceUnavailableError("No active data release is available")
    cache = AsyncMock()
    with (
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(side_effect=unavailable),
        ),
        patch("app.services.search_service.get_or_set", cache),
        pytest.raises(ServiceUnavailableError),
    ):
        await SearchService().global_search(
            object(),
            "Glyma",
            types=[SearchResultType.GENE],
        )

    cache.assert_not_awaited()


@pytest.mark.asyncio
async def test_gene_search_sql_is_bound_to_release_and_assembly():
    db = _CaptureDb()

    await SearchService()._search_genes(
        db,
        "%Glyma%",
        "%Glyma%",
        10,
        release_id=7,
        assembly_id=11,
    )

    sql = _postgresql_sql(db.statement)
    assert "join assemblies on assemblies.id = genes.assembly_id" in sql
    assert "assemblies.release_id = 7" in sql
    assert "genes.assembly_id = 11" in sql


@pytest.mark.asyncio
async def test_mutant_search_sql_excludes_private_deleted_and_other_release_rows():
    db = _CaptureDb()

    await SearchService()._search_mutant_lines(
        db,
        "%line%",
        "%line%",
        10,
        release_id=7,
        site_variant=SiteVariant.EXTERNAL,
    )

    sql = _postgresql_sql(db.statement)
    assert "mutant_lines.is_public is true" in sql
    assert "mutant_lines.is_deleted is false" in sql
    assert "mutant_lines.release_id = 7" in sql


@pytest.mark.asyncio
async def test_external_search_does_not_expose_mutant_persistence_ids():
    context = ReleaseContext(release_id=7, assembly_id=11, assembly="Wm82.v5")
    service = SearchService()
    mutant_search = AsyncMock()

    async def uncached(name, ttl, loader, *, params=None):
        del name, ttl, params
        return await loader()

    with (
        patch.object(service, "_search_mutant_lines", mutant_search),
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(return_value=context),
        ),
        patch("app.services.search_service.get_or_set", uncached),
    ):
        response = await service.global_search(
            object(),
            "line",
            types=[SearchResultType.MUTANT_LINE],
            site_variant=SiteVariant.EXTERNAL,
        )

    mutant_search.assert_awaited_once()
    assert response.results == []


@pytest.mark.asyncio
async def test_internal_search_sets_private_no_store_header():
    """R06: internal search response must carry private, no-store cache policy."""
    from fastapi import Response
    from app.api.v1.search import internal_search

    db = _CaptureDb()
    db.commit = AsyncMock()  # type: ignore[method-assign]
    db.add = lambda *_a, **_k: None
    response = Response()

    fake_context = type("FakeContext", (), {"release_id": 7})()
    with (
        patch("app.api.v1.search.resolve_release_context", AsyncMock(return_value=fake_context)),
        patch("app.api.v1.search.AuditLog", autospec=True),
    ):
        with patch(
            "app.services.search_service.SearchService.internal_search",
            AsyncMock(return_value=type("FakeResult", (), {"total_count": 0})()),
        ):
            await internal_search(
                response=response,
                db=db,  # type: ignore[arg-type]
                current_user=object(),
                q="SMTEST0001",
                limit=20,
            )

    assert response.headers.get("Cache-Control") == "private, no-store"


async def _capture_cache_params(context: ReleaseContext, site_variant: SiteVariant):
    captured: dict[str, Any] = {}

    async def fake_get_or_set(name, ttl, loader, *, params=None):
        del name, ttl, loader
        captured["params"] = params
        return {
            "query": "Glyma",
            "results": [],
            "by_type": {"gene": 0},
            "by_assembly": {},
            "ambiguous": False,
            "cursor": None,
            "next_cursor": None,
            "has_more": False,
            "total_count": 0,
        }

    with (
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(return_value=context),
        ),
        patch("app.services.search_service.get_or_set", fake_get_or_set),
    ):
        await SearchService().global_search(
            object(),
            "Glyma",
            types=[SearchResultType.GENE],
            assembly_id=context.assembly_id,
            site_variant=site_variant,
        )
    return captured["params"]


@pytest.mark.asyncio
async def test_global_search_cache_isolates_site_variant_release_and_assembly():
    """CTX-01/02/03: the shared cache must not be reused across contexts.

    The earlier contract only asserted one call's params; it never proved that
    a different release or assembly yields a different key, which is the
    property that keeps v4 and v5 (and two releases) from serving each other's
    cached rows.
    """
    external_v4_release7 = await _capture_cache_params(
        ReleaseContext(release_id=7, assembly_id=11), SiteVariant.EXTERNAL
    )
    other_release = await _capture_cache_params(
        ReleaseContext(release_id=8, assembly_id=11), SiteVariant.EXTERNAL
    )
    other_assembly = await _capture_cache_params(
        ReleaseContext(release_id=7, assembly_id=12), SiteVariant.EXTERNAL
    )

    assert external_v4_release7["site_variant"] == "external"
    assert external_v4_release7["release_id"] == 7
    assert external_v4_release7["assembly_id"] == 11
    # CTX-02: a different release must not share the entry.
    assert external_v4_release7 != other_release
    # CTX-03: a different assembly must not share the entry.
    assert external_v4_release7 != other_assembly


@pytest.mark.asyncio
async def test_internal_global_search_bypasses_the_shared_cache():
    """CTX-01: internal rows must never enter the shared (external) cache."""
    cache = AsyncMock()
    service = SearchService()
    with (
        patch(
            "app.services.search_service.resolve_release_context",
            AsyncMock(return_value=ReleaseContext(release_id=7, assembly_id=11)),
        ),
        patch("app.services.search_service.get_or_set", cache),
        patch.object(service, "_search_genes", AsyncMock(return_value=[])),
        patch.object(service, "_gene_assembly_distribution", AsyncMock(return_value={})),
    ):
        await service.global_search(
            object(),
            "Glyma",
            types=[SearchResultType.GENE],
            site_variant=SiteVariant.INTERNAL,
        )

    cache.assert_not_awaited()

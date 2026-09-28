"""OPT-03 call-site proof: real callers must hand the scope into ``make_key``.

A widened key function is worthless if the two production call sites keep
calling it unscoped.  These tests drive the real aggregator and the real
``/search`` HTML endpoint, spy on ``SearchCache.make_key``, and assert the
resolved biological scope actually reaches it (and therefore forks the keys
handed to Redis).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.v1 import search as search_api
from app.core.site_variant import SiteVariant
from app.search import ExternalSearchAggregator, ExternalSearchResponse
from app.search.cache import SearchCache
from app.search.models import SearchSource, SourceResult, SourceStatus
from app.services.release_context import ReleaseContext


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.sets: list[str] = []

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append(key)
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


class _EmptyAdapter:
    def __init__(self, source: SearchSource) -> None:
        self.source = source
        self.timeout = 0.1

    async def search(self, query: str, limit: int, client: object) -> SourceResult:
        return SourceResult(source=self.source, status=SourceStatus.EMPTY, hits=[])


def _spy_make_key(monkeypatch) -> list[dict]:
    calls: list[dict] = []
    real = SearchCache.make_key

    def spy(query, sources, **scope):
        calls.append({"query": query, "sources": tuple(sources), **scope})
        return real(query, sources, **scope)

    monkeypatch.setattr(SearchCache, "make_key", staticmethod(spy))
    return calls


# --------------------------------------------------------------- aggregator site
async def test_aggregator_passes_scope_into_make_key(monkeypatch) -> None:
    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)
    aggregator = ExternalSearchAggregator(
        redis,
        shared_http_client=object(),
        site_variant=SiteVariant.EXTERNAL,
        release_id=7,
        assembly_id=11,
    )
    aggregator._adapters = {SearchSource.NCBI: _EmptyAdapter(SearchSource.NCBI)}

    await aggregator.search("Glyma", sources=[SearchSource.NCBI], limit_per_source=8)

    assert len(calls) == 1
    assert calls[0]["query"] == "Glyma"
    assert calls[0]["sources"] == ("ncbi",)
    assert calls[0]["site_variant"] == SiteVariant.EXTERNAL
    assert calls[0]["release_id"] == 7
    assert calls[0]["assembly_id"] == 11
    assert calls[0]["filters"] == {"limit_per_source": 8}
    assert redis.sets and redis.sets[0].startswith("search:external:")


async def test_aggregator_forks_the_key_per_scope_axis(monkeypatch) -> None:
    redis = _FakeRedis()
    _spy_make_key(monkeypatch)

    async def stored_key(**scope: object) -> str:
        aggregator = ExternalSearchAggregator(
            redis, shared_http_client=object(), **scope
        )
        aggregator._adapters = {SearchSource.NCBI: _EmptyAdapter(SearchSource.NCBI)}
        await aggregator.search("Glyma", sources=[SearchSource.NCBI])
        return redis.sets[-1]

    base = await stored_key(
        site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11
    )
    other_release = await stored_key(
        site_variant=SiteVariant.EXTERNAL, release_id=8, assembly_id=11
    )
    other_assembly = await stored_key(
        site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=12
    )
    internal = await stored_key(
        site_variant=SiteVariant.INTERNAL, release_id=7, assembly_id=11
    )

    assert len({base, other_release, other_assembly, internal}) == 4


# ------------------------------------------------------------------ endpoint site
class _StubAggregator:
    def __init__(self, *args: object, **scope: object) -> None:
        self.scope = scope

    async def search(self, query: str, **kwargs: object) -> ExternalSearchResponse:
        return ExternalSearchResponse(query=query, sources=[])


async def _call_federated_html(
    monkeypatch,
    *,
    redis: _FakeRedis,
    calls: list[dict],
    release_id: int | None,
    assembly_id: int | None,
    requested_release_id: int | None = None,
) -> None:
    monkeypatch.setattr(
        search_api.FeatureFlagService, "is_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        search_api,
        "resolve_release_context",
        AsyncMock(
            return_value=ReleaseContext(release_id=release_id, assembly_id=assembly_id)
        ),
    )
    monkeypatch.setattr(search_api, "get_redis", lambda: redis)
    monkeypatch.setattr(search_api, "ExternalSearchAggregator", _StubAggregator)
    monkeypatch.setattr(search_api, "render_search_html", lambda response: "<html/>")

    await search_api.global_search(
        request=object(),
        db=object(),
        q="Glyma",
        types=None,
        sources=["ncbi"],
        cursor=None,
        limit=20,
        assembly_id=assembly_id,
        release_id=requested_release_id,
        format="html",
        accept=None,
    )


async def test_endpoint_passes_resolved_scope_into_make_key(monkeypatch) -> None:
    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)

    await _call_federated_html(
        monkeypatch, redis=redis, calls=calls, release_id=7, assembly_id=11
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "Glyma"
    assert calls[0]["site_variant"] == SiteVariant.EXTERNAL
    assert calls[0]["release_id"] == 7
    assert calls[0]["assembly_id"] == 11
    assert calls[0]["filters"] == {"limit_per_source": 10}


async def test_endpoint_forks_html_cache_key_per_release_and_assembly(monkeypatch) -> None:
    redis = _FakeRedis()
    _spy_make_key(monkeypatch)

    async def stored_key(*, release_id: int | None, assembly_id: int | None) -> str:
        await _call_federated_html(
            monkeypatch,
            redis=redis,
            calls=[],
            release_id=release_id,
            assembly_id=assembly_id,
        )
        return redis.sets[-1]

    base = await stored_key(release_id=7, assembly_id=11)
    other_release = await stored_key(release_id=8, assembly_id=11)
    other_assembly = await stored_key(release_id=7, assembly_id=12)

    assert len({base, other_release, other_assembly}) == 3
    assert base.endswith(":html")


@pytest.mark.asyncio
async def test_endpoint_survives_without_a_published_release(monkeypatch) -> None:
    """Best-effort release resolution keeps the federated route alive."""
    from app.core.exceptions import ServiceUnavailableError

    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)
    monkeypatch.setattr(
        search_api.FeatureFlagService, "is_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        search_api,
        "resolve_release_context",
        AsyncMock(side_effect=ServiceUnavailableError("none")),
    )
    monkeypatch.setattr(search_api, "get_redis", lambda: redis)
    monkeypatch.setattr(search_api, "ExternalSearchAggregator", _StubAggregator)
    monkeypatch.setattr(search_api, "render_search_html", lambda response: "<html/>")

    await search_api.global_search(
        request=object(),
        db=object(),
        q="Glyma",
        types=None,
        sources=["ncbi"],
        cursor=None,
        limit=20,
        assembly_id=None,
        release_id=None,
        format="html",
        accept=None,
    )

    assert calls[0]["release_id"] is None


@pytest.mark.asyncio
async def test_explicit_release_pin_wins_over_the_resolved_release(monkeypatch) -> None:
    """An explicit request pin is the scope, even before its release is published."""
    redis = _FakeRedis()
    calls = _spy_make_key(monkeypatch)

    await _call_federated_html(
        monkeypatch,
        redis=redis,
        calls=calls,
        release_id=7,  # what the active-pointer lookup returns
        assembly_id=None,
        requested_release_id=99,  # what the caller named
    )

    assert calls[0]["release_id"] == 99

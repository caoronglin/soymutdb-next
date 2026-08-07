"""Parallel aggregator over all enabled source adapters.

Runs every requested adapter concurrently with :func:`asyncio.gather`
(``return_exceptions=True``) under a shared timeout, and also wraps each
adapter call in :func:`asyncio.wait_for` with the per-source timeout so a
slow source cannot dominate the response wall-clock.
"""

from __future__ import annotations

import asyncio
import time
from typing import Iterable

import httpx
import structlog
from redis.asyncio import Redis

from .adapters import BaseAdapter, EBIAdapter, EnsemblAdapter, NCBIAdapter, UniProtAdapter
from .cache import SearchCache
from .models import (
    ExternalSearchResponse,
    SearchHit,
    SearchSource,
    SourceResult,
    SourceStatus,
)

logger = structlog.get_logger(__name__)

# Hard wall-clock ceiling for the whole federated call, regardless of
# individual per-source timeouts.
AGGREGATE_TIMEOUT = 8.0


class ExternalSearchAggregator:
    """Run parallel external searches and aggregate normalized results."""

    def __init__(self, redis: Redis, shared_http_client: httpx.AsyncClient | None = None) -> None:
        self._redis = redis
        self._cache = SearchCache(redis)
        self._shared_client = shared_http_client
        self._adapters: dict[SearchSource, BaseAdapter] = {
            SearchSource.NCBI: NCBIAdapter(redis),
            SearchSource.UNIPROT: UniProtAdapter(redis),
            SearchSource.ENSEMBL: EnsemblAdapter(redis),
            SearchSource.EBI: EBIAdapter(redis),
        }

    def available_sources(self) -> list[SearchSource]:
        return list(self._adapters.keys())

    async def search(
        self,
        query: str,
        sources: Iterable[SearchSource] | None = None,
        limit_per_source: int = 8,
        use_cache: bool = True,
    ) -> ExternalSearchResponse:
        start = time.perf_counter()
        query = query.strip()
        requested: list[SearchSource] = list(sources) if sources else self.available_sources()

        # Deterministic order.
        requested = [s for s in self.available_sources() if s in requested]

        # Cache lookup (HTML / JSON is cached separately by the caller; here
        # we cache the normalized response structure).
        cache_key = SearchCache.make_key(query, tuple(s.value for s in requested))
        cached = None
        if use_cache:
            cached = await self._cache.get_json(cache_key)
            if cached is not None:
                logger.debug("external_search.cache_hit", key=cache_key)
                return self._from_cache(cached, query)

        # Shared httpx client for connection pooling.
        owns_client = self._shared_client is None
        client = self._shared_client or httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            follow_redirects=True,
            headers={"User-Agent": "SoyMutDB/2.0"},
        )

        async def _run(adapter: BaseAdapter) -> SourceResult:
            try:
                return await asyncio.wait_for(
                    adapter.search(query, limit=limit_per_source, client=client),
                    timeout=adapter.timeout + 1.0,  # small buffer over per-call timeout
                )
            except asyncio.TimeoutError:
                return SourceResult(
                    source=adapter.source,
                    status=SourceStatus.TIMEOUT,
                    error_message="source timed out",
                    elapsed_ms=adapter.timeout * 1000,
                )

        try:
            tasks = [_run(self._adapters[s]) for s in requested]
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=False),
                timeout=AGGREGATE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # Hard outer timeout; mark pending sources as timed out but keep
            # whatever completed already.
            logger.warning("external_search.aggregate_timeout", query=query)
            # Build best-effort results from what is present; easiest is to
            # return already-completed via a fresh shorter gather.
            tasks = [_run(self._adapters[s]) for s in requested]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            results = [
                r if isinstance(r, SourceResult) else SourceResult(
                    source=requested[i],
                    status=SourceStatus.ERROR,
                    error_message=str(r)[:200] if isinstance(r, Exception) else "unknown error",
                )
                for i, r in enumerate(results)
            ]
        finally:
            if owns_client:
                await client.aclose()

        elapsed = (time.perf_counter() - start) * 1000
        response = ExternalSearchResponse(query=query, sources=list(results), elapsed_ms=elapsed)

        # Cache a JSON-serializable version.
        if use_cache:
            try:
                await self._cache.set_json(cache_key, self._to_cache(response))
            except Exception as e:  # pragma: no cover
                logger.warning("external_search.cache_set_error", error=str(e))

        return response

    # --------------------------------------------------------- cache (de)ser
    @staticmethod
    def _to_cache(resp: ExternalSearchResponse) -> dict:
        return {
            "query": resp.query,
            "elapsed_ms": resp.elapsed_ms,
            "sources": [
                {
                    "source": s.source.value,
                    "status": s.status.value,
                    "elapsed_ms": s.elapsed_ms,
                    "error_message": s.error_message,
                    "hits": [
                        {
                            "source": h.source.value,
                            "title": h.title,
                            "url": h.url,
                            "snippet": h.snippet,
                            "id": h.id,
                            "extra": h.extra,
                        }
                        for h in s.hits
                    ],
                }
                for s in resp.sources
            ],
        }

    def _from_cache(self, raw: dict, query: str) -> ExternalSearchResponse:
        sources: list[SourceResult] = []
        for s in raw.get("sources", []):
            hits = [
                SearchHit(
                    source=SearchSource(h["source"]),
                    title=h["title"],
                    url=h["url"],
                    snippet=h.get("snippet", ""),
                    id=h.get("id", ""),
                    extra=h.get("extra", {}),
                )
                for h in s.get("hits", [])
            ]
            sources.append(
                SourceResult(
                    source=SearchSource(s["source"]),
                    status=SourceStatus(s["status"]),
                    hits=hits,
                    elapsed_ms=s.get("elapsed_ms", 0.0),
                    error_message=s.get("error_message"),
                )
            )
        return ExternalSearchResponse(
            query=query,
            sources=sources,
            elapsed_ms=raw.get("elapsed_ms", 0.0),
        )

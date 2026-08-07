"""Search endpoints — internal DB search (JSON) and external federated search (HTML).

Content negotiation:
* ``Accept: application/json`` or ``?format=json`` → internal
  :class:`GlobalSearchResponse` (backward-compatible).
* Otherwise (default ``text/html``) → federated external search across
  NCBI, UniProt, Ensembl and EMBL-EBI, rendered as a sanitized HTML
  fragment that the frontend can inject into a results container.

The external search is cached in Redis for 5 minutes and uses a
per-source circuit breaker so that a degraded upstream never takes the
whole endpoint down.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db, get_redis
from ...schemas.search import GlobalSearchResponse, SearchResultType
from ...search import ExternalSearchAggregator, SearchSource, render_search_html
from ...search.cache import SearchCache
from ...services.search_service import SearchService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])
service = SearchService()


# Supported external source values (for query-param validation).
_EXTERNAL_SOURCES = {s.value: s for s in SearchSource if s != SearchSource.INTERNAL}


def _want_json(accept: str | None, fmt: str | None) -> bool:
    """Decide whether the caller wants JSON based on Accept header or ?format=."""
    if fmt == "json":
        return True
    if fmt == "html":
        return False
    if accept:
        lowered = accept.lower()
        if "application/json" in lowered:
            return True
        if "text/html" in lowered:
            return False
    # No Accept header (or ``*/*``) — default to the JSON API.
    return True


def _parse_sources(raw: list[str] | None) -> list[SearchSource]:
    """Parse ``sources`` query parameter (comma-separated, repeatable)."""
    if not raw:
        return [s for s in SearchSource if s != SearchSource.INTERNAL]
    selected: list[SearchSource] = []
    seen: set[str] = set()
    for token in raw:
        for part in token.split(","):
            key = part.strip().lower()
            if not key:
                continue
            if key not in _EXTERNAL_SOURCES:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown source '{key}'. valid: {sorted(_EXTERNAL_SOURCES)}",
                )
            if key not in seen:
                seen.add(key)
                selected.append(_EXTERNAL_SOURCES[key])
    return selected or [s for s in SearchSource if s != SearchSource.INTERNAL]


# --------------------------------------------------------------------- JSON
@router.get(
    "",
    response_model=GlobalSearchResponse,
    response_class=JSONResponse,
    summary="Global search (JSON or HTML fragment)",
)
async def global_search(
    request: Request,
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1, max_length=500, alias="query"),
    types: list[SearchResultType] | None = Query(default=None),
    sources: list[str] | None = Query(
        default=None,
        description="External sources to query (comma-separated): ncbi,uniprot,ensembl,ebi",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    format: str | None = Query(default=None, alias="format", description="'json' or 'html'"),
    accept: str | None = Header(default=None, alias="accept"),
) -> Response:
    """Global search endpoint.

    Returns JSON (internal DB search) when the client sends
    ``Accept: application/json`` or ``?format=json``.  Otherwise returns a
    sanitized HTML fragment built from federated external search results.
    """
    if _want_json(accept, format):
        # ---- Internal DB search (legacy / programmatic clients) ------------
        resp = await service.global_search(db, query=q, types=types, limit=limit)
        payload = resp if isinstance(resp, dict) else resp.model_dump()
        return JSONResponse(content=payload)

    # ---- External federated search -> HTML fragment -----------------------
    selected_sources = _parse_sources(sources)
    per_source_limit = max(3, min(10, limit))

    redis = get_redis()
    aggregator = ExternalSearchAggregator(redis)

    # Cache-key for the rendered HTML fragment.
    cache_key = SearchCache.make_key(q, tuple(s.value for s in selected_sources))
    cache = SearchCache(redis)

    # Try a cached HTML fragment first (separate from the structured cache
    # inside the aggregator, so we can short-circuit before any HTTP work).
    cached_html = await cache.get(cache_key + ":html")
    if cached_html:
        logger.debug("external_search.html_cache_hit", query=q)
        return Response(content=cached_html, media_type="text/html; charset=utf-8")

    start = time.perf_counter()
    ext_resp = await aggregator.search(
        q, sources=selected_sources, limit_per_source=per_source_limit
    )
    html = render_search_html(ext_resp)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "external_search.completed",
        query=q,
        total_hits=ext_resp.total_hits,
        elapsed_ms=round(elapsed, 1),
    )

    # Cache the rendered fragment for 5 minutes.
    await cache.set(cache_key + ":html", html)

    return Response(content=html, media_type="text/html; charset=utf-8")


# ------------------------------------------------------------------- suggest
@router.get("/suggest", response_model=list[dict])
async def suggest(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict]:
    """Autocomplete suggestions (internal DB only)."""
    suggestions = await service.suggest(db, query=q, limit=limit)
    return [s if isinstance(s, dict) else s.model_dump() for s in suggestions]

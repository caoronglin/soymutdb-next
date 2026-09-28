"""Search endpoints — SoyMutDB database search (JSON) and federated search (HTML).

Content negotiation:
* ``Accept: application/json`` or ``?format=json`` → public SoyMutDB
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
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db, get_redis
from ...core.exceptions import ServiceUnavailableError
from ...core.features import FeatureFlagService
from ...core.security import RoleName
from ...core.site_variant import SiteVariant
from ...models.auth import AuditLog
from ...schemas.search import (
    GlobalSearchResponse,
    InternalSearchResponse,
    SearchResultType,
)
from ...search import (
    ExternalSearchAggregator,
    ExternalSearchResponse,
    SearchSource,
    render_search_html,
)
from ...search.cache import SearchCache
from ...services.release_context import ReleaseContext, get_release_context, resolve_release_context
from ...services.search_service import SearchService
from .deps import require_role

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


def _external_json_payload(response: ExternalSearchResponse) -> dict:
    """Serialize the adapter result while preserving per-source degradation."""
    return {
        "query": response.query,
        "sources": [
            {
                "source": source.source.value,
                "status": source.status.value,
                "hits": [
                    {
                        "source": hit.source.value,
                        "title": hit.title,
                        "url": hit.url,
                        "snippet": hit.snippet,
                        "id": hit.id,
                        "extra": hit.extra,
                    }
                    for hit in source.hits
                ],
                "elapsed": source.elapsed_ms,
                "elapsed_ms": source.elapsed_ms,
                "error": source.error_message,
                "health": "healthy" if source.status.value in {"ok", "empty"} else "degraded",
            }
            for source in response.sources
        ],
        "total_hits": response.total_hits,
        "elapsed_ms": response.elapsed_ms,
    }


def _external_html_cache_key(
    query: str,
    sources: list[SearchSource],
    *,
    release_id: int | None = None,
    assembly_id: int | None,
    limit_per_source: int,
) -> str:
    """Scope the federated HTML-fragment cache like the structured cache.

    The external site variant is fixed for this route; the resolved release,
    the requested assembly and the per-source result limit are part of the
    scope, so neither a release change, nor a v4/v5 switch, nor a different
    result limit can reuse another scope's fragment.
    """
    return SearchCache.make_key(
        query,
        tuple(source.value for source in sources),
        site_variant=SiteVariant.EXTERNAL,
        release_id=release_id,
        assembly_id=assembly_id,
        filters={"limit_per_source": limit_per_source},
    )


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
    release_context: ReleaseContext = Depends(get_release_context),
    q: str = Query(..., min_length=1, max_length=500, alias="query"),
    types: list[SearchResultType] | None = Query(default=None),
    sources: list[str] | None = Query(
        default=None,
        description="External sources to query (comma-separated): ncbi,uniprot,ensembl,ebi",
    ),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    assembly_id: int | None = Query(default=None, ge=1),
    release_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Explicit release scope. Used verbatim (published or not); "
            "defaults to the active published release."
        ),
    ),
    format: str | None = Query(default=None, alias="format", description="'json' or 'html'"),
    accept: str | None = Header(default=None, alias="accept"),
) -> Response:
    """Global search endpoint.

    Returns JSON (public SoyMutDB search) when the client sends
    ``Accept: application/json`` or ``?format=json``.  Otherwise returns a
    sanitized HTML fragment built from federated external search results.

    The release query/header pin is resolved through the published release
    context dependency before either the catalog or federated search runs.
    Draft and otherwise unavailable release ids are rejected; without a pin,
    the active published release is selected.
    """
    resolved_release_id = release_context.release_id
    if _want_json(accept, format):
        if sources:
            if not await FeatureFlagService.is_enabled(db, "search.external"):
                raise HTTPException(status_code=503, detail="External search is currently disabled")
            selected_sources = _parse_sources(sources)
            aggregator = ExternalSearchAggregator(
                get_redis(),
                site_variant=SiteVariant.EXTERNAL,
                release_id=resolved_release_id,
                assembly_id=assembly_id,
            )
            ext_resp = await aggregator.search(
                q,
                sources=selected_sources,
                limit_per_source=max(3, min(10, limit)),
            )
            return JSONResponse(
                content=_external_json_payload(ext_resp),
                headers={"Vary": "Accept"},
            )
        # ---- Public SoyMutDB search (legacy / programmatic clients) --------
        resp = await service.global_search(
            db,
            query=q,
            types=types,
            cursor=cursor,
            limit=limit,
            assembly_id=assembly_id,
            site_variant=SiteVariant.EXTERNAL,
            release_id=resolved_release_id,
        )
        payload = resp if isinstance(resp, dict) else resp.model_dump()
        return JSONResponse(content=payload, headers={"Vary": "Accept"})

    # ---- External federated search -> HTML fragment -----------------------
    if not await FeatureFlagService.is_enabled(db, "search.external"):
        raise HTTPException(status_code=503, detail="External search is currently disabled")
    selected_sources = _parse_sources(sources)
    per_source_limit = max(3, min(10, limit))
    release_id = resolved_release_id

    redis = get_redis()
    aggregator = ExternalSearchAggregator(
        redis,
        site_variant=SiteVariant.EXTERNAL,
        release_id=release_id,
        assembly_id=assembly_id,
    )

    # Cache-key for the rendered HTML fragment.  It shares the aggregator's
    # biological scope (site variant, release, assembly, query, sources, limit).
    cache_key = _external_html_cache_key(
        q,
        selected_sources,
        release_id=release_id,
        assembly_id=assembly_id,
        limit_per_source=per_source_limit,
    )
    cache = SearchCache(redis)

    # Try a cached HTML fragment first (separate from the structured cache
    # inside the aggregator, so we can short-circuit before any HTTP work).
    cached_html = await cache.get(cache_key + ":html")
    if cached_html:
        logger.debug("external_search.html_cache_hit", query=q)
        return Response(
            content=cached_html,
            media_type="text/html; charset=utf-8",
            headers={"Vary": "Accept"},
        )

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

    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Vary": "Accept"},
    )


# ------------------------------------------------------------------- suggest
@router.get("/suggest", response_model=list[dict])
async def suggest(
    db: AsyncSession = Depends(get_db),
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(default=5, ge=1, le=20),
    release_id: int | None = Query(default=None, ge=1),
    pinned_release_id: int | None = Header(default=None, alias="X-SoyMutDB-Release", ge=1),
) -> list[dict]:
    """Autocomplete suggestions scoped to the requested published release."""
    if release_id is not None and pinned_release_id is not None and release_id != pinned_release_id:
        raise HTTPException(
            status_code=422, detail="Conflicting release ids were provided"
        )
    requested_release_id = release_id if release_id is not None else pinned_release_id
    try:
        release_context = await resolve_release_context(db, requested_release_id)
    except ServiceUnavailableError:
        # Fail closed: without a published release there is no release-scoped
        # suggestion set. Returning an unscoped list would expose draft
        # assemblies, so the anonymous surface stays empty instead.
        logger.warning("search.suggest.no_active_release")
        return []
    suggestions = await service.suggest(
        db, query=q, limit=limit, release_id=release_context.release_id
    )
    return [s if isinstance(s, dict) else s.model_dump() for s in suggestions]


# ------------------------------------------------------------------- internal
@router.get(
    "/internal",
    response_model=InternalSearchResponse,
    summary="Authorized internal search across public and internal identifiers",
)
async def internal_search(
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_role(RoleName.RESEARCHER)),
    q: str = Query(..., min_length=1, max_length=500, alias="query"),
    limit: int = Query(default=20, ge=1, le=100),
) -> InternalSearchResponse:
    """Internal-site search: server-side authorized, audited, uncached.

    Results carry both identities (public_id / internal_id) and the field
    that matched. The shared search cache is deliberately bypassed so
    authorized rows cannot leak into another scope, and the response is
    marked ``private, no-store``.
    """
    context = await resolve_release_context(db)
    result = await service.internal_search(
        db, q, release_id=context.release_id, limit=limit
    )
    # Structured audit of internal retrieval. The query text is recorded;
    # credentials and tokens never are.
    db.add(
        AuditLog(
            user_id=getattr(current_user, "id", None),
            action="search.internal",
            resource_type="search",
            resource_id=q[:128],
            new_value={"limit": limit, "results": result.total_count},
        )
    )
    await db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return result

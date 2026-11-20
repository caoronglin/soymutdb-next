"""Search endpoints — SoyMutDB catalogue search (JSON).

Federated external search (NCBI, UniProt, Ensembl, EMBL-EBI) is retired
permanently, including its content negotiation and HTML-fragment response, so
every route here answers with JSON scoped to the resolved published release.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import ServiceUnavailableError
from ...core.security import RoleName
from ...core.site_variant import SiteVariant
from ...models.auth import AuditLog
from ...schemas.search import (
    GlobalSearchResponse,
    InternalSearchResponse,
    SearchResultType,
)
from ...services.release_context import ReleaseContext, get_release_context, resolve_release_context
from ...services.search_service import SearchService
from .deps import require_role

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/search", tags=["search"])
service = SearchService()


# ------------------------------------------------------------------- global
@router.get(
    "",
    response_model=GlobalSearchResponse,
    response_class=JSONResponse,
    summary="Global search across the SoyMutDB catalogue",
)
async def global_search(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    q: str = Query(..., min_length=1, max_length=500, alias="query"),
    types: list[SearchResultType] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    assembly_id: int | None = Query(default=None, ge=1),
    release_id: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Explicit release scope. Must name a published release; the "
            "active published release is used when omitted."
        ),
    ),
) -> Response:
    """Search the published SoyMutDB catalogue.

    Federated external search (NCBI / UniProt / Ensembl / EMBL-EBI) is retired
    permanently: the ``sources`` parameter, the ``format``/``Accept`` content
    negotiation and the sanitized HTML-fragment response are all gone, so this
    endpoint always answers with JSON catalogue results.

    The release query/header pin is resolved through the published release
    context dependency; draft and otherwise unavailable release ids are
    rejected, and without a pin the active published release is selected.
    """
    resp = await service.global_search(
        db,
        query=q,
        types=types,
        cursor=cursor,
        limit=limit,
        assembly_id=assembly_id,
        site_variant=SiteVariant.EXTERNAL,
        release_id=release_context.release_id,
    )
    payload = resp if isinstance(resp, dict) else resp.model_dump()
    return JSONResponse(content=payload)


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
        db,
        query=q,
        limit=limit,
        release_id=release_context.release_id,
        # The cache key carries the variant; passing it keeps that boundary
        # honest even though this route is external-only today.
        site_variant=SiteVariant.EXTERNAL,
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

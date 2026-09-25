"""Public table-view contract.

The portal asks which columns to render instead of hard-coding them, so an
operator can reorder, relabel, hide or add columns — including the
cross-assembly homolog columns — without a frontend release.

Scoping rules:

* the site variant is an explicit request parameter, never inferred from a
  header, host, cookie or user agent (``AGENTS.md`` dual-site boundary);
* the internal variant's layout is authenticated: the internal artifact is a
  separate security boundary, so an anonymous caller cannot enumerate what an
  internal deployment shows;
* the layout is resolved for the caller's ``species`` and release, so one
  deployment never serves another species' or another release's column set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthenticationError
from ...core.site_variant import SiteVariant
from ...models.auth import User
from ...schemas.table_views import ResolvedTableView
from ...services.release_context import get_release_context
from ...services.table_views_service import TABLE_KINDS, TableKind, resolve_template
from .deps import get_optional_user

router = APIRouter(prefix="/table-views", tags=["table-views"])


@router.get("/{kind}", response_model=ResolvedTableView)
async def get_table_view(
    kind: TableKind,
    db: AsyncSession = Depends(get_db),
    release_context=Depends(get_release_context),
    variant: SiteVariant = Query(default=SiteVariant.EXTERNAL),
    species: str = Query(default="Glycine max", max_length=128),
    current_user: User | None = Depends(get_optional_user),
) -> ResolvedTableView:
    """Resolve the ordered column layout for one portal table."""
    if variant is SiteVariant.INTERNAL and current_user is None:
        raise AuthenticationError("Authenticated internal access required")

    return await resolve_template(
        db,
        kind=kind,
        species=species,
        site_variant=variant.value,
        release_id=release_context.release_id,
    )


__all__ = ["TABLE_KINDS", "router"]

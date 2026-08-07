"""Release endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...models.content import Release, ReleaseStatus
from ...schemas.content import ReleaseResponse

router = APIRouter(prefix="/releases", tags=["releases"])


@router.get("", response_model=list[ReleaseResponse])
async def list_releases(
    db: AsyncSession = Depends(get_db),
    status: ReleaseStatus | None = Query(default=None),
) -> list[ReleaseResponse]:
    """List database releases."""
    stmt = select(Release).order_by(Release.published_at.desc())
    if status is not None:
        stmt = stmt.where(Release.status == status)
    result = await db.execute(stmt)
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{release_id}", response_model=ReleaseResponse)
async def get_release(
    release_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReleaseResponse:
    result = await db.execute(select(Release).where(Release.id == release_id))
    release = result.scalar_one_or_none()
    if release is None:
        from ...core.exceptions import NotFoundError

        raise NotFoundError(f"Release {release_id} not found")
    return _to_response(release)


def _to_response(r: Release) -> ReleaseResponse:
    return ReleaseResponse(
        id=str(r.id),
        version=r.version,
        name=r.name,
        description=r.description,
        variant_count=r.variant_count,
        gene_count=r.gene_count,
        mutant_line_count=r.mutant_line_count,
        status=r.status,
        published_at=r.published_at,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )

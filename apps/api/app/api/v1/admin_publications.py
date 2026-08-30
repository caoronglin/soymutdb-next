"""Admin publication endpoints.

Provides explicit CRUD for the ``publications`` table.  The Admin content tab
previously called a non-existent generic ``/admin/content?type=publication``
endpoint; this router is the replacement contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...models.content import Publication
from ...schemas.content import (
    PublicationCreate,
    PublicationListResponse,
    PublicationResponse,
    PublicationUpdate,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/publications", tags=["admin-publications"])


def _require_admin(user: User) -> None:
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator access required")


def _to_response(p: Publication) -> PublicationResponse:
    return PublicationResponse(
        id=str(p.id),
        title=p.title,
        title_zh=p.title_zh,
        authors=p.authors,
        authors_zh=p.authors_zh,
        journal=p.journal,
        year=p.year,
        doi=p.doi,
        pmid=p.pmid,
        abstract=p.abstract,
        abstract_zh=p.abstract_zh,
        is_featured=p.is_featured,
        created_at=p.created_at,
    )


async def _get(db: AsyncSession, publication_id: int) -> Publication:
    result = await db.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    pub = result.scalar_one_or_none()
    if pub is None:
        raise NotFoundError(f"Publication {publication_id} not found")
    return pub


@router.get("", response_model=PublicationListResponse)
async def list_publications_admin(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str | None = Query(default=None),
    is_featured: bool | None = Query(default=None),
) -> PublicationListResponse:
    """List publications (admin)."""
    _require_admin(current_user)
    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                Publication.title.ilike(pattern),
                Publication.authors.ilike(pattern),
                Publication.doi.ilike(pattern),
                Publication.pmid.ilike(pattern),
            )
        )
    if is_featured is not None:
        conditions.append(Publication.is_featured.is_(is_featured))

    count_stmt = select(func.count()).select_from(Publication)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(await db.scalar(count_stmt) or 0)

    stmt = select(Publication).order_by(Publication.year.desc(), Publication.id.desc())
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    items = [_to_response(p) for p in result.scalars().all()]
    return PublicationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=PublicationResponse, status_code=status.HTTP_201_CREATED)
async def create_publication(
    payload: PublicationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationResponse:
    """Create a publication (admin)."""
    _require_admin(current_user)
    pub = Publication(
        title=payload.title,
        title_zh=payload.title_zh,
        authors=payload.authors,
        authors_zh=payload.authors_zh,
        journal=payload.journal,
        year=payload.year,
        doi=payload.doi,
        pmid=payload.pmid,
        abstract=payload.abstract,
        abstract_zh=payload.abstract_zh,
        is_featured=payload.is_featured,
    )
    db.add(pub)
    await db.commit()
    await db.refresh(pub)
    return _to_response(pub)


@router.put("/{publication_id}", response_model=PublicationResponse)
async def update_publication(
    publication_id: int,
    payload: PublicationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublicationResponse:
    """Update a publication (admin)."""
    _require_admin(current_user)
    pub = await _get(db, publication_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pub, field, value)
    await db.commit()
    await db.refresh(pub)
    return _to_response(pub)


@router.delete("/{publication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_publication(
    publication_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete a publication (admin)."""
    _require_admin(current_user)
    pub = await _get(db, publication_id)
    await db.delete(pub)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

"""Seed request contact endpoints (D1 — public contact + admin processing).

- ``POST /seed-requests`` — public submission (no auth); the service writes
  the request row plus an outbox event so the worker emails the requester
  and the admins.
- ``GET /admin/seed-requests`` — seed-manager capability; paginated listing with an
  optional status filter.
- ``PATCH /admin/seed-requests/{id}`` — seed-manager capability; transition-validated
  status updates (pending → approved/rejected → fulfilled).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.seed_request import (
    SeedRequestCreate,
    SeedRequestListResponse,
    SeedRequestResponse,
    SeedRequestStatus,
    SeedRequestUpdate,
)
from ...services.seed_request_service import SeedRequestService
from .deps import require_role

router = APIRouter(tags=["seed-requests"])
service = SeedRequestService()
settings = get_settings()


@router.post(
    "/seed-requests",
    response_model=SeedRequestResponse,
    status_code=201,
    summary="Submit a public seed request",
)
async def create_seed_request(
    payload: SeedRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> SeedRequestResponse:
    """Submit a seed request contact (open to all; no authentication)."""
    return await service.create_request(db, payload)


@router.get(
    "/admin/seed-requests",
    response_model=SeedRequestListResponse,
    summary="List seed requests (seed manager)",
)
async def list_seed_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(RoleName.SEED_MANAGER)),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    status: SeedRequestStatus | None = Query(default=None),
) -> SeedRequestListResponse:
    """Paginated admin listing with an optional status filter."""
    return await service.list_requests(
        db, page=page, page_size=page_size, status=status
    )


@router.patch(
    "/admin/seed-requests/{request_id}",
    response_model=SeedRequestResponse,
    summary="Update a seed request status (seed manager)",
)
async def update_seed_request(
    request_id: uuid.UUID,
    update: SeedRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(RoleName.SEED_MANAGER)),
) -> SeedRequestResponse:
    """Advance a request's status (pending → approved/rejected → fulfilled)."""
    return await service.update_status(
        db, request_id, update, processed_by=current_user.id
    )


__all__ = ["router"]

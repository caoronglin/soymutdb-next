"""Seed inventory and request endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.seed import (
    SeedInventoryResponse,
    SeedRequestCreate,
    SeedRequestResponse,
    SeedRequestStatus,
    SeedRequestUpdate,
)
from ...services.seed_service import SeedService
from .deps import get_current_user, require_role

router = APIRouter(prefix="/seeds", tags=["seeds"])
service = SeedService()


@router.get("/inventory", response_model=list[SeedInventoryResponse])
async def list_inventory(
    db: AsyncSession = Depends(get_db),
    mutant_line_id: int | None = Query(default=None),
) -> list[SeedInventoryResponse]:
    """List seed inventory."""
    return await service.list_inventory(db, mutant_line_id=mutant_line_id)


@router.get("/inventory/{inventory_id}", response_model=SeedInventoryResponse)
async def get_inventory(
    inventory_id: int,
    db: AsyncSession = Depends(get_db),
) -> SeedInventoryResponse:
    """Get seed inventory detail."""
    return await service.get_inventory(db, inventory_id)


@router.post(
    "/requests",
    response_model=SeedRequestResponse,
    status_code=201,
)
async def create_seed_request(
    request: SeedRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> SeedRequestResponse:
    """Submit a seed request (open to all)."""
    return await service.create_request(db, request)


@router.get("/requests", response_model=list[SeedRequestResponse])
async def list_seed_requests(
    db: AsyncSession = Depends(get_db),
    status: SeedRequestStatus | None = Query(default=None),
) -> list[SeedRequestResponse]:
    """List seed requests."""
    return await service.list_requests(db, status=status)


@router.patch(
    "/requests/{request_id}",
    response_model=SeedRequestResponse,
    dependencies=[Depends(require_role(RoleName.SEED_MANAGER))],
)
async def update_seed_request(
    request_id: uuid.UUID,
    update: SeedRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SeedRequestResponse:
    """Update a seed request status (requires seed_manager role)."""
    return await service.update_request(db, request_id, update, current_user.id)

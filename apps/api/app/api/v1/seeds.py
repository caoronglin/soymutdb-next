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
from ...services.release_context import ReleaseContext, get_release_context
from ...services.seed_service import SeedService
from .deps import get_current_user, require_role

router = APIRouter(prefix="/seeds", tags=["seeds"])
service = SeedService()


@router.get("/inventory", response_model=list[SeedInventoryResponse])
async def list_inventory(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    mutant_line_public_id: str | None = Query(
        default=None,
        description="Public mutant-line identifier (e.g. SM7K3ZQ9P2AX).",
    ),
) -> list[SeedInventoryResponse]:
    """List seed inventory for the resolved published release.

    Rows are bound to a released mutant line; the previous version listed every
    lot in the table, including drafts and other releases, and identified the
    line by its internal key.
    """
    return await service.list_inventory(
        db,
        release_context=release_context,
        mutant_line_public_id=mutant_line_public_id,
    )


@router.get("/inventory/{seed_lot}", response_model=SeedInventoryResponse)
async def get_inventory(
    seed_lot: str,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> SeedInventoryResponse:
    """Get a seed lot by its public lot label within the published release.

    The inventory row's persistence key is not a locator: a request for it (or
    for a lot outside the release) returns the same not-found response.
    """
    return await service.get_inventory(
        db, seed_lot, release_context=release_context
    )


@router.post(
    "/requests",
    response_model=SeedRequestResponse,
    status_code=201,
)
async def create_seed_request(
    request: SeedRequestCreate,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> SeedRequestResponse:
    """Submit a seed request (open to all).

    The requested line is addressed by its public identifier and must exist in
    the resolved published release; a numeric/internal value is refused.
    """
    return await service.create_request(
        db, request, release_context=release_context
    )


@router.get(
    "/requests",
    response_model=list[SeedRequestResponse],
    dependencies=[Depends(require_role(RoleName.SEED_MANAGER))],
)
async def list_seed_requests(
    db: AsyncSession = Depends(get_db),
    status: SeedRequestStatus | None = Query(default=None),
) -> list[SeedRequestResponse]:
    """List seed requests containing contact data (seed_manager only)."""
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

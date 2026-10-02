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
    MAX_GENE_IDS,
    SeedRequestCreate,
    SeedRequestGeneCount,
    SeedRequestListResponse,
    SeedRequestResponse,
    SeedRequestStatsResponse,
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
    "/seed-requests/stats",
    response_model=SeedRequestStatsResponse,
    summary="Public seed-request demand per gene (counts only)",
)
async def seed_request_stats(
    db: AsyncSession = Depends(get_db),
    gene_ids: str = Query(
        default="",
        max_length=8192,
        description=(
            "Comma-separated gene IDs. At most MAX_GENE_IDS distinct values are "
            "counted; the rest are ignored rather than rejected, so a page can "
            "send a whole result set without branching."
        ),
    ),
) -> SeedRequestStatsResponse:
    """Report how many requests reference each gene ID.

    Anonymous on purpose: the gene page renders "N requests" beside the seed
    request entry as a demand signal. The payload is counts only — no requester
    name, institution, email, timestamp or status ever leaves
    ``/admin/seed-requests``, so this cannot be turned into an enumeration of
    who asked for what.
    """
    wanted = [part.strip() for part in gene_ids.split(",") if part.strip()][:MAX_GENE_IDS]
    counts = await service.count_requests_by_gene(db, gene_ids=wanted)
    return SeedRequestStatsResponse(
        # Every requested ID is echoed, including the zeros, so the client can
        # render a row per gene without inferring "missing" as "unknown".
        items=[
            SeedRequestGeneCount(gene_id=gene_id, requests=counts.get(gene_id, 0))
            for gene_id in dict.fromkeys(wanted)
        ],
        total_requests=await service.total_requests(db),
    )


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

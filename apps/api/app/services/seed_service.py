"""Seed inventory and request service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.seed import SeedInventory, SeedRequest, SeedRequestStatus
from ..schemas.seed import (
    SeedInventoryResponse,
    SeedRequestCreate,
    SeedRequestResponse,
    SeedRequestUpdate,
)


class SeedService:
    """Seed inventory and request management."""

    async def list_inventory(
        self, db: AsyncSession, mutant_line_id: int | None = None
    ) -> list[SeedInventoryResponse]:
        stmt = select(SeedInventory)
        if mutant_line_id is not None:
            stmt = stmt.where(SeedInventory.mutant_line_id == mutant_line_id)
        result = await db.execute(stmt)
        return [self._inv_to_response(i) for i in result.scalars().all()]

    async def get_inventory(
        self, db: AsyncSession, inventory_id: int
    ) -> SeedInventoryResponse:
        result = await db.execute(
            select(SeedInventory).where(SeedInventory.id == inventory_id)
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise NotFoundError(f"Seed inventory {inventory_id} not found")
        return self._inv_to_response(inv)

    async def create_request(
        self, db: AsyncSession, request: SeedRequestCreate
    ) -> SeedRequestResponse:
        """Submit a new seed request."""
        ml_id = int(request.mutant_line_id)
        # Verify mutant line exists.
        from ..models.variant import MutantLine

        ml_result = await db.execute(
            select(MutantLine).where(MutantLine.id == ml_id)
        )
        if ml_result.scalar_one_or_none() is None:
            raise NotFoundError(f"Mutant line {ml_id} not found")

        seed_req = SeedRequest(
            id=uuid.uuid4(),
            requester_name=request.requester_name,
            requester_email=request.requester_email,
            requester_institution=request.requester_institution,
            mutant_line_id=ml_id,
            purpose=request.purpose,
            quantity_requested=request.quantity_grams,
            status=SeedRequestStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        db.add(seed_req)
        await db.commit()
        await db.refresh(seed_req)
        return self._req_to_response(seed_req)

    async def list_requests(
        self,
        db: AsyncSession,
        status: SeedRequestStatus | None = None,
    ) -> list[SeedRequestResponse]:
        stmt = select(SeedRequest)
        if status is not None:
            stmt = stmt.where(SeedRequest.status == status)
        result = await db.execute(stmt)
        return [self._req_to_response(r) for r in result.scalars().all()]

    async def update_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        update: SeedRequestUpdate,
        reviewer_id: uuid.UUID,
    ) -> SeedRequestResponse:
        result = await db.execute(
            select(SeedRequest).where(SeedRequest.id == request_id)
        )
        seed_req = result.scalar_one_or_none()
        if seed_req is None:
            raise NotFoundError(f"Seed request {request_id} not found")

        seed_req.status = update.status
        seed_req.reviewer_id = reviewer_id
        seed_req.reviewed_at = datetime.now(timezone.utc)
        if update.tracking_number is not None:
            seed_req.tracking_number = update.tracking_number
        if update.notes is not None:
            seed_req.notes = update.notes
        await db.commit()
        await db.refresh(seed_req)
        return self._req_to_response(seed_req)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _inv_to_response(inv: SeedInventory) -> SeedInventoryResponse:
        return SeedInventoryResponse(
            id=str(inv.id),
            mutant_line_id=str(inv.mutant_line_id),
            seed_lot=inv.seed_lot,
            quantity_grams=float(inv.quantity_grams),
            location=inv.location,
            harvest_date=inv.harvest_date,
            viability_pct=float(inv.viability_pct) if inv.viability_pct else None,
            notes=inv.notes,
            created_at=inv.created_at,
            updated_at=inv.updated_at,
        )

    @staticmethod
    def _req_to_response(req: SeedRequest) -> SeedRequestResponse:
        return SeedRequestResponse(
            id=str(req.id),
            mutant_line_id=str(req.mutant_line_id),
            status=req.status,
            quantity_requested=float(req.quantity_requested)
            if req.quantity_requested
            else None,
            requester_name=req.requester_name,
            requester_email=req.requester_email,
            requester_institution=req.requester_institution,
            purpose=req.purpose,
            tracking_number=req.tracking_number,
            notes=req.notes,
            created_at=req.created_at,
            reviewed_at=req.reviewed_at,
        )

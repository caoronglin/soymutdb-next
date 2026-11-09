"""Seed inventory and request service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError
from ..core.public_ids import normalize_public_id
from ..models.seed import SeedInventory, SeedRequest, SeedRequestStatus
from ..models.variant import MutantLine
from ..schemas.seed import (
    SeedInventoryResponse,
    SeedRequestCreate,
    SeedRequestResponse,
    SeedRequestUpdate,
)
from ..services.release_context import ReleaseContext


class SeedService:
    """Seed inventory and request management.

    Public reads are bound to the resolved published release and address rows by
    their public locators. ``seed_inventory`` has no release column of its own —
    it hangs off ``mutant_lines`` — so scoping means joining the line and
    filtering ``MutantLine.release_id``.
    """

    async def list_inventory(
        self,
        db: AsyncSession,
        *,
        release_context: ReleaseContext,
        mutant_line_public_id: str | None = None,
    ) -> list[SeedInventoryResponse]:
        """List seed lots whose line is released, public and not deleted.

        The release predicate alone would still expose a line an operator has
        unpublished or soft-deleted inside a released namespace, so visibility
        and deletion are applied on the same join as the release.
        """
        stmt = (
            select(SeedInventory)
            .join(MutantLine, SeedInventory.mutant_line_id == MutantLine.id)
            .where(
                MutantLine.release_id == release_context.release_id,
                MutantLine.is_public.is_(True),
                MutantLine.is_deleted.is_(False),
            )
        )
        if mutant_line_public_id is not None:
            stmt = stmt.where(
                func.upper(MutantLine.public_id)
                == normalize_public_id(mutant_line_public_id)
            )
        result = await db.execute(stmt)
        return [self._inv_to_response(i) for i in result.scalars().all()]

    async def get_inventory(
        self,
        db: AsyncSession,
        seed_lot: str,
        *,
        release_context: ReleaseContext,
    ) -> SeedInventoryResponse:
        """Look a lot up by its public lot label, not its persistence key."""
        result = await db.execute(
            select(SeedInventory)
            .join(MutantLine, SeedInventory.mutant_line_id == MutantLine.id)
            .where(
                SeedInventory.seed_lot == seed_lot,
                MutantLine.release_id == release_context.release_id,
                MutantLine.is_public.is_(True),
                MutantLine.is_deleted.is_(False),
            )
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            raise NotFoundError(f"Seed lot {seed_lot!r} not found")
        return self._inv_to_response(inv)

    @staticmethod
    async def _resolve_line(
        db: AsyncSession,
        public_id: str,
        *,
        release_context: ReleaseContext,
    ) -> int:
        """Resolve a public mutant id to its internal key in the release."""
        from ..core.public_ids import normalize_public_id

        candidate = normalize_public_id(public_id)
        if not candidate.startswith("SM"):
            raise NotFoundError(f"Mutant line {public_id} not found")
        result = await db.execute(
            select(MutantLine.id).where(
                func.upper(MutantLine.public_id) == candidate,
                MutantLine.is_deleted.is_(False),
                MutantLine.is_public.is_(True),
                MutantLine.release_id == release_context.release_id,
            )
        )
        line_id = result.scalar_one_or_none()
        if line_id is None:
            raise NotFoundError(f"Mutant line {public_id} not found")
        return int(line_id)

    async def create_request(
        self,
        db: AsyncSession,
        request: SeedRequestCreate,
        *,
        release_context: ReleaseContext,
    ) -> SeedRequestResponse:
        """Submit a new seed request against a released, public mutant line."""
        ml_id = await self._resolve_line(
            db, request.mutant_line_public_id, release_context=release_context
        )

        seed_req = SeedRequest(
            id=uuid.uuid4(),
            requester_name=request.requester_name,
            requester_email=request.requester_email,
            requester_institution=request.requester_institution,
            mutant_line_id=ml_id,
            purpose=request.purpose,
            quantity_requested=request.quantity_grams,
            status=SeedRequestStatus.PENDING,
            created_at=datetime.now(UTC),
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
        seed_req.reviewed_at = datetime.now(UTC)
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
        line = getattr(inv, "mutant_line", None)
        return SeedInventoryResponse(
            mutant_line_public_id=(line.public_id if line is not None else ""),
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
        line = getattr(req, "mutant_line", None)
        return SeedRequestResponse(
            id=str(req.id),
            mutant_line_public_id=(line.public_id if line is not None else ""),
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

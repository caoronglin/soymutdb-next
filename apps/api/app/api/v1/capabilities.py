"""Public server capabilities for feature-gated clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.features import FeatureFlagService
from ...schemas.features import PublicCapabilitiesResponse

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=PublicCapabilitiesResponse)
async def get_capabilities(db: AsyncSession = Depends(get_db)) -> PublicCapabilitiesResponse:
    return PublicCapabilitiesResponse(
        features=await FeatureFlagService.snapshot(db, public_only=True)
    )

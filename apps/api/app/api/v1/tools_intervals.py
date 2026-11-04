"""Published-gene interval overlap endpoint.

The assembly/release/chromosome are resolved server-side from the current
published ReleaseContext.  The client supplies only bounded 1-based regions;
it cannot name a table, path, object key or arbitrary dataset.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas import sequence_tools as s
from ...services import interval_overlap_service as service
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/tools/intervals", tags=["tools"])


@router.post("/overlap", response_model=s.OverlapResponse)
async def interval_overlap(
    payload: s.OverlapRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> s.OverlapResponse:
    """Overlap user regions with published gene annotations of one assembly."""
    return await service.overlap(db, payload, release_context)

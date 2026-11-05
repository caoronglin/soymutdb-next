"""Unified no-SQL query builder over the existing export pipeline.

One durable export pipeline already exists (``POST /variants/export`` ->
outbox -> ``export`` queue -> object storage). This router is a *façade*
over it: it accepts a whitelist of filters, refuses anything with no backing
query capability, and submits the equivalent ``ExportRequest`` through the
same shared helper. No new queue, no new storage backend, no second SQL
builder.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.export_query import ExportQueryRequest, ExportQueryResponse
from ...schemas.variant import ExportRequest, VariantExportFilters
from ...services.release_context import ReleaseContext, get_release_context
from .deps import require_role
from .variants import _submit_export

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post(
    "/query",
    response_model=ExportQueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_export_query(
    request: ExportQueryRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(require_role(RoleName.RESEARCHER)),
) -> ExportQueryResponse:
    """Submit a whitelisted filter set as one asynchronous variant export.

    Unknown or unbacked filters are refused by ``ExportQueryRequest`` before
    any record or outbox event is written, so a downloader never receives an
    artifact that silently ignored a constraint they set.
    """
    export_request = ExportRequest(
        format=request.format,
        filters=VariantExportFilters(**request.filters),
        compress=request.compress,
    )
    export_id = await _submit_export(
        db,
        export_request=export_request,
        release_context=release_context,
        current_user=current_user,
    )
    await db.commit()

    return ExportQueryResponse(
        export_id=str(export_id),
        status="pending",
        message="Export job submitted",
        format=request.format,
        applied_filters={
            key: value for key, value in request.filters.items()
        },
    )

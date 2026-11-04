"""Unified no-SQL query builder over the existing export pipeline.

One durable export pipeline already exists (``POST /variants/export`` ->
outbox -> ``export`` queue -> object storage). This router is a *façade*
over it: it accepts a whitelist of filters, refuses anything with no backing
query capability, and submits the equivalent ``ExportRequest`` through the
same shared helper. No new queue, no new storage backend, no second SQL
builder.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...core.task_contract import EXPORT_VARIANTS_TASK
from ...models.auth import User
from ...schemas.export_query import ExportQueryRequest, ExportQueryResponse
from ...schemas.variant import ExportRequest, VariantExportFilters
from ...services.outbox_service import enqueue_task_event
from ...services.release_context import ReleaseContext, get_release_context
from ...services.variant_export_service import VariantExportService
from .deps import require_role
from .variants import _submit_export

router = APIRouter(prefix="/exports", tags=["exports"])
export_service = VariantExportService()


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
    export_id = uuid.uuid4()
    filters, assembly_scope = await _submit_export(
        db,
        export_request=export_request,
        release_context=release_context,
        current_user=current_user,
    )
    await export_service.create_record(
        db,
        export_id=export_id,
        user_id=current_user.id,
        release_key=release_context.release_key,
        assembly_key=assembly_scope,
        export_format=request.format,
        compress=request.compress,
        filters=filters,
    )
    await enqueue_task_event(
        db,
        event_type="variant_export_requested",
        aggregate_type="variant_export",
        aggregate_id=str(export_id),
        task_name=EXPORT_VARIANTS_TASK,
        kwargs={
            "export_id": str(export_id),
            "filters": filters,
            "format": request.format,
            "compress": request.compress,
        },
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

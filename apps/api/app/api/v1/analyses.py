"""Analyses endpoints: upload presign, job submission, status, download presign.

Every endpoint requires the researcher role or higher (hierarchical RBAC
includes administrators).  Unauthenticated callers get 401, lower roles 403 –
both through the unified error envelope.

The upload flow is stateless: a pre-signed PUT URL plus the object key are
returned immediately (no job row yet); the job is created only when the
client submits it with the returned object keys.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...core.database import get_db
from ...core.security import RoleName
from ...models.analysis_job import AnalysisType as ModelAnalysisType
from ...models.auth import User
from ...schemas.analyses import (
    AnalysesDownloadResponse,
    AnalysesJobListResponse,
    AnalysesJobResponse,
    AnalysesSubmitRequest,
    AnalysesSubmitResponse,
    AnalysesUploadRequest,
    AnalysesUploadResponse,
    AnalysisType,
)
from ...services.analyses_service import AnalysesService
from ...services.presign import (
    UPLOAD_EXPIRES_IN,
    build_upload_key,
    generate_upload_url,
)
from .deps import get_current_user, get_user_roles, require_role

settings = get_settings()

router = APIRouter(prefix="/analyses", tags=["analyses"])
service = AnalysesService()

#: All analyses endpoints require researcher (or higher; admin included).
_RESEARCHER_OR_HIGHER = [Depends(require_role(RoleName.RESEARCHER))]


@router.get(
    "",
    response_model=AnalysesJobListResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def list_analysis_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysesJobListResponse:
    """List the current user's most recent analysis jobs (newest first).

    Only jobs owned by the caller are returned; anonymous/lower-role callers
    get 401/403 through the unified error envelope.
    """
    return await service.list_jobs(db, current_user.id, limit)


@router.post(
    "/uploads",
    response_model=AnalysesUploadResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def create_upload(request: AnalysesUploadRequest) -> AnalysesUploadResponse:
    """Request a pre-signed upload URL for an analysis input file.

    Returns a PUT URL valid for 1 hour plus the object key the client must
    send back at submit time.  Nothing is persisted yet.
    """
    job_id = uuid.uuid4()
    object_key = build_upload_key(job_id, request.filename)
    upload_url = generate_upload_url(object_key, expires_in=UPLOAD_EXPIRES_IN)
    return AnalysesUploadResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=UPLOAD_EXPIRES_IN,
    )


@router.post(
    "/{analysis_type}/submit",
    response_model=AnalysesSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def submit_analysis(
    analysis_type: AnalysisType,
    request: AnalysesSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysesSubmitResponse:
    """Submit an analysis job for the uploaded objects.

    Validates the ``analyses/`` key prefix and the parameter whitelist, then
    creates the job row + outbox event in one transaction (queued).
    """
    return await service.submit_job(
        db, current_user.id, ModelAnalysisType(analysis_type.value), request
    )


@router.get(
    "/{job_id}",
    response_model=AnalysesJobResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def get_analysis_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysesJobResponse:
    """Return the current status of an analysis job.

    ``result`` is ``null`` until the job completes; completed jobs carry the
    worker-written summary.
    """
    return await service.get_job(db, job_id, current_user.id, get_user_roles(current_user))


@router.get(
    "/{job_id}/download",
    response_model=AnalysesDownloadResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def download_analysis_object(
    job_id: uuid.UUID,
    object_key: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalysesDownloadResponse:
    """Return a pre-signed GET URL for one of the job's own objects.

    The key must live under ``analyses/{job_id}/``; anything outside that
    prefix (including other jobs' objects) is rejected.
    """
    return await service.get_download_url(
        db, job_id, object_key, current_user.id, get_user_roles(current_user)
    )

"""GWAS endpoints: upload presign, job submission, status, result URLs.

Every endpoint requires the researcher role or higher (hierarchical RBAC
includes administrators).  Unauthenticated callers get 401, lower roles 403 –
both through the unified error envelope.

The upload flow is stateless: a pre-signed PUT URL plus the object key are
returned immediately (no job row yet); the job is created only when the
client submits it with the returned object keys.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.gwas import (
    GwasJobResponse,
    GwasResultResponse,
    GwasSubmitRequest,
    GwasUploadRequest,
    GwasUploadResponse,
)
from ...services.gwas_service import GwasService
from .deps import get_current_user, get_user_roles, require_role

router = APIRouter(prefix="/gwas", tags=["gwas"])
service = GwasService()

#: All GWAS endpoints require researcher (or higher; admin included).
_RESEARCHER_OR_HIGHER = [Depends(require_role(RoleName.RESEARCHER))]


@router.post(
    "/uploads",
    response_model=GwasUploadResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def create_upload(
    request: GwasUploadRequest,
    current_user: User = Depends(get_current_user),
) -> GwasUploadResponse:
    """Request a pre-signed upload URL for a GWAS input file.

    Returns a PUT URL valid for 1 hour plus the object key the client must
    send back at submit time.  Nothing is persisted yet.
    """
    return GwasUploadResponse(
        **service.create_upload(current_user.id, request.filename)
    )


@router.post(
    "/submit",
    response_model=GwasJobResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def submit_gwas_job(
    request: GwasSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GwasJobResponse:
    """Submit a GWAS job for the uploaded inputs.

    Validates the ``gwas/`` key namespace, the phenotype file format, the
    method whitelist and the parameter whitelist, then creates the job row +
    outbox event in one transaction (pending).
    """
    return await service.submit_job(db, current_user.id, request)


@router.get(
    "/{job_id}",
    response_model=GwasJobResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def get_gwas_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GwasJobResponse:
    """Return the current status of a GWAS job.

    ``result`` is ``null`` until the job completes; completed jobs carry the
    worker-written summary (MinIO object keys + association statistics).
    """
    return await service.get_job(db, job_id, current_user.id, get_user_roles(current_user))


@router.get(
    "/{job_id}/results",
    response_model=GwasResultResponse,
    dependencies=_RESEARCHER_OR_HIGHER,
)
async def get_gwas_results(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GwasResultResponse:
    """Return pre-signed download URLs for a completed GWAS job's outputs.

    Non-completed jobs return no URLs (status-aware envelope); completed jobs
    expose the Manhattan data JSON, the QQ data JSON and the self-contained
    ``Manhattan_QQ.html`` report.
    """
    return await service.get_result(db, job_id, current_user.id, get_user_roles(current_user))

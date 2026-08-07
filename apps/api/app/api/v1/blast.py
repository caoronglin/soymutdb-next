"""BLAST endpoints: list databases, submit job, check status, get results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.blast import (
    BlastDatabaseResponse,
    BlastJobResponse,
    BlastResultResponse,
    BlastSubmitRequest,
)
from ...services.blast_service import BlastService
from .deps import get_current_user, require_role

router = APIRouter(prefix="/blast", tags=["blast"])
service = BlastService()


@router.get("/databases", response_model=list[BlastDatabaseResponse])
async def list_blast_databases(
    db: AsyncSession = Depends(get_db),
) -> list[BlastDatabaseResponse]:
    """List active BLAST databases."""
    return await service.list_databases(db)


@router.post(
    "/jobs",
    response_model=BlastJobResponse,
    status_code=201,
    dependencies=[Depends(require_role(RoleName.RESEARCHER))],
)
async def submit_blast_job(
    request: BlastSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastJobResponse:
    """Submit a BLAST job (requires researcher role or higher)."""
    return await service.submit_job(db, current_user.id, request)


@router.get("/jobs/{job_id}", response_model=BlastJobResponse)
async def get_blast_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BlastJobResponse:
    """Check BLAST job status."""
    return await service.get_job(db, job_id)


@router.get("/jobs/{job_id}/results", response_model=BlastResultResponse)
async def get_blast_results(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BlastResultResponse:
    """Retrieve BLAST results for a completed job."""
    return await service.get_result(db, job_id)

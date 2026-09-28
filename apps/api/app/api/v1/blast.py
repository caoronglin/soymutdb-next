"""BLAST endpoints: list databases, submit job, check status, get results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.blast import (
    BlastDatabaseResponse,
    BlastJobListResponse,
    BlastJobResponse,
    BlastResultResponse,
    BlastSubmitRequest,
)
from ...services.blast_service import BlastService
from ...services.release_context import ReleaseContext, get_release_context
from .deps import get_current_user, get_user_roles, require_role

router = APIRouter(prefix="/blast", tags=["blast"])
service = BlastService()


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/databases", response_model=list[BlastDatabaseResponse])
async def list_blast_databases(
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> list[BlastDatabaseResponse]:
    """List active BLAST databases in the resolved published release.

    Database lives outside the release boundary: the list previously included
    the databases of draft releases, whose underlying data is not published.
    """
    return await service.list_databases(db, release_context=release_context)


@router.post(
    "/jobs",
    response_model=BlastJobResponse,
    status_code=201,
    dependencies=[Depends(require_role(RoleName.RESEARCHER))],
)
async def submit_blast_job(
    request: BlastSubmitRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(get_current_user),
) -> BlastJobResponse:
    """Submit a BLAST job (requires researcher role or higher).

    The target database is resolved inside the published release, so a job can
    never search another release's (including unreleased) database.
    """
    _private(response)
    return await service.submit_job(
        db, current_user.id, request, release_context=release_context
    )


@router.get("/jobs", response_model=BlastJobListResponse)
async def list_blast_jobs(
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastJobListResponse:
    """List the current user's BLAST jobs, newest first."""
    _private(response)
    return await service.list_jobs(
        db,
        current_user.id,
        get_user_roles(current_user),
        page=page,
        page_size=page_size,
        status=status,
    )


@router.get("/jobs/{job_id}", response_model=BlastJobResponse)
async def get_blast_job(
    job_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastJobResponse:
    """Check BLAST job status."""
    _private(response)
    return await service.get_job(db, job_id, current_user.id, get_user_roles(current_user))


@router.get("/jobs/{job_id}/results", response_model=BlastResultResponse)
async def get_blast_results(
    job_id: uuid.UUID,
    response: Response,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastResultResponse:
    """Retrieve BLAST results for a job (status-aware envelope).

    Returns ``hits=None`` for pending/running/failed jobs; only completed
    jobs carry a hit list (empty means a genuine zero-hit result).
    """
    _private(response)
    return await service.get_result(
        db, job_id, current_user.id, get_user_roles(current_user), limit=limit, offset=offset
    )

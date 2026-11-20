"""BLAST endpoints: list databases, submit job, check status, get results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.blast_capability import issue_blast_capability, verify_blast_capability
from ...core.config import get_settings
from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...core.ratelimit import public_blast_rate_limiter, resolve_trusted_peer_ip
from ...core.security import RoleName
from ...models.auth import User
from ...schemas.blast import (
    BlastDatabaseResponse,
    BlastDatabaseStateResponse,
    BlastDatabaseStateUpdate,
    BlastGenomeTargetResponse,
    BlastIndexBuildRequest,
    BlastIndexBuildResponse,
    BlastJobListResponse,
    BlastJobResponse,
    BlastResultResponse,
    BlastSubmitRequest,
    PublicBlastSubmission,
)
from ...services.blast_service import BlastService
from ...services.release_context import ReleaseContext, get_release_context
from .deps import get_current_user, get_user_roles, require_role
from .public_blast_route import PublicBlastRoute

router = APIRouter(prefix="/blast", tags=["blast"])
service = BlastService()
public_router = APIRouter(route_class=PublicBlastRoute)


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


@router.patch(
    "/databases/{database_id}",
    response_model=BlastDatabaseStateResponse,
    dependencies=[Depends(require_role(RoleName.ADMINISTRATOR))],
)
async def update_blast_database_state(
    database_id: int,
    body: BlastDatabaseStateUpdate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastDatabaseStateResponse:
    """Enable/disable a published BLAST index (administrator only).

    Disabling an index only removes it from *new* searches. Submitted jobs keep
    the provenance frozen at submission time and are never rewritten. There is
    no delete route: a published index is an immutable, auditable record.
    """
    _private(response)
    result = await service.set_database_active(
        db,
        database_id,
        body.is_active,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return result


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
    return await service.submit_job(db, current_user.id, request, release_context=release_context)


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


@router.post("/jobs/{job_id}/cancel", response_model=BlastJobResponse)
async def cancel_blast_job(
    job_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastJobResponse:
    """Cancel a pending/running BLAST job owned by the caller.

    The worker re-checks the row before launching the aligner, so a queued
    Celery message that arrives after cancellation cannot start a search.
    """
    _private(response)
    return await service.cancel_job(
        db, job_id, current_user.id, get_user_roles(current_user)
    )


@router.post("/jobs/{job_id}/retry", response_model=BlastJobResponse)
async def retry_blast_job(
    job_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(get_current_user),
) -> BlastJobResponse:
    """Re-dispatch a failed BLAST job with its original frozen provenance."""
    _private(response)
    return await service.retry_job(
        db, job_id, current_user.id, get_user_roles(current_user),
        release_context=release_context,
    )


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


def _public_private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "X-Blast-Token"


def _require_public_blast() -> None:
    if not get_settings().blast_public_enabled:
        raise NotFoundError("Public BLAST is disabled")


@router.post(
    "/index-builds",
    response_model=BlastIndexBuildResponse,
    status_code=202,
    dependencies=[Depends(require_role(RoleName.ADMINISTRATOR))],
)
async def create_blast_index_build(
    payload: BlastIndexBuildRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(get_current_user),
) -> BlastIndexBuildResponse:
    """Request an immutable NCBI index build (admin only).

    Records the catalog/build rows and one transactional-outbox event in a
    single transaction. ``makeblastdb`` never runs inside this HTTP request;
    the worker on the ``blast`` queue owns construction and publication.
    """
    _private(response)
    return await service.request_index_build(
        db, payload, user_id=current_user.id, release_context=release_context
    )


@router.get(
    "/index-builds/{build_id}",
    response_model=BlastIndexBuildResponse,
    dependencies=[Depends(require_role(RoleName.ADMINISTRATOR))],
)
async def get_blast_index_build(
    build_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> BlastIndexBuildResponse:
    """Poll one build's state; no filesystem path or binary name is exposed."""
    _private(response)
    return await service.get_index_build(db, build_id)


@router.get(
    "/jobs/{job_id}/hits/{subject_id}/genome-target",
    response_model=BlastGenomeTargetResponse,
)
async def get_blast_hit_genome_target(
    job_id: uuid.UUID,
    subject_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastGenomeTargetResponse:
    """Resolve a subject to a gene locus in the job's release/assembly.

    Never derives genomic coordinates from amino-acid alignment positions.
    An unresolved subject returns an explicit reason and no locus.
    """
    _private(response)
    # `user_id` and `user_roles` are keyword-only on the service: passing them
    # positionally raised a TypeError before the call ever ran.
    return await service.resolve_genome_target(
        db,
        job_id,
        subject_id,
        user_id=current_user.id,
        user_roles=get_user_roles(current_user),
    )


@public_router.get(
    "/public/jobs/{job_id}/hits/{subject_id}/genome-target",
    response_model=BlastGenomeTargetResponse,
    dependencies=[Depends(_require_public_blast)],
)
async def get_public_blast_hit_genome_target(
    job_id: uuid.UUID,
    subject_id: str,
    response: Response,
    access_token: str | None = Header(default=None, alias="X-Blast-Token"),
    db: AsyncSession = Depends(get_db),
) -> BlastGenomeTargetResponse:
    _public_private(response)
    verify_blast_capability(access_token, job_id)
    return await service.resolve_genome_target(
        db, job_id, subject_id, public_token=access_token
    )



@public_router.post(
    "/public/jobs/{job_id}/cancel",
    response_model=BlastJobResponse,
    dependencies=[Depends(_require_public_blast)],
)
async def cancel_public_blast_job(
    job_id: uuid.UUID,
    response: Response,
    access_token: str | None = Header(default=None, alias="X-Blast-Token"),
    db: AsyncSession = Depends(get_db),
) -> BlastJobResponse:
    """Anonymous capability holder may cancel only its own pending job."""
    _public_private(response)
    verify_blast_capability(access_token, job_id)
    return await service.cancel_job(db, job_id, public_token=access_token)

@public_router.post(
    "/public/jobs",
    response_model=PublicBlastSubmission,
    status_code=201,
    dependencies=[Depends(_require_public_blast)],
)
async def submit_public_blast_job(
    payload: BlastSubmitRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> PublicBlastSubmission:
    """Submit an explicitly anonymous job, even when a bearer session is present.

    Save the returned capability and send it as X-Blast-Token when polling.
    There is no public listing. Publication/release validation and execution
    reuse the same service, outbox and worker as private jobs.
    """
    _public_private(response)
    settings = get_settings()
    if len(payload.query_sequence) > settings.blast_public_max_length:
        raise ValidationError(f"Public query exceeds max length {settings.blast_public_max_length}")
    peer = resolve_trusted_peer_ip(request, settings.analytics_trusted_proxy_ips)
    await public_blast_rate_limiter.enforce(client_ip=peer)
    job = await service.submit_job(db, None, payload, release_context=release_context)
    token, expires_at = issue_blast_capability(uuid.UUID(job.job_id))
    return PublicBlastSubmission(job=job, access_token=token, expires_at=expires_at)


@public_router.get(
    "/public/jobs/{job_id}",
    response_model=BlastJobResponse,
    dependencies=[Depends(_require_public_blast)],
)
async def get_public_blast_job(
    job_id: uuid.UUID,
    response: Response,
    access_token: str | None = Header(default=None, alias="X-Blast-Token"),
    db: AsyncSession = Depends(get_db),
) -> BlastJobResponse:
    _public_private(response)
    verify_blast_capability(access_token, job_id)
    return await service.get_job(db, job_id, public_token=access_token)


@public_router.get(
    "/public/jobs/{job_id}/results",
    response_model=BlastResultResponse,
    dependencies=[Depends(_require_public_blast)],
)
async def get_public_blast_results(
    job_id: uuid.UUID,
    response: Response,
    access_token: str | None = Header(default=None, alias="X-Blast-Token"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> BlastResultResponse:
    _public_private(response)
    verify_blast_capability(access_token, job_id)
    return await service.get_result(
        db, job_id, limit=limit, offset=offset, public_token=access_token
    )


router.include_router(public_router)

"""BLAST endpoints: list databases, submit job, check status, get results."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.blast_capability import issue_blast_capability, verify_blast_capability
from ...core.config import get_settings
from ...core.database import get_db
from ...core.exceptions import NotFoundError, ValidationError
from ...core.ratelimit import public_blast_rate_limiter, resolve_trusted_peer_ip
from ...core.security import RoleName, require_admin_roles
from ...models.auth import User
from ...schemas.blast import (
    BlastDatabaseResponse,
    BlastGenomeTargetResponse,
    BlastIndexBuildQueued,
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


class BlastIndexBuildRequest(BaseModel):
    """Admin-only request to build one immutable NCBI index asynchronously.

    Only identifiers, frozen biological provenance and an object reference are
    accepted. No local filesystem path can pass this boundary.
    """

    database_id: int = Field(..., gt=0)
    db_type: Literal["nucl", "prot"]
    source_object: str = Field(..., min_length=1, max_length=512)
    assembly_id: str = Field(..., min_length=1, max_length=256)
    assembly_version: str = Field(..., min_length=1, max_length=256)
    release_id: str = Field(..., min_length=1, max_length=256)
    annotation_version: str = Field(..., min_length=1, max_length=256)
    source_url: str = Field(..., min_length=1, max_length=2048)
    source_version: str = Field(..., min_length=1, max_length=256)
    license: str = Field(..., min_length=1, max_length=1024)


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


@router.post(
    "/databases/build", status_code=202,
    response_model=BlastIndexBuildQueued,
    dependencies=[Depends(require_role(RoleName.ADMINISTRATOR))],
)
async def request_blast_index_build(
    request: BlastIndexBuildRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BlastIndexBuildQueued:
    """Queue an immutable index build; construction never runs in this request.

    The catalog row must exist and be buildable (``pending``/``failed`` or a
    ``ready`` row being rebuilt). The outbox event carries only the frozen
    metadata and a validated object reference; the worker resolves binaries,
    staging, validation and publication.
    """
    from ...core.task_contract import BLAST_INDEX_BUILD_TASK
    from ...services.job_service import build_job_payload
    from ...services.outbox_service import create_outbox_event

    _private(response)
    require_admin_roles(get_user_roles(current_user))
    # JobPayload.job_id is a UUID; a catalog id is not one, so use a fresh
    # deterministic-per-request UUID that carries no biological meaning.
    payload = build_job_payload(
        job_id=uuid.uuid4(),
        task_name=BLAST_INDEX_BUILD_TASK,
        payload={
            "database_id": request.database_id,
            "db_type": request.db_type,
            "source_object": request.source_object,
            **{key: getattr(request, key) for key in (
                "assembly_id", "assembly_version", "release_id",
                "annotation_version", "source_url", "source_version", "license",
            )},
        },
        idempotency_key=f"blast-index:{request.database_id}:{uuid.uuid4().hex}",
    )
    await create_outbox_event(
        db,
        aggregate_type="blast_database",
        aggregate_id=str(request.database_id),
        event_type="blast_database.build",
        payload=payload.model_dump(mode="json"),
    )
    await db.commit()
    return BlastIndexBuildQueued(
        database_id=request.database_id, queued=True, task_name=BLAST_INDEX_BUILD_TASK,
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
    return await service.resolve_genome_target(
        db, job_id, subject_id, current_user.id, get_user_roles(current_user)
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

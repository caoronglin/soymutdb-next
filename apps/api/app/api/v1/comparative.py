"""Comparative-genomics endpoints: families, member comparison, orthologs, artifacts.

Every read is bound to the resolved release and an optional assembly, so a
family imported for v5 can never be answered with v4 members. Absent data is
reported as ``no_data`` rather than an empty list.

The artifact endpoints only *record* a request and enqueue it through the
existing transactional outbox; the API never runs an aligner inside a request.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.security import RoleName
from ...core.task_contract import COMPARATIVE_ARTIFACT_TASK
from ...models.auth import User
from ...schemas.comparative import (
    ArtifactRequest,
    ArtifactResponse,
    FamilyDetailResponse,
    FamilyListResponse,
    MemberComparisonResponse,
    OrthologResponse,
)
from ...services.comparative_service import ComparativeService
from ...services.job_service import build_job_payload
from ...services.outbox_service import create_outbox_event
from ...services.presign import generate_download_url
from ...services.release_context import ReleaseContext, get_release_context
from .deps import get_current_user, require_role

router = APIRouter(prefix="/comparative", tags=["comparative"])
service = ComparativeService()


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/families", response_model=FamilyListResponse)
async def list_families(
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    level: str | None = Query(default=None, pattern="^(gene_family|gene_subfamily)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> FamilyListResponse:
    """List gene families/subfamilies in the resolved release."""
    _private(response)
    return await service.list_families(
        db,
        release_context=release_context,
        assembly_id=assembly_id,
        level=level,
        page=page,
        page_size=page_size,
    )


@router.get("/families/{family_id}", response_model=FamilyDetailResponse)
async def get_family(
    family_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
) -> FamilyDetailResponse:
    """One family with its members and per-species coverage.

    ``coverage`` names the species the family knows about; a species that
    contributed no member is ``state="no_data"`` with ``member_count: null``,
    never an empty member list that would read as "present but empty".
    """
    _private(response)
    return await service.get_family(
        db, family_id, release_context=release_context, assembly_id=assembly_id
    )


@router.get("/families/compare", response_model=MemberComparisonResponse)
async def compare_families(
    response: Response,
    left: int = Query(..., gt=0, description="Family id on the left side."),
    right: int = Query(..., gt=0, description="Family id on the right side."),
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
) -> MemberComparisonResponse:
    """Compare two families: shared members, and the members unique to each."""
    _private(response)
    return await service.compare_families(
        db, left, right, release_context=release_context, assembly_id=assembly_id
    )


@router.get("/genes/{gene_id}/orthologs", response_model=OrthologResponse)
async def get_gene_orthologs(
    gene_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    assembly_id: int | None = Query(default=None),
    homolog_type: str | None = Query(default=None, pattern="^(ortholog|paralog)$"),
) -> OrthologResponse:
    """Ortholog/paralog rows for one gene, with the relationship type stated.

    ``relationship_type`` summarises how many counterparts the source recorded
    per species. It is not derived from sequence similarity: this endpoint never
    reads BLAST hits.
    """
    _private(response)
    return await service.get_orthologs(
        db,
        gene_id,
        release_context=release_context,
        assembly_id=assembly_id,
        homolog_type=homolog_type,
    )


@router.post(
    "/artifacts",
    response_model=ArtifactResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(RoleName.RESEARCHER))],
)
async def request_artifact(
    request: ArtifactRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
    current_user: User = Depends(get_current_user),
) -> ArtifactResponse:
    """Queue an alignment or tree for a family.

    The response is the pending artifact, not a result: the aligner runs in the
    worker through the shared outbox, and the finished object is fetched through
    ``GET /comparative/artifacts/{job_id}``.
    """
    _private(response)
    artifact, _members = await service.request_artifact(
        db,
        family_id=request.family_id,
        artifact_type=request.artifact_type,
        method=request.method,
        release_context=release_context,
        assembly_id=request.assembly_id,
    )
    payload = build_job_payload(
        job_id=artifact.job_id,
        task_name=COMPARATIVE_ARTIFACT_TASK,
        payload={
            "artifact_id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "family_id": artifact.family_id,
            "release_id": artifact.release_id,
            "assembly_id": artifact.assembly_id,
            "method": artifact.method,
            "input_sha256": artifact.input_sha256,
            "member_ids": list(artifact.input_member_ids),
            "requested_by": str(current_user.id),
        },
        idempotency_key=f"comparative:{artifact.job_id}",
    )
    await create_outbox_event(
        db,
        aggregate_type="comparative_artifact",
        aggregate_id=str(artifact.id),
        event_type=f"comparative_artifact.{artifact.artifact_type}.build",
        payload=payload.model_dump(mode="json"),
    )
    await db.commit()
    return ArtifactResponse(
        artifact_type=artifact.artifact_type,  # type: ignore[arg-type]
        job_id=artifact.job_id,
        state=artifact.state,  # type: ignore[arg-type]
        method=artifact.method,
        input_sha256=artifact.input_sha256,
        input_member_ids=list(artifact.input_member_ids),
        download_url=None,
        error_message=None,
        created_at=artifact.created_at,
        completed_at=None,
    )


@router.get("/artifacts/{job_id}", response_model=ArtifactResponse)
async def get_artifact(
    job_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> ArtifactResponse:
    """Status of an alignment/tree, with a pre-signed URL once it succeeded."""
    _private(response)
    artifact = await service.get_artifact(db, job_id, release_context=release_context)
    object_key = await service.artifact_object_key(
        db, job_id, release_id=release_context.release_id
    )
    if object_key and artifact.state == "succeeded":
        artifact.download_url = generate_download_url(object_key)
    return artifact

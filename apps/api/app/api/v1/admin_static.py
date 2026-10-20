"""Admin static-page builder: trigger and check status of static generation jobs."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...core.task_contract import BUILD_STATIC_PAGES_TASK
from ...models.auth import User
from ...models.gene_data_cache import GeneDataCache
from ...models.genomic import Assembly, Gene
from ...models.import_task import ImportTask, ImportTaskStatus, ImportTaskType
from ...services.outbox_service import enqueue_task_event
from ...services.release_context import resolve_release_context
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/build-static", tags=["admin-static"])

#: Max gene IDs per explicit request (mirrors the seqfetch/seed-request cap).
MAX_STATIC_BUILD_GENE_IDS = 200
#: Per-entry length cap - a gene ID is a short stable identifier.
MAX_STATIC_BUILD_GENE_ID_LEN = 64


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


class StaticBuildRequest(BaseModel):
    """Body of the static-build trigger.

    Selection is validated but not resolved: an accession only means something
    against a release, so an unknown (or foreign-release) ID has to reach the
    build exactly as the administrator wrote it and simply not be counted.
    """

    gene_ids: list[str] | None = Field(default=None, max_length=MAX_STATIC_BUILD_GENE_IDS)

    @field_validator("gene_ids")
    @classmethod
    def _validate_gene_ids(cls, values: list[str] | None) -> list[str] | None:
        """Reject empty or over-long identifiers without dropping entries."""
        if values is None:
            return None
        for raw in values:
            gene_id = raw.strip()
            if not gene_id:
                raise ValueError("Gene IDs must not be empty")
            if len(raw) > MAX_STATIC_BUILD_GENE_ID_LEN:
                raise ValueError(
                    f"Gene ID {gene_id[:40]!r}... exceeds max length "
                    f"{MAX_STATIC_BUILD_GENE_ID_LEN}"
                )
        return values


async def _count_release_genes(
    db: AsyncSession,
    *,
    release_id: int,
    gene_ids: list[str] | None,
) -> int:
    """Count the genes this build will actually produce pages for.

    The count uses the release-scoped join the gene reads use, so a first build
    (nothing cached yet) still reports the real number, and an explicit
    selection only counts genes that exist in the built release. An empty
    selection is empty, not "everything".
    """
    if gene_ids is not None and not gene_ids:
        return 0

    statement = (
        select(func.count())
        .select_from(Gene)
        .join(Assembly, Assembly.id == Gene.assembly_id)
        .where(Assembly.release_id == release_id)
    )
    if gene_ids is not None:
        statement = statement.where(Gene.accession.in_(gene_ids))

    result = await db.execute(statement)
    return int(result.scalar() or 0)


# ---------------------------------------------------------------------------
# 1. Trigger static page build
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def trigger_build(
    body: StaticBuildRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Trigger a static page generation job (administrator-only).

    Request body::

        {
            "gene_ids": ["Glyma.01G000100", "Glyma.02G000200"] | null
        }

    If ``gene_ids`` is ``None``, all genes of the active published release
    will be rebuilt; ``[]`` rebuilds nothing. The build is scoped to a
    published release, so an installation without one is rejected (503)
    instead of queueing work against an unreleased namespace.
    """
    _require_admin(current_user)

    gene_ids = body.gene_ids

    # One resolved release drives both the count and the queued job, so the
    # reported scope can never disagree with what the worker builds. An
    # installation without a published active release is rejected here.
    release_id = (await resolve_release_context(db)).release_id
    total_genes = await _count_release_genes(db, release_id=release_id, gene_ids=gene_ids)

    # Persist the job record and its outbox event in one transaction. The
    # dispatcher owns broker I/O, preventing a broker failure from leaving a
    # committed queued task with no durable delivery intent.
    task = ImportTask(
        filename="static_pages_build",
        type=ImportTaskType.SEED_DATA.value,
        status=ImportTaskStatus.QUEUED.value,
        file_path="internal://build-static",
        submitted_by=str(current_user.id),
        idempotency_key=f"static-pages:{uuid4()}",
    )
    db.add(task)
    await db.flush()
    event = await enqueue_task_event(
        db,
        event_type="static_pages_build_requested",
        aggregate_type="import_task",
        aggregate_id=str(task.id),
        task_name=BUILD_STATIC_PAGES_TASK,
        kwargs={"gene_ids": gene_ids, "release_id": release_id},
    )
    task.celery_task_id = str(event.event_id)
    await db.commit()
    await db.refresh(task)

    return {
        "task_id": task.id,
        "total_genes": total_genes,
        "status": "queued",
    }


# ---------------------------------------------------------------------------
# 2. Get last build status
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_build_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the status of the most recent static page build
    (administrator-only)."""
    _require_admin(current_user)

    # Total cached gene entries.
    total_result = await db.execute(
        select(func.count()).select_from(GeneDataCache)
    )
    total_cached = int(total_result.scalar() or 0)

    # Most recent completed build task (by submitted_at).
    build_result = await db.execute(
        select(ImportTask)
        .where(
            ImportTask.filename == "static_pages_build",
            ImportTask.status == ImportTaskStatus.COMPLETED.value,
        )
        .order_by(ImportTask.submitted_at.desc())
        .limit(1)
    )
    last_build = build_result.scalar_one_or_none()

    last_build_at: str | None = None
    if last_build and last_build.completed_at:
        last_build_at = last_build.completed_at.isoformat()

    return {
        "last_build_at": last_build_at,
        "total_cached": total_cached,
        "status": "completed" if last_build else "never_built",
    }

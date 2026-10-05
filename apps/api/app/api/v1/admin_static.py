"""Admin static-page builder: trigger and check status of static generation jobs."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...core.task_contract import BUILD_STATIC_PAGES_TASK
from ...models.auth import User
from ...models.data_publishing import ActiveRelease
from ...models.gene_data_cache import GeneDataCache
from ...models.import_task import ImportTask, ImportTaskStatus, ImportTaskType
from ...services.outbox_service import enqueue_task_event
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/build-static", tags=["admin-static"])


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


# ---------------------------------------------------------------------------
# 1. Trigger static page build
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def trigger_build(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Trigger a static page generation job (administrator-only).

    Request body::

        {
            "gene_ids": ["Glyma.01G000100", "Glyma.02G000200"] | null
        }

    If ``gene_ids`` is ``None``, all genes will be rebuilt.
    """
    _require_admin(current_user)

    gene_ids: list[str] | None = body.get("gene_ids")

    # Determine total genes to build.
    if gene_ids:
        total_genes = len(gene_ids)
    else:
        total_result = await db.execute(
            select(func.count()).select_from(GeneDataCache)
        )
        total_genes = int(total_result.scalar() or 0)

    # Resolve the active release for the object namespace.
    active_result = await db.execute(select(ActiveRelease.release_id))
    active_release_id = active_result.scalar_one_or_none()

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
        kwargs={"gene_ids": gene_ids, "release_id": active_release_id},
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

"""Admin static-page builder: trigger and check status of static generation jobs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError
from ...core.security import RoleName, has_role
from ...core.task_contract import BUILD_STATIC_PAGES_TASK
from ...core.task_dispatch import dispatch_task
from ...models.auth import User
from ...models.gene_data_cache import GeneDataCache
from ...models.import_task import ImportTask, ImportTaskType, ImportTaskStatus
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

    # Record a build import task.
    task = ImportTask(
        filename="static_pages_build",
        type=ImportTaskType.SEED_DATA.value,
        status=ImportTaskStatus.QUEUED.value,
        file_path="internal://build-static",
        submitted_by=str(current_user.id),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Dispatch Celery task.
    async_result = dispatch_task(
        BUILD_STATIC_PAGES_TASK,
        identifier=task.id,
        kwargs={"gene_ids": gene_ids},
        queue="stats",
    )
    task.celery_task_id = async_result.id
    await db.commit()

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

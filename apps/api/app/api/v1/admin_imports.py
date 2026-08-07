"""Admin import management: create, list, status, cancel, and retry import tasks."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.exceptions import AuthorizationError, NotFoundError
from ...core.security import RoleName, has_role
from ...core.task_contract import IMPORT_EXPRESSION_TASK, IMPORT_HOMOLOG_TASK
from ...core.task_dispatch import dispatch_task, get_celery_client
from ...models.auth import User
from ...models.import_task import ImportTask, ImportTaskStatus
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/imports", tags=["admin-imports"])


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    if not has_role(get_user_roles(current_user), RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")


def _task_to_dict(task: ImportTask) -> dict:
    """Serialise an :class:`ImportTask` row into the API item shape."""
    return {
        "id": task.id,
        "filename": task.filename,
        "type": task.type,
        "status": task.status,
        "progress": task.progress,
        "total_records": task.total_records,
        "processed_records": task.processed_records,
        "celery_task_id": task.celery_task_id,
        "submitted_by": task.submitted_by,
        "file_path": task.file_path,
        "error_message": task.error_message,
        "submitted_at": task.submitted_at.isoformat() if task.submitted_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


# ---------------------------------------------------------------------------
# 1. List imports (paginated)
# ---------------------------------------------------------------------------


@router.get("")
async def list_imports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    search: str | None = Query(default=None),
    type: str | None = Query(default=None, alias="type"),
    status: str | None = Query(default=None, alias="status"),
) -> dict:
    """Paginated list of import tasks with optional filters (administrator-only)."""
    _require_admin(current_user)

    conditions = []
    if search:
        pattern = f"%{search}%"
        conditions.append(ImportTask.filename.ilike(pattern))
    if type:
        conditions.append(ImportTask.type == type)
    if status:
        conditions.append(ImportTask.status == status)

    where_clause = and_(*conditions) if conditions else None

    count_stmt = select(func.count()).select_from(ImportTask)
    if where_clause is not None:
        count_stmt = count_stmt.where(where_clause)
    total = int(await db.scalar(count_stmt) or 0)

    offset = (page - 1) * page_size
    stmt = select(ImportTask).order_by(ImportTask.id.desc())
    if where_clause is not None:
        stmt = stmt.where(where_clause)
    stmt = stmt.offset(offset).limit(page_size)
    result = await db.execute(stmt)
    tasks = result.scalars().all()

    items = [_task_to_dict(t) for t in tasks]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# 2. Get single import
# ---------------------------------------------------------------------------


@router.get("/{import_id}")
async def get_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get a single import task detail (administrator-only)."""
    _require_admin(current_user)

    result = await db.execute(select(ImportTask).where(ImportTask.id == import_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Import task {import_id} not found")

    return _task_to_dict(task)


# ---------------------------------------------------------------------------
# 3. Get import live status (including Celery task state)
# ---------------------------------------------------------------------------


@router.get("/{import_id}/status")
async def get_import_status(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the live status of an import task, including Celery task state
    (administrator-only)."""
    _require_admin(current_user)

    result = await db.execute(select(ImportTask).where(ImportTask.id == import_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Import task {import_id} not found")

    celery_status = "PENDING"
    if task.celery_task_id:
        async_result = get_celery_client().AsyncResult(task.celery_task_id)
        celery_status = async_result.state

    return {
        "id": task.id,
        "status": task.status,
        "celery_status": celery_status,
        "progress": task.progress,
        "processed_records": task.processed_records,
        "total_records": task.total_records,
        "error_message": task.error_message,
    }


# ---------------------------------------------------------------------------
# 4. Create a new import
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_import(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Create a new import task and dispatch it to Celery (administrator-only).

    Request body::

        {
            "filename": "expression_data.csv",
            "type": "expression_csv",
            "file_path": "s3://bucket/path/to/file.csv",
            "submitted_by": "user@example.com"
        }
    """
    _require_admin(current_user)

    task = ImportTask(
        filename=body["filename"],
        type=body["type"],
        status=ImportTaskStatus.QUEUED.value,
        file_path=body["file_path"],
        submitted_by=body.get("submitted_by"),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Dispatch Celery task by name.
    task_name = _resolve_task_name(task.type)
    if task_name:
        async_result = dispatch_task(
            task_name,
            identifier=task.id,
            args=[task.id, task.file_path],
            queue="ingest",
        )
        task.celery_task_id = async_result.id
        await db.commit()

    return _task_to_dict(task)


def _resolve_task_name(import_type: str) -> str | None:
    """Map an import type to the corresponding Celery task name."""
    mapping = {
        "expression_csv": IMPORT_EXPRESSION_TASK,
        "homolog_csv": IMPORT_HOMOLOG_TASK,
    }
    return mapping.get(import_type)


# ---------------------------------------------------------------------------
# 5. Delete / cancel an import
# ---------------------------------------------------------------------------


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Cancel and delete an import task (administrator-only).

    If the task is still running, the associated Celery task is revoked.
    """
    _require_admin(current_user)

    result = await db.execute(select(ImportTask).where(ImportTask.id == import_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Import task {import_id} not found")

    # Revoke the Celery task if still running.
    if task.celery_task_id and task.status == ImportTaskStatus.RUNNING.value:
        get_celery_client().control.revoke(task.celery_task_id, terminate=True)

    task.status = ImportTaskStatus.FAILED.value
    task.error_message = "Cancelled by user"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()


# ---------------------------------------------------------------------------
# 6. Retry a failed import
# ---------------------------------------------------------------------------


@router.post("/{import_id}/retry")
async def retry_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Retry a failed import: reset status, clear error, re-dispatch Celery
    task (administrator-only)."""
    _require_admin(current_user)

    result = await db.execute(select(ImportTask).where(ImportTask.id == import_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError(f"Import task {import_id} not found")

    task.status = ImportTaskStatus.QUEUED.value
    task.error_message = None
    task.completed_at = None
    task.progress = 0
    task.processed_records = 0

    # Re-dispatch Celery task.
    task_name = _resolve_task_name(task.type)
    if task_name:
        async_result = dispatch_task(
            task_name,
            identifier=task.id,
            args=[task.id, task.file_path],
            queue="ingest",
        )
        task.celery_task_id = async_result.id

    await db.commit()
    await db.refresh(task)

    return _task_to_dict(task)

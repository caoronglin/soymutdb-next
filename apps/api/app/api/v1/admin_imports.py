"""Admin import management: create, list, status, cancel, and retry import tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.features import IMPORT_TYPE_FEATURES, FeatureFlagService
from ...core.exceptions import NotFoundError, ValidationError
from ...core.security import require_admin_roles
from ...core.task_dispatch import get_celery_client
from ...models.auth import User
from ...models.import_task import ImportTask, ImportTaskStatus
from ...schemas.data_publishing import (
    ImportCreateRequest,
    MultipartCompleteRequest,
    MultipartStartRequest,
)
from ...services.outbox_service import create_import_command
from ...services.presign import (
    CompletedPart,
    complete_multipart_upload,
    initiate_multipart_upload,
    sign_multipart_part,
)
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/imports", tags=["admin-imports"])


class MultipartCompletePathRequest(MultipartCompleteRequest):
    pass


def _require_admin(current_user: User) -> None:
    """Raise :class:`AuthorizationError` unless *current_user* is an administrator."""
    require_admin_roles(get_user_roles(current_user))


async def _require_import_type_enabled(db: AsyncSession, import_type: str) -> None:
    """Reject an import type whose persisted writer is not closed.

    Every import type maps to a registered feature flag (see
    ``core.features.IMPORT_TYPE_FEATURES``).  A type without a flag is
    unsupported; a type whose flag is off is rejected up front so the caller
    gets a clear 422 rather than a worker ``fail-closed`` after dispatch.
    """
    feature_key = IMPORT_TYPE_FEATURES.get(import_type)
    if feature_key is None:
        raise ValidationError(f"Unsupported import type '{import_type}'")
    if not await FeatureFlagService.is_enabled(db, feature_key):
        raise ValidationError(f"{import_type} imports are currently disabled")


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


@router.post("/uploads/multipart", status_code=status.HTTP_201_CREATED)
async def start_multipart_upload(
    body: MultipartStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    if body.type == "module_tsv" and not await FeatureFlagService.is_enabled(db, "imports.local_upload"):
        raise ValidationError("Local module uploads are currently disabled")
    data_set_id = body.data_set_id or 1
    session = initiate_multipart_upload(data_set_id=data_set_id, filename=body.filename, content_type=body.content_type)
    return {"upload_id": session.upload_id, "object_key": session.object_key, "parts": [{"part_number": n, "url": sign_multipart_part(object_key=session.object_key, upload_id=session.upload_id, part_number=n)} for n in range(1, body.part_count + 1)]}


@router.post("/uploads/multipart/{upload_id}/complete", status_code=status.HTTP_200_OK)
async def finish_multipart_upload(upload_id: str, body: MultipartCompletePathRequest, current_user: User = Depends(get_current_user)) -> dict:
    _require_admin(current_user)
    completed = complete_multipart_upload(object_key=body.object_key, upload_id=upload_id, parts=[CompletedPart(p.part_number, p.etag) for p in body.parts], sha256=body.sha256)
    return {"upload_id": completed.upload_id, "object_key": completed.object_key, "sha256": completed.sha256, "parts": [{"part_number": p.part_number, "etag": p.etag} for p in completed.parts]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_import(
    body: ImportCreateRequest,
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

    # Every import type is gated by its own capability flag.  Types whose
    # durable writer is not implemented default to OFF so the caller is
    # rejected up front instead of getting a worker ``fail-closed``.
    await _require_import_type_enabled(db, body.type)

    if body.type == "module_tsv":
        if body.filename.lower().endswith(".xlsx") and not await FeatureFlagService.is_enabled(db, "imports.module_xlsx"):
            raise ValidationError("XLSX module imports are currently disabled")
        if not body.module_key:
            raise ValidationError("module_key is required for module_tsv imports")
        if not body.checksum:
            raise ValidationError("checksum is required for module_tsv imports")
        from ...services.module_schema_registry import (
            SUPPORTED_MODULE_FORMATS,
            detect_format,
            get_schema,
        )

        if get_schema(body.module_key) is None:
            raise ValidationError(f"Unknown module schema '{body.module_key}'")
        # 为什么：多格式导入只接受 .txt/.tsv/.csv/.xlsx，其它扩展名 422。
        if detect_format(body.filename) is None:
            raise ValidationError(
                f"Unsupported module file format for '{body.filename}'; "
                f"expected one of {', '.join(SUPPORTED_MODULE_FORMATS)}"
            )

    task = await create_import_command(
        db,
        actor_id=current_user.id,
        idempotency_key=body.idempotency_key,
        data_set_id=body.data_set_id or 1,
        import_type=body.type,
        filename=body.filename,
        object_key=body.object_key or body.file_path,
        release_id=body.release_id,
        assembly=body.assembly,
        module_key=body.module_key,
        schema_version=body.schema_version,
        checksum=body.checksum,
    )
    await db.commit()
    await db.refresh(task)

    return _task_to_dict(task)


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
    task.completed_at = datetime.now(UTC)
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

    await db.commit()
    await db.refresh(task)

    return _task_to_dict(task)

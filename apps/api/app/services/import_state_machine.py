"""Server-side import state transitions and audit trail."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.auth import AuditLog
from ..models.data_publishing import ImportStatus
from ..models.import_task import ImportTask

IMPORT_TRANSITIONS: dict[ImportStatus, frozenset[ImportStatus]] = {
    ImportStatus.UPLOADING: frozenset({ImportStatus.VALIDATING, ImportStatus.FAILED}),
    ImportStatus.VALIDATING: frozenset({ImportStatus.INGESTING, ImportStatus.FAILED}),
    ImportStatus.INGESTING: frozenset({ImportStatus.READY, ImportStatus.FAILED}),
    ImportStatus.READY: frozenset({ImportStatus.PUBLISHED, ImportStatus.FAILED}),
    ImportStatus.PUBLISHED: frozenset({ImportStatus.ROLLED_BACK}),
    ImportStatus.FAILED: frozenset({ImportStatus.UPLOADING, ImportStatus.VALIDATING, ImportStatus.INGESTING}),
    ImportStatus.ROLLED_BACK: frozenset(),
}


class InvalidStateTransition(ValueError):
    pass


def assert_transition(current: ImportStatus, target: ImportStatus) -> None:
    current = ImportStatus(current)
    target = ImportStatus(target)
    if target not in IMPORT_TRANSITIONS[current]:
        raise InvalidStateTransition(f"{current.value} -> {target.value}")


async def transition_import(db: AsyncSession, *, import_task_id: int, target: ImportStatus,
                            actor_id, evidence: dict | None = None) -> ImportTask:
    task = (await db.execute(select(ImportTask).where(ImportTask.id == import_task_id).with_for_update())).scalar_one()
    current = ImportStatus(task.status)
    assert_transition(current, target)
    task.status = target.value
    if target == ImportStatus.FAILED:
        task.error_detail = evidence or task.error_detail
    db.add(AuditLog(user_id=actor_id, action=f"import_{target.value}", resource_type="import_task",
                    resource_id=str(task.id), old_value={"status": current.value},
                    new_value={"status": target.value, "evidence": evidence or {}}))
    await db.flush()
    return task

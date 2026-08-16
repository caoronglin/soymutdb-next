"""Release assembly and readiness gates.

External builders run before these functions; this service only persists their
evidence and advances the PostgreSQL state machine.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.task_contract import RELEASE_POINTER_CHANGED_TASK
from ..models.auth import AuditLog
from ..models.content import Release, ReleaseStatus
from ..models.data_publishing import ActiveRelease, DataSet, ImportStatus, ReleaseDataSet
from .outbox_service import enqueue_task_event


class ReleaseNotReady(ValueError):
    pass


async def _datasets(db: AsyncSession, release_id: int) -> list[DataSet]:
    result = await db.execute(
        select(DataSet)
        .join(ReleaseDataSet, ReleaseDataSet.data_set_id == DataSet.id)
        .where(ReleaseDataSet.release_id == release_id)
    )
    return list(result.scalars())


async def validate_release(db: AsyncSession, *, release_id: int, actor_id) -> Release:
    release = (await db.execute(select(Release).where(Release.id == release_id).with_for_update())).scalar_one_or_none()
    if release is None:
        raise ReleaseNotReady("release not found")
    datasets = await _datasets(db, release_id)
    if not datasets or any(ds.status != ImportStatus.READY.value for ds in datasets):
        raise ReleaseNotReady("all data sets must be ready")
    if any(not all(obj.get("sha256") and obj.get("etag") for obj in (ds.source_objects or [])) for ds in datasets):
        raise ReleaseNotReady("source objects must be complete")
    release.status = ReleaseStatus.VALIDATED.value
    db.add(AuditLog(user_id=actor_id, action="release_validated", resource_type="release", resource_id=str(release_id), new_value={"status": release.status}))
    await db.flush()
    return release


async def mark_release_ready(db: AsyncSession, *, release_id: int, actor_id, manifest: dict, readiness: dict[str, bool]) -> Release:
    missing = [key for key in ("jbrowse", "blast", "downloads", "api") if readiness.get(key) is not True]
    if missing:
        raise ReleaseNotReady(f"readiness evidence missing: {', '.join(missing)}")
    release = (await db.execute(select(Release).where(Release.id == release_id).with_for_update())).scalar_one_or_none()
    if release is None or release.status != ReleaseStatus.VALIDATED.value:
        raise ReleaseNotReady("release must be validated before ready")
    if not manifest.get("version") or not manifest.get("provenance"):
        raise ReleaseNotReady("manifest is incomplete")
    release.manifest = {**manifest, "readiness": readiness}
    release.status = ReleaseStatus.READY.value
    db.add(AuditLog(user_id=actor_id, action="release_ready", resource_type="release", resource_id=str(release_id), new_value={"readiness": readiness}))
    await db.flush()
    return release


def manifest_digest(manifest: dict | None) -> str | None:
    if not manifest:
        return None
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def release_is_ready(db: AsyncSession, release_id: int) -> bool:
    release = (await db.execute(select(Release).where(Release.id == release_id))).scalar_one_or_none()
    if release is None or release.status != ReleaseStatus.READY.value or not release.manifest:
        return False
    datasets = await _datasets(db, release_id)
    return bool(datasets) and all(ds.status == ImportStatus.READY.value for ds in datasets)


async def publish_release(db: AsyncSession, *, release_id: int, actor_id, reason: str, request_id: str | None = None) -> Release:
    if not reason or not reason.strip():
        raise ReleaseNotReady("publish reason is required")
    async with db.begin():
        pointer = (await db.execute(select(ActiveRelease).where(ActiveRelease.id == 1).with_for_update())).scalar_one_or_none()
        target = (await db.execute(select(Release).where(Release.id == release_id).with_for_update())).scalar_one_or_none()
        if pointer is None or target is None or pointer.release_id == release_id:
            raise ReleaseNotReady("active release transition is invalid")
        if target.status != ReleaseStatus.READY.value or not await release_is_ready(db, release_id):
            raise ReleaseNotReady("release must be ready before publishing")
        previous_id = pointer.release_id
        now = datetime.now(UTC)
        pointer.release_id = target.id
        target.status = ReleaseStatus.PUBLISHED.value
        target.active_at = now
        target.published_at = now
        target.published_by = actor_id
        target.reason = reason
        db.add(AuditLog(user_id=actor_id, action="release_published", resource_type="release", resource_id=str(target.id), old_value={"active_release_id": previous_id}, new_value={"active_release_id": target.id, "reason": reason, "manifest_sha256": manifest_digest(target.manifest)}))
        await enqueue_task_event(
            db,
            aggregate_type="release",
            aggregate_id=str(target.id),
            event_type="release_pointer_changed",
            task_name=RELEASE_POINTER_CHANGED_TASK,
            kwargs={"previous_release_id": previous_id, "release_id": target.id, "request_id": request_id},
        )
        await db.flush()
        return target


async def rollback_release(db: AsyncSession, *, release_id: int, actor_id, reason: str, request_id: str | None = None) -> tuple[Release, Release]:
    if not reason or not reason.strip():
        raise ReleaseNotReady("rollback reason is required")
    async with db.begin():
        pointer = (await db.execute(select(ActiveRelease).where(ActiveRelease.id == 1).with_for_update())).scalar_one_or_none()
        current = (await db.execute(select(Release).where(Release.id == release_id).with_for_update())).scalar_one_or_none()
        if pointer is None or current is None or pointer.release_id != release_id:
            raise ReleaseNotReady("release is not active")
        previous = (await db.execute(select(Release).where(Release.status == ReleaseStatus.PUBLISHED.value, Release.id != release_id, Release.active_at < current.active_at).order_by(Release.active_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
        if previous is None:
            raise ReleaseNotReady("no previous active release to restore")
        pointer.release_id = previous.id
        current.status = ReleaseStatus.ROLLED_BACK.value
        current.rolled_back_at = datetime.now(UTC)
        current.reason = reason
        db.add(AuditLog(user_id=actor_id, action="release_rolled_back", resource_type="release", resource_id=str(current.id), old_value={"from": release_id}, new_value={"to": previous.id, "reason": reason}))
        await enqueue_task_event(
            db,
            aggregate_type="release",
            aggregate_id=str(current.id),
            event_type="release_pointer_changed",
            task_name=RELEASE_POINTER_CHANGED_TASK,
            kwargs={"previous_release_id": release_id, "release_id": previous.id, "request_id": request_id},
        )
        await db.flush()
        return previous, current


__all__ = ["ReleaseNotReady", "mark_release_ready", "publish_release", "rollback_release", "validate_release"]

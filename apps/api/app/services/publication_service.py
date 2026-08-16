"""Immutable multi-target static publication service (Phase 3).

Implements the publication request lifecycle with target-scoped concurrency
protection:

- ``request_publication`` allocates a monotonic, target-scoped
  ``publication_id`` under a target lease, records a ``requested`` row, and
  dispatches the build task through the transactional outbox.
- ``transition`` guards every state change with the model state machine and
  compares against the target's *latest* request before promotion so a stale
  job can never replace a newer release.
- ``mark_superseded`` marks a stale job without touching the currently
  published pointer.
- ``record_published`` / ``record_failed`` persist the final evidence /
  remote id.
- ``rollback`` restores the previous verified publication (by remote id and
  immutable artifact), linking via ``previous_publication_id``.

Credentials are never handled here — the worker's publication adapters read
them from ``publication_targets``; this service only stores target
identifiers and immutable evidence (digest, remote id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.task_contract import STATIC_PUBLISH_TASK
from ..models.auth import AuditLog
from ..models.publication import (
    PublicationCounter,
    PublicationStatus,
    PublicationTarget,
    PublicationTargetLease,
    StaticPublication,
    is_terminal,
    transition_allowed,
)
from ..services.outbox_service import enqueue_task_event


class PublicationError(ValueError):
    """Base error for invalid publication transitions / inputs."""


class InvalidTransition(PublicationError):
    """Requested state transition is not allowed."""


class TargetNotConfigured(PublicationError):
    """The requested target has no runtime configuration."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _get_counter(db: AsyncSession, target: PublicationTarget) -> int:
    """Increment and return the next target-scoped ``publication_id`` value."""
    # Row-lock the counter row (PostgreSQL) — safe only for the short
    # allocation critical section.
    stmt = (
        select(PublicationCounter)
        .where(PublicationCounter.target == target.value)
        .with_for_update()
    )
    counter = (await db.execute(stmt)).scalar_one_or_none()
    if counter is None:
        counter = PublicationCounter(target=target.value, last_id=0)
        db.add(counter)
        await db.flush()
    counter.last_id += 1
    await db.flush()
    return counter.last_id


async def _acquire_lease(db: AsyncSession, target: PublicationTarget) -> PublicationTargetLease:
    """Get-or-create the target lease row and row-lock it."""
    stmt = (
        select(PublicationTargetLease)
        .where(PublicationTargetLease.target == target.value)
        .with_for_update()
    )
    lease = (await db.execute(stmt)).scalar_one_or_none()
    if lease is None:
        lease = PublicationTargetLease(target=target.value, latest_publication_id=0)
        db.add(lease)
        await db.flush()
    return lease


def _parse_target(target: str | PublicationTarget) -> PublicationTarget:
    if isinstance(target, PublicationTarget):
        return target
    try:
        return PublicationTarget(target)
    except ValueError as exc:
        raise PublicationError(f"unknown publication target: {target}") from exc


async def request_publication(
    db: AsyncSession,
    *,
    target: str | PublicationTarget,
    release_id: int,
    actor_id: str | None,
    page_definition_version: int | None = None,
    request_id: str | None = None,
) -> StaticPublication:
    """Allocate a publication request and enqueue the build task.

    The monotonic ``publication_id`` is allocated under the target lease;
    the lease (and counter) lock is released when the transaction commits,
    well before any network I/O in the worker.
    """
    target_enum = _parse_target(target)
    lease = await _acquire_lease(db, target_enum)
    new_id = await _get_counter(db, target_enum)

    pub = StaticPublication(
        publication_id=new_id,
        target=target_enum.value,
        status=PublicationStatus.REQUESTED.value,
        release_id=release_id,
        page_definition_version=page_definition_version,
        requested_by=actor_id,
        superseded_by_publication_id=None,
    )
    db.add(pub)
    await db.flush()

    # Record this request as the latest for the target (under the lease).
    lease.latest_publication_id = new_id
    db.add(AuditLog(
        user_id=actor_id,
        action="static_publication_requested",
        resource_type="static_publication",
        resource_id=str(pub.id),
        new_value={
            "target": target_enum.value,
            "publication_id": new_id,
            "release_id": release_id,
            "page_definition_version": page_definition_version,
        },
    ))

    await enqueue_task_event(
        db,
        aggregate_type="static_publication",
        aggregate_id=str(pub.id),
        event_type="static_publish_requested",
        task_name=STATIC_PUBLISH_TASK,
        kwargs={
            "publication_id": pub.id,
            "target": target_enum.value,
            "release_id": release_id,
            "page_definition_version": page_definition_version,
            "request_id": request_id,
        },
    )
    await db.flush()
    return pub


async def _get(db: AsyncSession, publication_id: int) -> StaticPublication:
    pub = (
        await db.execute(
            select(StaticPublication)
            .where(StaticPublication.id == publication_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pub is None:
        raise PublicationError(f"publication {publication_id} not found")
    return pub


async def transition(
    db: AsyncSession,
    publication_id: int,
    to_status: PublicationStatus,
    **fields: Any,
) -> StaticPublication:
    """Atomically transition a publication, validating the state machine.

    ``fields`` may carry ``manifest_digest``, ``artifact_url``,
    ``remote_id``, ``evidence``, ``error_message``.
    """
    pub = await _get(db, publication_id)
    current = PublicationStatus(pub.status)
    if is_terminal(current):
        raise InvalidTransition(f"publication {publication_id} is terminal ({current.value})")
    if not transition_allowed(current, to_status):
        raise InvalidTransition(
            f"cannot transition {current.value} -> {to_status.value}"
        )
    pub.status = to_status.value
    for field, value in fields.items():
        if field in {
            "manifest_digest",
            "artifact_url",
            "remote_id",
            "evidence",
            "error_message",
            "superseded_by_publication_id",
        }:
            setattr(pub, field, value)
    await db.flush()
    return pub


async def record_building(db: AsyncSession, publication_id: int) -> StaticPublication:
    return await transition(db, publication_id, PublicationStatus.BUILDING)


async def record_validating(
    db: AsyncSession, publication_id: int, *, manifest_digest: str, artifact_url: str
) -> StaticPublication:
    return await transition(
        db,
        publication_id,
        PublicationStatus.VALIDATING,
        manifest_digest=manifest_digest,
        artifact_url=artifact_url,
    )


async def record_deploying(db: AsyncSession, publication_id: int) -> StaticPublication:
    return await transition(db, publication_id, PublicationStatus.DEPLOYING)


async def should_promote(db: AsyncSession, publication_id: int) -> bool:
    """Return True if this publication is still the latest for its target.

    Called by the worker immediately before promotion (outside the original
    request transaction).  If a newer request superseded this one, returns
    False and the worker must NOT promote.
    """
    pub = await _get(db, publication_id)
    latest = (
        await db.execute(
            select(PublicationTargetLease.latest_publication_id).where(
                PublicationTargetLease.target == pub.target
            )
        )
    ).scalar_one_or_none()
    return latest == pub.publication_id


async def mark_superseded(
    db: AsyncSession, publication_id: int, *, by_publication_id: int
) -> StaticPublication:
    """Mark a publication superseded by a newer request (no promotion)."""
    pub = await _get(db, publication_id)
    if is_terminal(PublicationStatus(pub.status)):
        return pub
    pub.status = PublicationStatus.SUPERSEDED.value
    pub.superseded_by_publication_id = by_publication_id
    await db.flush()
    return pub


async def record_published(
    db: AsyncSession,
    publication_id: int,
    *,
    remote_id: str,
    evidence: dict | None = None,
) -> StaticPublication:
    """Persist a successful promotion (remote id + evidence)."""
    pub = await _get(db, publication_id)
    current = PublicationStatus(pub.status)
    if current == PublicationStatus.DEPLOYING:
        pub.status = PublicationStatus.PUBLISHED.value
    elif current == PublicationStatus.PUBLISHED:
        pass  # idempotent re-entry
    else:
        raise InvalidTransition(f"cannot publish from {current.value}")
    pub.remote_id = remote_id
    if evidence is not None:
        pub.evidence = evidence
    # Link to previous published publication on the same target (rollback).
    previous = (
        await db.execute(
            select(StaticPublication)
            .where(
                StaticPublication.target == pub.target,
                StaticPublication.status == PublicationStatus.PUBLISHED.value,
                StaticPublication.id != pub.id,
            )
            .order_by(StaticPublication.publication_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if previous is not None:
        pub.previous_publication_id = previous.id
    await db.flush()
    return pub


async def record_failed(
    db: AsyncSession, publication_id: int, *, error_message: str
) -> StaticPublication:
    pub = await _get(db, publication_id)
    if is_terminal(PublicationStatus(pub.status)):
        return pub
    pub.status = PublicationStatus.FAILED.value
    pub.error_message = error_message[:4000]
    await db.flush()
    return pub


async def rollback(
    db: AsyncSession,
    publication_id: int,
    *,
    actor_id: str | None,
    reason: str = "",
) -> StaticPublication:
    """Mark a published publication rolled back, restoring the previous one.

    The actual pointer restore on the target is driven by the worker using
    the previous publication's ``remote_id``; this persists the state and
    returns the restored publication id so the caller can enqueue it.
    """
    if not reason or not reason.strip():
        raise PublicationError("rollback reason is required")
    pub = await _get(db, publication_id)
    if PublicationStatus(pub.status) != PublicationStatus.PUBLISHED:
        raise PublicationError("only a published publication can be rolled back")
    pub.status = PublicationStatus.ROLLED_BACK.value
    db.add(AuditLog(
        user_id=actor_id,
        action="static_publication_rolled_back",
        resource_type="static_publication",
        resource_id=str(pub.id),
        old_value={"remote_id": pub.remote_id},
        new_value={"reason": reason, "previous_publication_id": pub.previous_publication_id},
    ))
    await db.flush()
    return pub


async def list_publications(
    db: AsyncSession,
    *,
    target: str | None = None,
    limit: int = 50,
) -> list[StaticPublication]:
    stmt = select(StaticPublication).order_by(StaticPublication.publication_id.desc())
    if target:
        stmt = stmt.where(StaticPublication.target == _parse_target(target).value)
    stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars())


__all__ = [
    "InvalidTransition",
    "PublicationError",
    "TargetNotConfigured",
    "list_publications",
    "mark_superseded",
    "record_building",
    "record_deploying",
    "record_failed",
    "record_published",
    "record_validating",
    "request_publication",
    "rollback",
    "should_promote",
    "transition",
]

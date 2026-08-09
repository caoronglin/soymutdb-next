"""Notification model — in-app notification centre entries (D2).

Notifications are written by the worker (via the narrow
``soymutdb_worker.repositories.NotifyStore``) when a background job
completes or fails, and optionally via
``app.services.notification_service.create_notification`` for other
channels (e.g. seed-request events).  The web app polls
``GET /api/v1/notifications`` and renders the bell in the site header.

``type`` is a plain string vocabulary (``blast_completed``,
``blast_failed``, ``analysis_completed``, ``analysis_failed``,
``gwas_completed``, ``gwas_failed``, ``seed_request``, ...) so new kinds
never require a schema migration.  ``link`` is an optional app route the
frontend opens when the entry is clicked (e.g. ``/blast/jobs/{id}``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    #: Optional app route opened on click, e.g. ``/blast/jobs/{job_id}``.
    link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Unread-first listing: (user_id, read_at IS NULL) → (user_id, created_at DESC).
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user={self.user_id} type={self.type!r}>"


__all__ = ["Notification"]

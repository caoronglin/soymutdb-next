"""Transactional outbox model.

Business transactions (e.g. BLAST job submission) write an outbox row in the
*same* database transaction instead of depending on the Celery broker.  A
background dispatcher polls pending rows and forwards them to Celery with a
fixed ``task_id`` equal to the outbox ``event_id``; the worker is idempotent
so a crash between send and acknowledgement only causes a harmless re-send.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, enum_values


class OutboxEventStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: Public event identifier; also used as the Celery ``task_id`` so that
    #: crash-restart re-sends reuse the same task id (worker dedupes).
    event_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        unique=True,
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            OutboxEventStatus,
            name="outbox_event_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=OutboxEventStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    #: Per-claim fencing token.  A fresh value is written for every delivery
    #: attempt so an expired dispatcher cannot finalize a reclaimed event.
    lease_owner: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Celery task id used to send this event (equal to ``event_id``).
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(status = 'processing' AND lease_owner IS NOT NULL "
            "AND lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND lease_owner IS NULL "
            "AND lease_until IS NULL)",
            name="ck_outbox_events_processing_lease",
        ),
        Index("ix_outbox_events_status_created", "status", "created_at"),
        Index(
            "ix_outbox_events_status_lease_until", "status", "lease_until"
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<OutboxEvent id={self.id} event_id={self.event_id} "
            f"type={self.event_type!r} status={self.status!r}>"
        )


__all__ = ["OutboxEvent", "OutboxEventStatus"]

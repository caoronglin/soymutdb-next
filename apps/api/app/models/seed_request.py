"""Seed request contact model (public gene-material request form, D1).

Anyone may submit a request — name / email / institution / country plus a
list of gene IDs (≤ 200, validated at the API boundary) — without an
account.  The API writes the row together with a transactional-outbox event
(see ``app.services.seed_request_service``); the worker renders and sends
the confirmation + admin notification emails (or writes them to
``logs/emails/`` when SMTP is disabled).  Curators advance the small status
machine ``pending → approved/rejected → fulfilled``.

The table is intentionally named ``seed_request_contacts`` rather than
``seed_requests``: migration 0001 already created a ``seed_requests`` table
(legacy authenticated requests against mutant lines, mapped by
``app.models.seed.SeedRequest``).  This module is a separate public contact
lifecycle, so it gets a dedicated table to avoid a schema collision.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, enum_values


class SeedRequestStatus(enum.StrEnum):
    """Lifecycle of a contact-style seed request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"


class SeedRequestContact(Base):
    __tablename__ = "seed_request_contacts"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    institution: Mapped[str] = mapped_column(String(512), nullable=False)
    country: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Requested gene IDs (whitelisted at the API boundary, ≤ 200 entries).
    gene_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(
            SeedRequestStatus,
            name="seed_request_contact_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=SeedRequestStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_seed_request_contacts_status", "status"),
        Index("ix_seed_request_contacts_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<SeedRequestContact id={self.id} status={self.status!r}>"


__all__ = ["SeedRequestContact", "SeedRequestStatus"]

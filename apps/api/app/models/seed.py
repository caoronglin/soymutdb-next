"""Seed inventory and request models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_values


class SeedRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    REJECTED = "rejected"


class SeedInventory(Base, TimestampMixin):
    __tablename__ = "seed_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mutant_line_id: Mapped[int] = mapped_column(
        ForeignKey("mutant_lines.id", ondelete="CASCADE"), nullable=False
    )
    seed_lot: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity_grams: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    harvest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    viability_pct: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    mutant_line = relationship(
        "MutantLine", back_populates="seed_inventory", lazy="joined"
    )

    __table_args__ = (Index("ix_seed_inv_ml", "mutant_line_id"),)

    def __repr__(self) -> str:
        return f"<SeedInventory id={self.id} lot={self.seed_lot!r}>"


class SeedRequest(Base):
    __tablename__ = "seed_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    requester_name: Mapped[str] = mapped_column(String(256), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(320), nullable=False)
    requester_institution: Mapped[str] = mapped_column(String(512), nullable=False)
    mutant_line_id: Mapped[int] = mapped_column(
        ForeignKey("mutant_lines.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_requested: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum(
            SeedRequestStatus,
            name="seed_request_status_enum",
            create_constraint=True,
            values_callable=enum_values,
        ),
        default=SeedRequestStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    mutant_line = relationship(
        "MutantLine", back_populates="seed_requests", lazy="joined"
    )
    reviewer = relationship("User", lazy="joined")

    __table_args__ = (
        Index("ix_seed_req_status", "status"),
        Index("ix_seed_req_email", "requester_email"),
        Index("ix_seed_req_ml", "mutant_line_id"),
    )

    def __repr__(self) -> str:
        return f"<SeedRequest id={self.id} status={self.status}>"


__all__ = [
    "SeedInventory",
    "SeedRequest",
    "SeedRequestStatus",
]

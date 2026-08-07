"""SQLAlchemy 2.0 async declarative base and shared mixins.

All model modules import ``Base`` and the mixin classes from here so that
``Base.metadata`` collects every table for Alembic auto-generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in SoyMutDB."""

    type_annotation_map = {
        str: String,
        uuid.UUID: PG_UUID(as_uuid=True),
    }


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` with timezone-aware defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AuditMixin:
    """Records who created / last modified a row (FK to ``users.id``)."""

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )


class SoftDeleteMixin:
    """Supports logical deletion without removing the row."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("false"),
        nullable=False,
    )


__all__ = [
    "AuditMixin",
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
]

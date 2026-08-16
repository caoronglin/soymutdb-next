"""Release-scoped module data models for schema-driven TSV imports."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ModuleSchema(Base):
    """Server-owned TSV schema definition.

    ``key`` + ``version`` identify an immutable schema.  ``columns`` is a
    list of ``TsvColumn``-compatible dicts; ``unique_key`` names the columns
    that make a logical row unique within a release.
    """

    __tablename__ = "module_schemas"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    unique_key: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )


class ModuleDataRow(Base, TimestampMixin):
    """One validated module-data row scoped to a release."""

    __tablename__ = "module_data_rows"
    __table_args__ = (
        UniqueConstraint(
            "module_key", "release_id", "row_key",
            name="uq_module_data_rows_module_release_row",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_key: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    release_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("releases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    row_key: Mapped[str] = mapped_column(String(512), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


__all__ = ["ModuleDataRow", "ModuleSchema"]

"""Pre-computed gene data cache for fast gene detail page loading."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class GeneDataCache(Base):
    __tablename__ = "gene_data_cache"

    gene_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("genes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    gene: Mapped["Gene"] = relationship(back_populates="data_cache", lazy="joined")  # type: ignore  # noqa: F811

    def __repr__(self) -> str:
        return f"<GeneDataCache gene={self.gene_id!r}>"


__all__ = [
    "GeneDataCache",
]

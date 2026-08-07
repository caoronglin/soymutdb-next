"""Homolog (ortholog/paralog) model for cross-species gene relationships."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .genomic import Gene


class HomologType(str, enum.Enum):
    """Type of homology relationship."""

    ORTHOLOG = "ortholog"
    PARALOG = "paralog"


class GeneHomolog(Base, TimestampMixin):
    __tablename__ = "gene_homologs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gene_id: Mapped[str] = mapped_column(
        ForeignKey("genes.id", ondelete="CASCADE"), nullable=False
    )
    homolog_species: Mapped[str] = mapped_column(String(128), nullable=False)
    homolog_gene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    homolog_type: Mapped[str] = mapped_column(
        Enum(HomologType, name="homolog_type_enum", create_constraint=True),
        nullable=False,
    )
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    gene: Mapped["Gene"] = relationship(back_populates="homologs", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "gene_id", "homolog_species", "homolog_gene_id", "homolog_type",
            name="uq_gene_homolog",
        ),
        Index("ix_homolog_gene", "gene_id"),
        Index("ix_homolog_species", "homolog_species"),
    )

    def __repr__(self) -> str:
        return (
            f"<GeneHomolog gene={self.gene_id!r} "
            f"species={self.homolog_species!r} type={self.homolog_type!r}>"
        )


__all__ = [
    "GeneHomolog",
    "HomologType",
]

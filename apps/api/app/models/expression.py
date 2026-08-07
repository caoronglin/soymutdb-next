"""Expression data models: libraries and per-gene expression values."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, enum_values

if TYPE_CHECKING:
    from .genomic import Assembly, Gene


class TissueType(str, enum.Enum):
    """Tissue types for expression data (currently modelled on soybean)."""

    LEAF = "leaf"
    ROOT = "root"
    SEED = "seed"
    NODULE = "nodule"
    FLOWER = "flower"
    POD = "pod"
    STEM = "stem"
    COTYLEDON = "cotyledon"
    SHOOT_APEX = "shoot_apex"


class TreatmentType(str, enum.Enum):
    """Experimental treatment conditions."""

    CONTROL = "control"
    DROUGHT = "drought"
    SALT = "salt"
    COLD = "cold"
    HEAT = "heat"
    FLOODING = "flooding"
    PATHOGEN = "pathogen"
    NUTRIENT_DEFICIENCY = "nutrient_deficiency"


class ExpressionLibrary(Base, TimestampMixin):
    __tablename__ = "expression_libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[str] = mapped_column(String(128), nullable=False)
    library_name: Mapped[str] = mapped_column(String(256), nullable=False)
    tissue: Mapped[str] = mapped_column(
        Enum(TissueType, name="expression_tissue_enum", create_constraint=True, values_callable=enum_values),
        nullable=False,
    )
    treatment: Mapped[str] = mapped_column(
        Enum(TreatmentType, name="expression_treatment_enum", create_constraint=True, values_callable=enum_values),
        nullable=False,
    )
    developmental_stage: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    study_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    assembly_id: Mapped[int] = mapped_column(
        ForeignKey("assemblies.id", ondelete="CASCADE"), nullable=False
    )
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    assembly: Mapped["Assembly"] = relationship(
        back_populates="expression_libraries", lazy="joined"
    )
    expression_data: Mapped[List["ExpressionData"]] = relationship(
        back_populates="library",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_expr_lib_assembly", "assembly_id"),
        Index("ix_expr_lib_tissue", "tissue"),
        Index("ix_expr_lib_treatment", "treatment"),
    )

    def __repr__(self) -> str:
        return f"<ExpressionLibrary id={self.id} name={self.library_name!r}>"


class ExpressionData(Base, TimestampMixin):
    __tablename__ = "expression_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gene_id: Mapped[str] = mapped_column(
        ForeignKey("genes.id", ondelete="CASCADE"), nullable=False
    )
    library_id: Mapped[int] = mapped_column(
        ForeignKey("expression_libraries.id", ondelete="CASCADE"), nullable=False
    )
    fpkm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    gene: Mapped["Gene"] = relationship(back_populates="expression_data", lazy="joined")
    library: Mapped["ExpressionLibrary"] = relationship(
        back_populates="expression_data", lazy="joined"
    )

    __table_args__ = (
        UniqueConstraint("gene_id", "library_id", name="uq_expression_gene_library"),
        Index("ix_expr_data_gene", "gene_id"),
        Index("ix_expr_data_library", "library_id"),
        Index("ix_expr_data_fpkm", "fpkm"),
    )

    def __repr__(self) -> str:
        return f"<ExpressionData gene={self.gene_id!r} library={self.library_id}>"


__all__ = [
    "ExpressionData",
    "ExpressionLibrary",
    "TissueType",
    "TreatmentType",
]

"""Pydantic v2 schemas for genomic entities: assemblies, chromosomes, genes, transcripts."""

from __future__ import annotations

from datetime import datetime
from ..core.compat import StrEnum

from pydantic import BaseModel, Field, field_validator


class Strand(StrEnum):
    PLUS = "+"
    MINUS = "-"


class GeneFeatureType(StrEnum):
    PROTEIN_CODING = "protein_coding"
    NON_CODING = "non_coding"
    PSEUDOGENE = "pseudogene"
    TRNA = "tRNA"
    RRNA = "rRNA"
    MIRNA = "miRNA"


class AssemblyResponse(BaseModel):
    id: int | str
    name: str
    species: str
    version: str
    description: str | None = None
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChromosomeResponse(BaseModel):
    id: int | str
    assembly_id: int | str
    name: str
    length: int = Field(..., ge=1)
    order: int = Field(default=0, ge=0)

    model_config = {"from_attributes": True}


class GeneResponse(BaseModel):
    id: str | None = None
    gene_id: str | None = None
    assembly_id: str | None = None
    chromosome: str
    name: str | None = None
    biotype: str = "protein_coding"
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    strand: Strand
    description: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: int, info) -> int:  # noqa: ANN001
        start = info.data.get("start")
        if start is not None and v < start:
            raise ValueError("end must be >= start")
        return v


class GeneDetail(GeneResponse):
    transcripts: list["TranscriptResponse"] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    variant_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExonResponse(BaseModel):
    id: str
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    order: int = Field(..., ge=1)

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    id: str
    gene_id: str
    name: str | None = None
    biotype: str = "mRNA"
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    strand: Strand
    is_canonical: bool = False
    exons: list[ExonResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class GeneListParams(BaseModel):
    """Query parameters for paginated gene listing (cursor-based)."""

    assembly_id: str | None = None
    chromosome: str | None = None
    biotype: str | None = None
    search: str | None = Field(default=None, max_length=500)
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class GeneListResponse(BaseModel):
    items: list[GeneResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


GeneDetail.model_rebuild()

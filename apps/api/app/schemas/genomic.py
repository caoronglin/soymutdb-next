"""Pydantic v2 schemas for genomic entities: assemblies, chromosomes, genes, transcripts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.compat import StrEnum


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
    assembly_name: str | None = None
    chromosome: str
    name: str | None = None
    symbol: str | None = None
    biotype: str = "protein_coding"
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    start_pos: int = Field(..., ge=0)
    end_pos: int = Field(..., ge=0)
    strand: Strand
    description: str | None = None
    #: Variants linked to this gene within the resolved release AND assembly.
    #: The React list/detail render it as the row's variant total; it is 0 when
    #: the gene genuinely has no linked variants in that scope.
    variant_count: int = Field(default=0, ge=0)

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _portal_fields(cls, data):  # noqa: ANN001
        if isinstance(data, dict):
            values = dict(data)
            values.setdefault("symbol", values.get("name"))
            values.setdefault("start_pos", values.get("start"))
            values.setdefault("end_pos", values.get("end"))
            return values
        return data

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: int, info) -> int:  # noqa: ANN001
        start = info.data.get("start")
        if start is not None and v < start:
            raise ValueError("end must be >= start")
        return v


class GeneDetail(GeneResponse):
    transcripts: list[TranscriptResponse] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
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


class TranscriptPartResponse(BaseModel):
    """One typed segment of a transcript.

    ``kind`` is the vocabulary the renderers already speak — the portal's
    ``packages/genome-view`` places ``cds`` / ``utr5`` / ``utr3`` boxes and the
    server-side SVG renderer draws the same four. Exposing the database's
    ``part_type`` verbatim would put that mapping in every client.
    """

    kind: Literal["cds", "utr5", "utr3"]
    start: int = Field(..., ge=1)
    end: int = Field(..., ge=1)


class RegionTranscriptResponse(BaseModel):
    """A transcript with its structure, inside one coordinate window."""

    id: str
    name: str | None = None
    biotype: str = "mRNA"
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    strand: Strand
    is_canonical: bool = False
    parts: list[TranscriptPartResponse] = Field(default_factory=list)


class RegionGeneResponse(BaseModel):
    """A gene overlapping the window, with every transcript it models."""

    gene_id: str
    name: str | None = None
    chromosome: str
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=0)
    start_pos: int = Field(..., ge=0)
    end_pos: int = Field(..., ge=0)
    strand: Strand
    biotype: str = "protein_coding"
    transcripts: list[RegionTranscriptResponse] = Field(default_factory=list)


class RegionStructureResponse(BaseModel):
    """The answer to "what is in this window"."""

    assembly_id: int
    assembly_name: str
    assembly_version: str
    chromosome: str
    chromosome_length: int
    start: int = Field(..., ge=1)
    end: int = Field(..., ge=1)
    genes: list[RegionGeneResponse] = Field(default_factory=list)
    #: True when the window is wider than the endpoint will model in full.
    truncated: bool = False


#: Columns the gene list may be ordered by (validated, never interpolated
#: from user text). ``gene_id`` is the default and the only order the keyset
#: cursor is defined for.
GENE_SORT_COLUMNS: tuple[str, ...] = ("gene_id", "symbol", "variant_count")


class GeneListParams(BaseModel):
    """Query parameters for paginated gene listing (cursor-based)."""

    assembly_id: str | None = None
    chromosome: str | None = None
    biotype: str | None = None
    search: str | None = Field(default=None, max_length=500)
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    page: int | None = Field(default=None, ge=1)
    page_size: int | None = Field(default=None, ge=1, le=200)
    # The React gene table renders sortable Gene ID / Symbol / Variant count
    # headers and sends these parameters; they were previously dropped, so the
    # UI showed an unsorted page while claiming a sort order.
    sort_by: str = Field(default="gene_id")
    sort_dir: str = Field(default="asc")

    @field_validator("sort_by")
    @classmethod
    def _validate_sort_by(cls, value: str) -> str:
        if value not in GENE_SORT_COLUMNS:
            raise ValueError(
                f"sort_by must be one of {', '.join(GENE_SORT_COLUMNS)}"
            )
        return value

    @field_validator("sort_dir")
    @classmethod
    def _validate_sort_dir(cls, value: str) -> str:
        lowered = value.lower()
        if lowered not in ("asc", "desc"):
            raise ValueError("sort_dir must be 'asc' or 'desc'")
        return lowered


class GeneListResponse(BaseModel):
    items: list[GeneResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    page: int = 1
    page_size: int = 50
    total: int = 0
    total_pages: int = 0


GeneDetail.model_rebuild()

"""Pydantic v2 schemas for genomic entities: assemblies, chromosomes, genes, transcripts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..core.compat import StrEnum
from .gene_evidence import (
    AnnotationSection,
    EvidenceTag,
    ExpressionSection,
    HomologSection,
    LiteratureSection,
    PhenotypeSection,
    SequenceAvailability,
    VariantSection,
)


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
    #: Per-molecule availability (genomic/CDS/transcript/protein). Always
    #: present; a disabled entry carries a machine-readable ``reason`` instead
    #: of a fabricated sequence.
    sequences: list[SequenceAvailability] = Field(default_factory=list)
    #: How the gene model itself came to exist (predicted/curated/imported).
    #: ``None`` when the source record does not say — never guessed.
    model_evidence: EvidenceTag | None = None
    #: Optional blocks. Each carries its own status, so "this gene has none"
    #: and "this release never imported them" stay distinguishable. Optional on
    #: the wire: an older API build omits them rather than sending empty lists.
    annotation_section: AnnotationSection | None = None
    homolog_section: HomologSection | None = None
    expression_section: ExpressionSection | None = None
    variants_section: VariantSection | None = None
    phenotype_section: PhenotypeSection | None = None
    literature_section: LiteratureSection | None = None


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


class AssemblyMetricReason(StrEnum):
    """Why an assembly statistic has no value.

    A closed set. The reason reaches the reader as translated text, so it has to
    be a code the client can look up; a sentence written by the service would be
    shown untranslated and cannot be covered by a locale check. Keeping the set
    closed on the server is also what stops a new free-text reason from being
    introduced without a client-side translation.
    """

    #: No gene rows exist for this assembly: no annotation was ever imported.
    NO_GENES = "no_genes"
    #: No chromosome rows exist, so there is neither a count nor a size.
    NO_CHROMOSOMES = "no_chromosomes"
    #: ``download_files`` has no assembly dimension to aggregate over.
    NO_LINKED_DOWNLOADS = "no_linked_downloads"


class AssemblyMetric(BaseModel):
    """One assembly-level statistic, with the reason it is unknown.

    ``value`` is ``None`` whenever the number could not be derived from the
    authoritative tables, and a machine-readable ``reason`` then says why. It is
    never defaulted to ``0``: an assembly whose annotation was never imported and
    an assembly that genuinely has no genes are different facts, and once both
    are printed as zero nobody can tell them apart. The two fields are mutually
    exclusive on purpose -- a number with a reason ("we did not count it, but
    here it is") would be a contradiction.
    """

    value: int | None = Field(default=None, ge=0)
    reason: AssemblyMetricReason | None = None

    @model_validator(mode="after")
    def _reason_matches_value(self):  # noqa: ANN201
        if self.value is None and not self.reason:
            raise ValueError("an unknown statistic must carry a reason")
        if self.value is not None and self.reason is not None:
            raise ValueError("a known statistic must not carry a reason")
        return self


class AssemblyStatistics(BaseModel):
    """Counts derived from real rows, scoped to one assembly.

    Every number here is a ``COUNT``/``SUM`` over rows that carry an
    ``assembly_id`` of their own. Nothing is read from ``Release.gene_count`` or
    any other denormalised counter: a release owns several assemblies, so a
    release-level total copied onto each assembly would report the whole
    release's genes once per assembly.

    Each count is an :class:`AssemblyMetric` rather than a bare ``int`` so that
    "we could not count this" survives the trip to the client. A histogram over
    an empty assembly and an assembly whose statistics were never computed both
    used to arrive as ``0``; with the metric shape the second arrives as
    ``{"value": null, "reason": "..."}`` and the page can say so.

    ``download_count`` is always unknown. ``download_files`` has no assembly
    column -- it is linked to a release and its ``category`` is free text -- so
    there is no relation to aggregate over. Guessing an assembly from a category
    string would invent a number, and borrowing the release's download total
    would be the same mistake as borrowing its gene count.

    All five fields are required on purpose. A default of ``AssemblyMetric()``
    is ``value=None, reason=None``, which the metric's own validator rejects, so
    a defaulted field could not even be constructed -- and any value that *did*
    construct would be an unstated measurement. Requiring them moves "somebody
    forgot to say" from the reader's guess to a schema error at write time.
    """

    gene_count: AssemblyMetric
    transcript_count: AssemblyMetric
    chromosome_count: AssemblyMetric
    total_length: AssemblyMetric
    download_count: AssemblyMetric


class AssemblySummaryResponse(AssemblyResponse):
    """An assembly in the resolved release, with its own real counts."""

    release_id: int | None = None
    release_version: str | None = None
    #: Required for the same reason the five metrics are: a defaulted statistics
    #: block would be five unstated numbers, not an empty one.
    statistics: AssemblyStatistics


class AssemblyDetailResponse(AssemblySummaryResponse):
    """One assembly, its counts, and its chromosomes.

    The chromosome list is what makes "the assembly does not exist" and "the
    assembly exists but has no chromosomes" distinguishable answers rather
    than two identical empty payloads.
    """

    chromosomes: list[ChromosomeResponse] = Field(default_factory=list)

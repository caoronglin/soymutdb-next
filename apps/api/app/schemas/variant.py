"""Pydantic v2 schemas for variants, mutant lines, and phenotype data.

Fix vs. reference: ``VariantType`` enum is unified to SNP/INS/DEL/MNV/SV.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ..core.compat import StrEnum

#: Maximum length of an assembly key in the public export contract.
#:
#: The export record stores the resolved assembly in
#: ``variant_exports.assembly_key``, a ``String(64)`` column. A longer name
#: cannot be persisted, so the API rejects it before the write instead of
#: letting the database fail the request with a 500.
MAX_ASSEMBLY_KEY_LENGTH = 64


class VariantType(StrEnum):
    """Unified variant type enum."""

    SNP = "SNP"
    INS = "INS"
    DEL = "DEL"
    MNV = "MNV"
    SV = "SV"


class ConsequenceType(StrEnum):
    MISSENSE = "missense_variant"
    NONSENSE = "stop_gained"
    SYNONYMOUS = "synonymous_variant"
    FRAMESHIFT = "frameshift_variant"
    INFRAME_INSERTION = "inframe_insertion"
    INFRAME_DELETION = "inframe_deletion"
    SPLICE_DONOR = "splice_donor_variant"
    SPLICE_ACCEPTOR = "splice_acceptor_variant"
    INTRON = "intron_variant"
    UTR_5 = "5_prime_UTR_variant"
    UTR_3 = "3_prime_UTR_variant"
    UPSTREAM = "upstream_gene_variant"
    DOWNSTREAM = "downstream_gene_variant"
    INTERGENIC = "intergenic_variant"
    START_LOST = "start_lost"
    STOP_LOST = "stop_lost"


class ImpactLevel(StrEnum):
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    MODIFIER = "MODIFIER"


class VariantResponse(BaseModel):
    """Compact variant representation for list endpoints."""

    id: str | None = None
    assembly_id: str | None = None
    # Assembly key (name) the fact belongs to. ``assembly_id`` above is the
    # legacy numeric slot; this carries the namespace the row actually came
    # from so an "All assemblies" listing can label every row (P1-05).
    assembly: str | None = None
    variant_id: str | None = None
    chromosome: str
    position: int = Field(..., ge=0)
    ref_allele: str = Field(..., min_length=1)
    alt_allele: str = Field(..., min_length=1)
    variant_type: VariantType
    quality: float | None = Field(default=None, ge=0)
    filter_status: str = Field(default="PASS")
    allele_frequency: float | None = Field(default=None, ge=0.0, le=1.0)
    gene_id: str | None = None
    gene_symbol: str | None = None
    consequence: ConsequenceType | None = None
    impact: ImpactLevel | None = None

    model_config = {"from_attributes": True}


class VariantDetail(VariantResponse):
    """Extended variant information with annotation and linked entities."""

    transcript_id: str | None = None
    hgvs_c: str | None = None
    hgvs_p: str | None = None
    sift_score: float | None = Field(default=None, ge=0.0, le=1.0)
    sift_prediction: str | None = None
    depth: int | None = Field(default=None, ge=0)
    genotype: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VariantQueryFilters(BaseModel):
    """Query parameters for filtering and paginating variant queries.

    Uses an authenticated, release/filter-bound keyset cursor – never OFFSET.
    ``limit`` is capped at 200.
    """

    assembly: str | None = Field(
        default=None,
        description="Assembly name (e.g. Wm82.a4.v1). Required for region queries.",
    )
    chromosome: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    ref: str | None = Field(default=None, min_length=1, max_length=4096)
    alt: str | None = Field(default=None, min_length=1, max_length=4096)
    gene_id: str | None = None
    variant_type: VariantType | None = None
    consequence: ConsequenceType | None = None
    impact: ImpactLevel | None = None
    min_af: float | None = Field(default=None, ge=0.0, le=1.0)
    max_af: float | None = Field(default=None, ge=0.0, le=1.0)
    cursor: str | None = Field(
        default=None, description="Opaque signed keyset cursor."
    )
    limit: int = Field(default=100, ge=1, le=200)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: int | None, info) -> int | None:  # noqa: ANN001
        start = info.data.get("start")
        if v is not None and start is not None and v < start:
            raise ValueError("end must be >= start")
        return v

    @field_validator("max_af")
    @classmethod
    def _max_af_gte_min(cls, v: float | None, info) -> float | None:  # noqa: ANN001
        min_af = info.data.get("min_af")
        if v is not None and min_af is not None and v < min_af:
            raise ValueError("max_af must be >= min_af")
        return v


class VariantFilterParams(VariantQueryFilters):
    """Resolved repository filters, not a client request body.

    ``mutant_line_name`` is set after a release-scoped public-id lookup. It is
    never accepted directly from a client; historical hash surrogates are not
    PostgreSQL foreign keys.
    """

    mutant_line_name: str | None = None


class VariantExportFilters(VariantQueryFilters):
    """Public export filters; reject private keys instead of ignoring them."""

    model_config = {"extra": "forbid"}
    mutant_line_public_id: str | None = None
    assembly: str | None = Field(
        default=None,
        description=(
            "Assembly namespace of the exported file (e.g. ``Wm82.a4.v1``). "
            "A named assembly wins; when the request names none, the resolved "
            "release's own assembly scope is used; a request whose release "
            "declares no scope is refused. One export carries exactly one "
            "assembly namespace. The name is checked for length (at most "
            f"{MAX_ASSEMBLY_KEY_LENGTH} characters) and against the release's "
            "own facts: a namespace the release publishes no variants in is "
            "refused, because an artifact without rows would claim a "
            "namespace the release does not have."
        ),
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            "Accepted for compatibility with the variant query filters, but "
            "not applied to an export: an artifact contains every record that "
            "matches the other filters, bounded by the export budget. A "
            "caller that wants a page of rows uses the variant list endpoint."
        ),
    )


class VariantListResponse(BaseModel):
    """Cursor-paginated list of variants."""

    items: list[VariantResponse] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None)
    total_count: int | None = Field(
        default=None, description="May be null for large result sets."
    )
    has_more: bool = Field(default=False)


class MutantLineResponse(BaseModel):
    """Compact public mutant-line representation.

    ``public_id`` is the canonical external identity. The private
    persistence key is never part of this public contract.
    """

    public_id: str
    name: str
    mutagen: str | None = None
    cultivar: str | None = Field(default="Williams 82")
    variant_count: int = Field(default=0, ge=0)

    model_config = {"from_attributes": True}


class MutantLineDetail(MutantLineResponse):
    """Extended mutant line information."""

    species: str = "Glycine max"
    description: str | None = None
    generation: str | None = None
    phenotype_summary: str | None = None
    is_public: bool = True
    created_at: datetime
    updated_at: datetime


class PhenotypeResponse(BaseModel):
    """Public representation of a phenotype observation."""

    id: str
    mutant_line_public_id: str
    trait_category: str
    trait_name: str
    trait_value: str | None = None
    unit: str | None = None
    description: str | None = None

    model_config = {"from_attributes": True}


class ExportRequest(BaseModel):
    """Payload for requesting an asynchronous variant export."""

    format: str = Field(default="tsv", pattern=r"^(vcf|tsv|csv|json|bed)$")
    filters: VariantExportFilters = Field(default_factory=VariantExportFilters)
    compress: bool = True


class ExportResponse(BaseModel):
    """Response after submitting an export job."""

    export_id: str
    status: str
    message: str


class ExportStatusResponse(BaseModel):
    """Owner-visible state of a submitted variant export.

    ``status`` uses the shared job vocabulary (``pending``/``running``/
    ``succeeded``/``failed``).  The artifact's storage key is deliberately
    absent: only a short-lived download URL is handed out, and only to the
    owner or an administrator.
    """

    export_id: str
    status: str
    format: str
    release_key: str
    assembly_key: str | None = None
    record_count: int | None = None
    file_size: int | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None


class ExportDownloadResponse(BaseModel):
    """A short-lived download link for a finished export artifact."""

    export_id: str
    download_url: str
    filename: str
    expires_at: datetime
    expires_in_seconds: int

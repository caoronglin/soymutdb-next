"""Pydantic contracts for the Sequence Tools endpoints.

All inputs are bounded here before any Rust call.  Public coordinates are
1-based inclusive; the Rust kernel uses 0-based half-open internally.  These
schemas never accept a filesystem path, S3 key or arbitrary URL.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MAX_INLINE_SEQUENCE = 1_048_576  # 1 MiB, mirrors the Rust kernel
MAX_PATTERN = 256
MAX_HITS = 1000
MAX_REGIONS = 1000
MAX_ALIGNMENT_CELLS = 10_000_000  # query_len * target_len, mirrors the Rust kernel

SequenceText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_INLINE_SEQUENCE)]
Alphabet = Literal["dna", "rna", "protein"]
AlignmentMode = Literal["local", "global", "semiglobal"]


class EngineMetadata(BaseModel):
    """Implementation identity; distinct from a biological data release."""

    engine: str
    engine_version: str
    request_id: str | None = None


class ReverseComplementRequest(BaseModel):
    sequence: SequenceText
    alphabet: Alphabet = "dna"
    preserve_case: bool = False


class ReverseComplementResponse(BaseModel):
    sequence: str
    length: int
    alphabet: Alphabet
    engine: EngineMetadata


class MatchHit(BaseModel):
    start: int = Field(description="1-based inclusive start")
    end: int = Field(description="1-based inclusive end")
    strand: Literal["+", "-"]
    edit_distance: int = 0


class InlineTarget(BaseModel):
    kind: Literal["inline"] = "inline"
    sequence: SequenceText


Target = Annotated[InlineTarget, Field(discriminator="kind")]


class SequenceMatchRequest(BaseModel):
    pattern: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PATTERN)]
    target: Target
    alphabet: Alphabet = "dna"
    mode: Literal["exact", "approximate"] = "exact"
    both_strands: bool = True
    max_edits: int = Field(default=0, ge=0, le=3)
    iupac_mode: Literal["literal"] = "literal"
    max_hits: int = Field(default=100, ge=1, le=MAX_HITS)


class SequenceMatchResponse(BaseModel):
    matches: list[MatchHit]
    count: int
    limited: bool
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    method: Literal["exact", "approximate"]
    engine: EngineMetadata


class ScoringConfig(BaseModel):
    match: int = Field(default=2, ge=-100, le=100)
    mismatch: int = Field(default=-3, ge=-100, le=100)
    gap_open: int = Field(default=-5, ge=-100, le=100)
    gap_extend: int = Field(default=-1, ge=-100, le=100)


class SequenceAlignRequest(BaseModel):
    query: SequenceText
    target: SequenceText
    alphabet: Alphabet = "dna"
    mode: AlignmentMode = "local"
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)


class SequenceAlignResponse(BaseModel):
    score: int
    query_range: tuple[int, int]
    target_range: tuple[int, int]
    cigar: str
    identity: float
    mode: AlignmentMode
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    engine: EngineMetadata


class SequenceStatsRequest(BaseModel):
    sequence: SequenceText
    alphabet: Alphabet = "dna"
    ambiguous_gc_policy: Literal["exclude", "include"] = "exclude"


class SequenceStatsResponse(BaseModel):
    length: int
    gc_count: int
    at_count: int
    ambiguous_count: int
    a: int
    c: int
    g: int
    t: int
    denominator: int
    gc_fraction: float
    engine: EngineMetadata


class OrfRequest(BaseModel):
    sequence: SequenceText
    min_len: int = Field(default=90, ge=3, le=MAX_INLINE_SEQUENCE)
    limit: int = Field(default=1000, ge=1, le=1000)


class OrfCandidate(BaseModel):
    start: int
    end: int
    strand: Literal["+", "-"]
    frame: int


class OrfResponse(BaseModel):
    candidates: list[OrfCandidate]
    count: int
    engine: EngineMetadata


class TranslateRequest(BaseModel):
    sequence: SequenceText
    genetic_code_id: int = Field(default=1, ge=1, le=100)
    frame: int = Field(default=0, ge=0, le=2)


class TranslateResponse(BaseModel):
    protein: str
    genetic_code_id: int
    frame: int
    warnings: list[str]
    codons: int
    trailing_bases: int
    engine: EngineMetadata


class KmerRequest(BaseModel):
    sequence: SequenceText
    k: int = Field(default=4, ge=1, le=32)
    canonical: bool = True
    ambiguity_policy: Literal["skip", "reject"] = "skip"
    max_items: int = Field(default=1000, ge=1, le=1000)


class KmerItem(BaseModel):
    kmer: str
    count: int


class KmerResponse(BaseModel):
    k: int
    canonical: bool
    total_windows: int
    valid_windows: int
    skipped_windows: int
    distinct_kmers: int
    items: list[KmerItem]
    limited: bool
    engine: EngineMetadata


class SequenceCapabilitiesResponse(BaseModel):
    """Supported algorithms, formats and limits; never internal paths."""

    available: bool
    engine: str | None = None
    engine_version: str | None = None
    reason: str | None = None
    max_inline_sequence: int = MAX_INLINE_SEQUENCE
    max_pattern: int = MAX_PATTERN
    max_hits: int = MAX_HITS
    max_regions: int = MAX_REGIONS
    max_alignment_cells: int = MAX_ALIGNMENT_CELLS
    k_range: tuple[int, int] = (1, 32)
    genetic_codes: list[int] = Field(default_factory=lambda: [1])
    coordinate_system_internal: str = "0-based-half-open"
    coordinate_system_public: str = "1-based-inclusive"
    # Every live POST operation must appear here, or a client enumerating
    # `programs` cannot discover the endpoint. The list is the conservative
    # baseline both engines answer; the Biopython engine additionally reports
    # its wider codon-table set at runtime.
    programs: list[str] = Field(
        default_factory=lambda: [
            "reverse-complement",
            "match",
            "align",
            "stats",
            "orfs",
            "translate",
            "kmers",
            "inspect",
            "intervals/overlap",
            "convert",
            "restriction-sites",
            "protein-properties",
            "melting-temp",
            "multiple-alignment",
            "tree",
        ]
    )
    formats: list[str] = Field(default_factory=lambda: ["fasta", "fastq", "bed"])


class IntervalRegion(BaseModel):
    start: int = Field(ge=1, description="1-based inclusive start")
    end: int = Field(ge=1, description="1-based inclusive end")


class OverlapRequest(BaseModel):
    assembly: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    reference_name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    regions: list[IntervalRegion] = Field(min_length=1, max_length=MAX_REGIONS)
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    annotation_type: Literal["gene"] = "gene"
    mode: Literal["hits", "count"] = "hits"
    max_hits: int = Field(default=100, ge=1, le=MAX_HITS)


class OverlapHit(BaseModel):
    public_id: str
    start: int
    end: int
    overlap_bp: int
    source: str


class OverlapQueryResult(BaseModel):
    query: IntervalRegion
    overlap_count: int
    covered_bp: int
    # None means the caller did not request per-record hits (mode='count');
    # [] means hits were requested and the region had none. spec §7.3.
    hits: list[OverlapHit] | None = None
    limited: bool


class OverlapResponse(BaseModel):
    assembly: str
    release: str
    coordinate_system: Literal["1-based-inclusive"] = "1-based-inclusive"
    queries: list[OverlapQueryResult]
    engine: EngineMetadata


class FormatInspectRequest(BaseModel):
    """Bounded raw bytes as a list of integers (no file paths / URLs)."""

    fmt: Literal["fasta", "fastq", "bed"]
    data: str = Field(description="Base64-encoded file content, ≤1 MiB")


class FormatInspectResponse(BaseModel):
    fmt: Literal["fasta", "fastq", "bed"]
    valid: bool
    record_count: int
    truncated: bool
    records: list[dict[str, object]] = Field(default_factory=list)
    engine: EngineMetadata


# ---------------------------------------------------------------------------
# Capabilities beyond the original kernel: format conversion, restriction
# enzymes, protein properties, primer Tm and multiple alignment/trees.
# ---------------------------------------------------------------------------

#: Short oligos only: beyond this the thermodynamic tables are not a primer Tm.
MAX_PRIMER_LENGTH = 200
#: Defensive bound on the number of sequences one alignment request may carry.
MAX_ALIGNMENT_SEQUENCES = 50


class ConvertFormatRequest(BaseModel):
    data: SequenceText
    source_format: Literal["fasta", "genbank", "embl", "tab"] = "fasta"
    target_format: Literal["fasta", "genbank", "embl", "tab"] = "genbank"
    max_records: int = Field(default=100, ge=1, le=1000)


class ConvertFormatResponse(BaseModel):
    source_format: str
    target_format: str
    record_count: int
    total_records: int
    limited: bool
    output: str
    engine: EngineMetadata


class RestrictionRequest(BaseModel):
    sequence: SequenceText
    #: Empty means "scan every known enzyme and report the ones with a site".
    enzymes: Annotated[list[str], Field(max_length=200)] = Field(default_factory=list)
    circular: bool = False
    max_hits: int = Field(default=1000, ge=1, le=MAX_HITS)


class RestrictionEnzymeResult(BaseModel):
    enzyme: str
    site: str
    cut_positions: list[int]
    site_starts: list[int]
    count: int
    limited: bool


class RestrictionResponse(BaseModel):
    sequence_length: int
    circular: bool
    enzyme_count: int
    total_cut_sites: int
    enzymes: list[RestrictionEnzymeResult]
    limited: bool
    engine: EngineMetadata


class ProteinPropertiesRequest(BaseModel):
    protein: Annotated[str, StringConstraints(min_length=1, max_length=MAX_INLINE_SEQUENCE)]


class ProteinPropertiesResponse(BaseModel):
    length: int
    molecular_weight: float
    isoelectric_point: float
    aromaticity: float
    instability_index: float
    gravy: float
    extinction_coefficient: list[int]
    amino_acid_composition: dict[str, float]
    engine: EngineMetadata


class MeltingTempRequest(BaseModel):
    sequence: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_PRIMER_LENGTH)
    ]
    method: Literal["wallace", "gc", "nearest_neighbor"] = "nearest_neighbor"
    dna_conc_nm: float = Field(default=50.0, gt=0, le=10_000)
    salt_conc_mm: float = Field(default=50.0, gt=0, le=5_000)


class MeltingTempResponse(BaseModel):
    method: str
    length: int
    gc_fraction: float
    melting_temp_c: float
    dna_conc_nm: float
    salt_conc_mm: float
    engine: EngineMetadata


class MultipleAlignmentRequest(BaseModel):
    sequences: Annotated[
        list[SequenceText], Field(min_length=2, max_length=MAX_ALIGNMENT_SEQUENCES)
    ]
    alphabet: Alphabet = "dna"
    mode: AlignmentMode = "global"


class MultipleAlignmentResponse(BaseModel):
    aligned_sequences: list[str]
    column_count: int
    sequence_count: int
    method: str
    mode: str
    distance_matrix: list[list[float]]
    identity_matrix: list[list[float]]
    engine: EngineMetadata


class TreeRequest(BaseModel):
    sequences: Annotated[
        list[SequenceText], Field(min_length=3, max_length=MAX_ALIGNMENT_SEQUENCES)
    ]
    labels: Annotated[list[str], Field(max_length=MAX_ALIGNMENT_SEQUENCES)] | None = None
    alphabet: Alphabet = "dna"


class TreeResponse(BaseModel):
    newick: str
    leaf_count: int
    labels: list[str]
    distance_model: str
    method: str
    caveat: str
    engine: EngineMetadata

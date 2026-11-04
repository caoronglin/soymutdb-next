"""Pydantic v2 schemas for the population-genetics tool endpoints.

Three public, read-only tools (mirroring the public ``/tools/seqfetch``
pattern) that aggregate the PostgreSQL ``variant_facts`` data:

- ``POST /api/v1/tools/ld`` – LD heatmap (r² matrix + variant coordinates).
- ``POST /api/v1/tools/diversity`` – nucleotide diversity (π / θ) per
  region or gene.
- ``POST /api/v1/tools/allelefreq`` – per-variant allele frequencies.

A query targets either a ``gene_id`` or an explicit
``assembly + chromosome + start + end`` interval; exactly one mode is
required and intervals are capped at 50 Mb (defense against runaway scans).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

#: Hard ceiling for a single interval scan (base pairs).
MAX_REGION_SPAN: int = 50_000_000
#: Maximum number of variants returned by one query.
MAX_VARIANTS: int = 50_000


class RegionQuery(BaseModel):
    """Base region selector: either ``gene_id`` or an explicit interval."""

    gene_id: str | None = Field(default=None, max_length=64)
    assembly: str | None = Field(default=None, max_length=128)
    chromosome: str | None = Field(default=None, max_length=64)
    start: int | None = Field(default=None, ge=1)
    end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_region_mode(self) -> RegionQuery:
        has_gene = self.gene_id is not None
        has_interval = (
            self.assembly is not None
            or self.chromosome is not None
            or self.start is not None
            or self.end is not None
        )
        if has_gene == has_interval:
            raise ValueError(
                "provide exactly one of 'gene_id' or an assembly+chromosome+start+end interval"
            )
        if has_interval:
            missing = [
                name
                for name, value in (
                    ("assembly", self.assembly),
                    ("chromosome", self.chromosome),
                    ("start", self.start),
                    ("end", self.end),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "interval mode requires all of assembly/chromosome/start/end; "
                    f"missing: {missing}"
                )
            assert self.start is not None and self.end is not None
            if self.start > self.end:
                raise ValueError("start must be <= end")
            if self.end - self.start + 1 > MAX_REGION_SPAN:
                raise ValueError(
                    f"interval span exceeds the {MAX_REGION_SPAN}-bp limit"
                )
        return self


class AlleleFreqRequest(RegionQuery):
    """Allele-frequency query (per locus / gene / interval)."""

    max_variants: int = Field(default=10_000, ge=1, le=MAX_VARIANTS)


class AlleleFreqVariant(BaseModel):
    variant_id: str
    assembly: str = Field(
        title="Assembly",
        description=(
            # The line breaks are part of the published description: the
            # committed OpenAPI snapshot spells this field that way.
            "Assembly namespace the variant was read from.\n\n"
            "`variant_id` is only unique per (release, assembly); a row that travels\n"
            "without its namespace cannot be identified once two scopes meet."
        )
    )
    chromosome: str
    position: int
    ref_allele: str
    alt_allele: str
    allele_frequency: float | None
    variant_type: str = "SNP"
    gene_id: str | None = None


class AlleleFreqResponse(BaseModel):
    source: str  # "gene" | "interval"
    gene_id: str | None = None
    assembly: str
    chromosome: str
    start: int
    end: int
    n_variants: int
    variants: list[AlleleFreqVariant]


class DiversityRequest(RegionQuery):
    """Nucleotide-diversity query.

    ``sample_size`` enables the Watterson θ estimate (θ = S / a_n, where
    a_n = sum(1/k, k=1..n-1)); it is ``None`` when the sample size is
    unknown, in which case only π and the segregating-site count are
    reported.  ``window_size`` (bp, default 0 = no windows) bins π per
    window for plotting.
    """

    sample_size: int | None = Field(default=None, ge=2, le=1_000_000)
    window_size: int = Field(default=0, ge=0)


class DiversityWindow(BaseModel):
    start: int
    end: int
    n_variants: int
    segregating_sites: int
    pi: float


class DiversityResponse(BaseModel):
    source: str
    gene_id: str | None = None
    assembly: str
    chromosome: str
    start: int
    end: int
    n_bp: int
    n_variants: int
    segregating_sites: int
    #: π per base pair: sum(2pq) / region length (monomorphic positions
    #: contribute 0).  ``None`` when no polymorphic sites exist.
    pi: float | None
    #: π averaged over polymorphic sites only (2pq per site).
    pi_per_site: float | None
    #: Watterson's θ (per bp) – only when ``sample_size`` is provided.
    theta: float | None
    windows: list[DiversityWindow] | None = None


class GenotypeMatrix(BaseModel):
    """Inline genotype matrix for LD computation.

    ``sample_ids`` (rows) × ``variant_ids`` (columns); each value is the
    allele dosage (0/1/2).  Missing genotypes are not allowed – complete
    rows are required (the service rejects matrices with missing calls).
    """

    sample_ids: list[str] = Field(..., min_length=2, max_length=10_000)
    variant_ids: list[str] = Field(..., min_length=2, max_length=2_000)
    values: list[list[int]]

    @model_validator(mode="after")
    def _validate_shape_and_values(self) -> GenotypeMatrix:
        n_samples = len(self.sample_ids)
        n_variants = len(self.variant_ids)
        if len(self.values) != n_samples:
            raise ValueError(
                f"values must have {n_samples} rows (one per sample)"
            )
        for row in self.values:
            if len(row) != n_variants:
                raise ValueError(
                    f"each row must have {n_variants} values (one per variant)"
                )
            for value in row:
                if value not in (0, 1, 2):
                    raise ValueError("genotype values must be 0, 1 or 2 (dosage)")
        return self


class LdRequest(RegionQuery):
    """LD query: a region (or gene) plus an optional inline genotype matrix.

    The ``variant_facts`` store carries per-variant allele frequencies but no
    per-sample genotype calls, so pairwise r² cannot be derived from the
    database alone: clients that hold genotype data supply it inline via
    ``genotypes``; without it the response returns ``r_squared: null`` with a
    ``note`` explaining what is needed (the variant coordinates are still
    returned for plotting).
    """

    genotypes: GenotypeMatrix | None = None


class LdVariant(BaseModel):
    variant_id: str
    assembly: str = Field(
        title="Assembly",
        description="Assembly namespace the variant was read from (see AlleleFreqVariant).",
    )
    chromosome: str
    position: int
    ref_allele: str
    alt_allele: str


class LdResponse(BaseModel):
    source: str
    gene_id: str | None = None
    assembly: str
    chromosome: str
    start: int
    end: int
    n_variants: int
    variants: list[LdVariant]
    #: Pairwise LD r² matrix (n_variants × n_variants, upper triangle
    #: mirrored) computed from the inline genotype matrix; ``None`` when no
    #: genotype data is available.
    r_squared: list[list[float]] | None = None
    note: str | None = None
    details: dict[str, Any] | None = None

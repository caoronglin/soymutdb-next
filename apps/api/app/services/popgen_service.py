"""Population-genetics service: LD, nucleotide diversity, allele frequencies.

Data sources (all PostgreSQL, the authoritative runtime store):

* relational metadata (gene → chromosome/interval resolution, release scope)
  from the PostgreSQL identity/relationship tables;
* per-variant rows from the native PostgreSQL ``variant_facts`` projection
  (``allele_frequency`` / ``ref_allele`` / ``alt_allele``) via the
  :class:`app.services.postgres_variant_service.PostgresVariantService` region
  query.

All numeric aggregation happens in numpy with small, pure helpers that are
directly unit-testable.

Design notes (honest about the data model):
- ``variant_facts`` stores **per-variant allele frequencies, not per-sample
  genotypes**.  Allele frequencies and nucleotide diversity (π = Σ 2pq per
  bp, θ = S/a_n with an explicit sample size) are therefore fully derivable;
  pairwise LD r² is **not** derivable from allele frequencies alone.  The LD
  endpoint accepts an inline genotype matrix (dosage 0/1/2) and computes
  r² = squared Pearson correlation of dosage vectors (HWE approximation);
  without one it returns ``r_squared: null`` plus a clear note, together
  with the variant coordinates for plotting.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.genomic import Assembly, Chromosome, Gene
from ..schemas.popgen import (
    MAX_VARIANTS,
    AlleleFreqRequest,
    AlleleFreqResponse,
    AlleleFreqVariant,
    DiversityRequest,
    DiversityResponse,
    DiversityWindow,
    LdRequest,
    LdResponse,
    LdVariant,
)
from .postgres_variant_service import PostgresVariantService
from .release_context import ReleaseContext

#: Column names returned by ``query_variants_by_region`` that popgen reads.
_REGION_COLUMNS = frozenset(
    {
        "variant_id",
        "chromosome",
        "position",
        "ref_allele",
        "alt_allele",
        "variant_type",
        "allele_frequency",
        "gene_id",
        "gene_symbol",
    }
)


class PopGenService:
    """Population-genetics aggregation over the variants store."""

    def __init__(self, variant_service: PostgresVariantService | None = None) -> None:
        self.variant_service = variant_service or PostgresVariantService()

    # ------------------------------------------------------------------ #
    # Region resolution
    # ------------------------------------------------------------------ #

    async def _resolve_region(
        self,
        db: AsyncSession,
        request: AlleleFreqRequest | DiversityRequest | LdRequest,
        *,
        release_context: ReleaseContext,
    ) -> dict[str, Any]:
        """Resolve a request into ``(assembly, chromosome, start, end, source)``.

        ``source`` is ``"gene"`` when resolved through ``genes`` /
        ``chromosomes`` / ``assemblies`` (PostgreSQL), ``"interval"`` when
        the client supplied the coordinates directly.
        """
        if request.gene_id is not None:
            stmt = (
                select(Gene)
                .join(Assembly, Gene.assembly_id == Assembly.id)
                .where(
                    Gene.accession == request.gene_id,
                    Assembly.release_id == release_context.release_id,
                )
            )
            if request.assembly is not None:
                stmt = stmt.where(Assembly.name == request.assembly)
            result = await db.execute(stmt)
            genes = list(result.scalars().all())
            if not genes:
                raise NotFoundError(f"Gene {request.gene_id!r} not found")
            if len(genes) > 1:
                raise ValidationError(
                    f"Gene {request.gene_id!r} exists in multiple assemblies; "
                    "supply an explicit 'assembly'",
                    details={"code": "ambiguous_assembly"},
                )
            gene = genes[0]
            assembly: Assembly | None = getattr(gene, "assembly", None)
            chromosome: Chromosome | None = getattr(gene, "chromosome", None)
            if assembly is None or chromosome is None:
                raise NotFoundError(f"Gene {request.gene_id!r} has no assembly/chromosome")
            return {
                "assembly": assembly.name,
                "chromosome": chromosome.name,
                "start": int(gene.start),
                "end": int(gene.end),
                "source": "gene",
                "gene_id": gene.accession,
            }

        assert request.assembly is not None
        assert request.chromosome is not None
        assert request.start is not None
        assert request.end is not None
        return {
            "assembly": request.assembly,
            "chromosome": request.chromosome,
            "start": request.start,
            "end": request.end,
            "source": "interval",
            "gene_id": None,
        }

    # ------------------------------------------------------------------ #
    # Shared variant fetch
    # ------------------------------------------------------------------ #

    async def _fetch_variants(
        self,
        db: AsyncSession,
        request: AlleleFreqRequest | DiversityRequest | LdRequest,
        *,
        release_context: ReleaseContext,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Fetch region + variant rows for *request* (capped at MAX_VARIANTS)."""
        region = await self._resolve_region(
            db,
            request,
            release_context=release_context,
        )
        rows = await self.variant_service.query_variants_by_region(
            release_context=release_context,
            assembly=region["assembly"],
            chromosome=region["chromosome"],
            start=region["start"],
            end=region["end"],
            max_results=MAX_VARIANTS,
        )
        return region, rows

    @staticmethod
    def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise region rows to plain floats/ints (PostgreSQL may return
        ``Decimal``/``None`` values)."""
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            af = row.get("allele_frequency")
            cleaned.append(
                {
                    "variant_id": str(row.get("variant_id", "")),
                    "chromosome": str(row.get("chromosome", "")),
                    "position": int(row.get("position", 0)),
                    "ref_allele": str(row.get("ref_allele", "")),
                    "alt_allele": str(row.get("alt_allele", "")),
                    "variant_type": str(row.get("variant_type", "SNP")),
                    "gene_id": row.get("gene_id"),
                    "allele_frequency": float(af) if af is not None else None,
                }
            )
        return cleaned

    # ------------------------------------------------------------------ #
    # Allele frequencies
    # ------------------------------------------------------------------ #

    async def allele_frequencies(
        self,
        db: AsyncSession,
        request: AlleleFreqRequest,
        *,
        release_context: ReleaseContext,
    ) -> AlleleFreqResponse:
        """Return per-variant allele frequencies for a gene / interval."""
        region, rows = await self._fetch_variants(
            db,
            request,
            release_context=release_context,
        )
        variants = [
            AlleleFreqVariant(
                variant_id=r["variant_id"],
                chromosome=r["chromosome"],
                position=r["position"],
                ref_allele=r["ref_allele"],
                alt_allele=r["alt_allele"],
                allele_frequency=r["allele_frequency"],
                variant_type=r["variant_type"],
                gene_id=r["gene_id"],
            )
            for r in self._clean_rows(rows)[: request.max_variants]
        ]
        return AlleleFreqResponse(
            source=region["source"],
            gene_id=region["gene_id"],
            assembly=region["assembly"],
            chromosome=region["chromosome"],
            start=region["start"],
            end=region["end"],
            n_variants=len(variants),
            variants=variants,
        )

    # ------------------------------------------------------------------ #
    # Nucleotide diversity
    # ------------------------------------------------------------------ #

    async def diversity(
        self,
        db: AsyncSession,
        request: DiversityRequest,
        *,
        release_context: ReleaseContext,
    ) -> DiversityResponse:
        """Compute nucleotide diversity (π) and Watterson's θ for a region.

        π is summed per polymorphic site as 2·p·(1−p) (expected
        heterozygosity under HWE) and divided by the region length in bp
        (monomorphic positions contribute 0).  θ = S / a_n requires an
        explicit ``sample_size`` (the store does not record it).
        """
        region, rows = await self._fetch_variants(
            db,
            request,
            release_context=release_context,
        )
        variants = self._clean_rows(rows)
        n_bp = region["end"] - region["start"] + 1

        allele_freqs = [
            r["allele_frequency"]
            for r in variants
            if r["allele_frequency"] is not None
        ]
        pi_sum, pi_per_site, segregating = compute_diversity_stats(allele_freqs)

        theta: float | None = None
        if request.sample_size is not None and segregating > 0:
            theta = watterson_theta(segregating, request.sample_size, n_bp=n_bp)

        windows: list[DiversityWindow] | None = None
        if request.window_size and request.window_size > 0:
            windows = compute_diversity_windows(
                variants, region["start"], region["end"], request.window_size
            )

        return DiversityResponse(
            source=region["source"],
            gene_id=region["gene_id"],
            assembly=region["assembly"],
            chromosome=region["chromosome"],
            start=region["start"],
            end=region["end"],
            n_bp=n_bp,
            n_variants=len(variants),
            segregating_sites=segregating,
            pi=round(pi_sum / n_bp, 10) if pi_sum else 0.0,
            pi_per_site=round(pi_per_site, 10) if pi_per_site is not None else None,
            theta=round(theta, 10) if theta is not None else None,
            windows=windows,
        )

    # ------------------------------------------------------------------ #
    # LD
    # ------------------------------------------------------------------ #

    async def ld(
        self,
        db: AsyncSession,
        request: LdRequest,
        *,
        release_context: ReleaseContext,
    ) -> LdResponse:
        """Return LD r² (inline genotype matrix) or a clear note + variant
        coordinates when no genotype data is available."""
        region, rows = await self._fetch_variants(
            db,
            request,
            release_context=release_context,
        )
        variants = self._clean_rows(rows)

        variant_rows = [
            LdVariant(
                variant_id=r["variant_id"],
                chromosome=r["chromosome"],
                position=r["position"],
                ref_allele=r["ref_allele"],
                alt_allele=r["alt_allele"],
            )
            for r in variants
        ]

        if request.genotypes is None:
            return LdResponse(
                source=region["source"],
                gene_id=region["gene_id"],
                assembly=region["assembly"],
                chromosome=region["chromosome"],
                start=region["start"],
                end=region["end"],
                n_variants=len(variant_rows),
                variants=variant_rows,
                r_squared=None,
                note=(
                    "variant_facts stores per-variant allele frequencies, not "
                    "per-sample genotypes; pairwise LD r² cannot be derived "
                    "from it. Supply an inline genotype matrix (dosage 0/1/2) "
                    "via the 'genotypes' field to compute r²."
                ),
            )

        matrix = request.genotypes
        r2 = compute_ld_r2(matrix.values)
        return LdResponse(
            source=region["source"],
            gene_id=region["gene_id"],
            assembly=region["assembly"],
            chromosome=region["chromosome"],
            start=region["start"],
            end=region["end"],
            n_variants=len(matrix.variant_ids),
            variants=[
                LdVariant(
                    variant_id=vid,
                    chromosome=region["chromosome"],
                    position=0,
                    ref_allele="",
                    alt_allele="",
                )
                for vid in matrix.variant_ids
            ],
            r_squared=[[round(v, 6) for v in row] for row in r2],
            note=None,
            details={
                "n_samples": len(matrix.sample_ids),
                "n_variants": len(matrix.variant_ids),
                "statistic": (
                    "r2 = squared Pearson correlation of allele dosages "
                    "(HWE approximation)"
                ),
            },
        )


# ---------------------------------------------------------------------------
# Pure numeric helpers (numpy-free implementations for tiny inputs; the
# worker-side GWAS code uses numpy – here inputs are capped at 50k rows so a
# plain-python pass is safe and dependency-light).
# ---------------------------------------------------------------------------


def compute_diversity_stats(allele_freqs: list[float]) -> tuple[float, float | None, int]:
    """Return ``(pi_sum, pi_per_site, segregating_sites)``.

    - ``pi_sum`` = Σ 2·p·(1−p) over polymorphic sites (0 < p < 1).
    - ``pi_per_site`` = mean of 2·p·(1−p) over polymorphic sites (``None``
      when there are none).
    - ``segregating_sites`` = number of polymorphic sites.
    """
    per_site: list[float] = []
    for af in allele_freqs:
        if af is None or not (0.0 < af < 1.0):
            continue
        per_site.append(2.0 * af * (1.0 - af))
    pi_sum = sum(per_site)
    pi_per_site = pi_sum / len(per_site) if per_site else None
    return pi_sum, pi_per_site, len(per_site)


def harmonic_sum(n: int) -> float:
    """a_n = Σ_{k=1..n-1} 1/k (normalising constant of Watterson's θ)."""
    return sum(1.0 / k for k in range(1, n))


def watterson_theta(
    segregating_sites: int, sample_size: int, *, n_bp: int | None = None
) -> float:
    """Watterson's θ = S / a_n (per-bp when *n_bp* is given)."""
    if sample_size < 2:
        raise ValidationError("sample_size must be >= 2 for Watterson's theta")
    a_n = harmonic_sum(sample_size)
    if a_n <= 0:
        return 0.0
    theta = segregating_sites / a_n
    if n_bp:
        theta /= n_bp
    return theta


def compute_ld_r2(genotypes: list[list[int]]) -> list[list[float]]:
    """Compute pairwise LD r² from a dosage matrix.

    ``genotypes`` is ``samples × variants`` with values in {0, 1, 2};
    r²(i, j) = squared Pearson correlation of the two dosage vectors
    (the HWE-based approximation used by standard LD tools for biallelic
    SNPs).  Returns a symmetric ``variants × variants`` matrix.
    """
    n_samples = len(genotypes)
    n_variants = len(genotypes[0]) if genotypes else 0
    if n_samples < 2:
        raise ValidationError("at least 2 samples are required for LD")
    if n_variants < 2:
        raise ValidationError("at least 2 variants are required for LD")

    means = [sum(row[j] for row in genotypes) / n_samples for j in range(n_variants)]
    covs: list[list[float]] = [[0.0] * n_variants for _ in range(n_variants)]

    for i in range(n_variants):
        covs[i][i] = 1.0
        for j in range(i + 1, n_variants):
            num = sum(
                (row[i] - means[i]) * (row[j] - means[j]) for row in genotypes
            )
            den_i = math.sqrt(
                sum((row[i] - means[i]) ** 2 for row in genotypes)
            )
            den_j = math.sqrt(
                sum((row[j] - means[j]) ** 2 for row in genotypes)
            )
            r2 = (num / (den_i * den_j)) ** 2 if den_i > 0 and den_j > 0 else 0.0
            covs[i][j] = r2
            covs[j][i] = r2
    return covs


def compute_diversity_windows(
    variants: list[dict[str, Any]],
    region_start: int,
    region_end: int,
    window_size: int,
) -> list[DiversityWindow]:
    """Bin variants into fixed-size windows and compute π per window.

    ``variants`` are cleaned rows (``position`` / ``allele_frequency``);
    π is 2·p·(1−p) summed over polymorphic sites, divided by the window
    length in bp.  Empty windows are skipped.
    """
    windows: list[DiversityWindow] = []
    cursor = region_start
    bucket_pos: list[int] = []
    bucket_af: list[float] = []

    def flush() -> None:
        nonlocal cursor, bucket_pos, bucket_af
        if not bucket_pos:
            cursor += window_size
            return
        w_end = min(cursor + window_size - 1, region_end)
        nbp = w_end - cursor + 1
        pi_sum, _, seg = compute_diversity_stats(bucket_af)
        windows.append(
            DiversityWindow(
                start=cursor,
                end=w_end,
                n_variants=len(bucket_pos),
                segregating_sites=seg,
                pi=round(pi_sum / nbp, 10) if nbp else 0.0,
            )
        )
        cursor += window_size
        bucket_pos = []
        bucket_af = []

    for r in variants:
        pos = int(r["position"])
        while pos > cursor + window_size - 1:
            flush()
        bucket_pos.append(pos)
        af = r.get("allele_frequency")
        if af is not None:
            bucket_af.append(float(af))
    flush()
    return windows


__all__ = [
    "PopGenService",
    "compute_diversity_stats",
    "compute_diversity_windows",
    "compute_ld_r2",
    "harmonic_sum",
    "watterson_theta",
]

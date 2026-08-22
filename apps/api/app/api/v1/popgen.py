"""Population-genetics tool endpoints: LD, nucleotide diversity, allele freq.

Public, read-only tools (no authentication required) mirroring the public
``/tools/seqfetch`` pattern: they aggregate the public ``variant_facts``
store and expose nothing private.  All three return plain JSON ready for
front-end Plotly rendering.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.popgen import (
    AlleleFreqRequest,
    AlleleFreqResponse,
    DiversityRequest,
    DiversityResponse,
    LdRequest,
    LdResponse,
)
from ...services.popgen_service import PopGenService
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/tools", tags=["tools"])
service = PopGenService()


@router.post("/ld", response_model=LdResponse)
async def compute_ld(
    request: LdRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> LdResponse:
    """LD heatmap data: variant coordinates + r² matrix.

    - Region/gene mode returns the variant coordinates in the interval
      (from ``variant_facts``) together with ``r_squared: null`` when no
      per-sample genotype data is available (the store only carries allele
      frequencies).
    - Inline ``genotypes`` mode (sample × variant dosage matrix) computes the
      full pairwise r² matrix (squared Pearson correlation of dosages).
    """
    return await service.ld(db, request, release_context=release_context)


@router.post("/diversity", response_model=DiversityResponse)
async def nucleotide_diversity(
    request: DiversityRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> DiversityResponse:
    """Nucleotide diversity (π) and Watterson's θ for a gene / interval.

    π = Σ 2·p·(1−p) over polymorphic sites, per base pair; θ = S / a_n is
    reported when ``sample_size`` is provided.  Optional ``window_size``
    (bp) returns per-window π for sliding-window plots.
    """
    return await service.diversity(
        db,
        request,
        release_context=release_context,
    )


@router.post("/allelefreq", response_model=AlleleFreqResponse)
async def allele_frequencies(
    request: AlleleFreqRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> AlleleFreqResponse:
    """Per-variant allele frequencies for a locus / gene / interval."""
    return await service.allele_frequencies(
        db,
        request,
        release_context=release_context,
    )

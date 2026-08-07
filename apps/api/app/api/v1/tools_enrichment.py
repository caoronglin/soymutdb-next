"""GO/KEGG enrichment analysis tool (public).

POST /api/v1/tools/enrichment — runs a hypergeometric enrichment test over
the ``gene_annotations`` table (gene → GO/KEGG term mappings).  When the
annotation table is missing or the input genes carry no annotations, the
endpoint returns an explicit empty result with a ``message`` explaining why
(never an error).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.enrichment import EnrichmentRequest, EnrichmentResponse
from ...services import enrichment_service

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post(
    "/enrichment",
    response_model=EnrichmentResponse,
    summary="GO/KEGG enrichment analysis",
    description=(
        "Hypergeometric enrichment test (right-tail) with Benjamini-Hochberg "
        "multiple-testing correction.  The background set is the full set of "
        "genes annotated for the requested ontology.  Terms are filtered by "
        "the raw p-value threshold, sorted by q-value ascending, and limited "
        "to ``max_terms``."
    ),
)
async def run_enrichment(
    payload: EnrichmentRequest,
    db: AsyncSession = Depends(get_db),
) -> EnrichmentResponse:
    """Run GO/KEGG term enrichment for the submitted gene list."""
    return await enrichment_service.run_enrichment(
        db,
        genes=payload.genes,
        ontology=payload.ontology,
        p_threshold=payload.p_threshold,
        max_terms=payload.max_terms,
    )


__all__ = ["run_enrichment", "router"]

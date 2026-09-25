"""GO/KEGG enrichment analysis tool (public).

POST /api/v1/tools/enrichment — runs an enrichment analysis over the
``gene_annotations`` table (gene → GO/KEGG term mappings) in one of two
modes, selected by the ``mode`` field:

* ``ora`` (default, backwards compatible) — hypergeometric right-tail test
  with Benjamini-Hochberg correction.
* ``gsea`` — simplified rank-based gene-set test over per-gene values
  (e.g. log2 fold-changes); requires ``values`` aligned 1:1 with ``genes``.

When the annotation table is missing or the input genes carry no
annotations, the endpoint returns an explicit empty result with a
``message`` explaining why. A present table without assembly provenance is
rejected with HTTP 503.

Reference-material note: the planned external reference for the GSEA
statistics could not be retrieved (scraping source blocked); the
implementation follows the standard field definitions (running-sum ES,
one-sided Smirnov asymptotic p-value, BH FDR, z-score NES) as documented in
``enrichment_service``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...schemas.enrichment import (
    EnrichmentGseaResponse,
    EnrichmentRequest,
    EnrichmentResponse,
)
from ...services import enrichment_service
from ...services.release_context import ReleaseContext, get_release_context

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post(
    "/enrichment",
    response_model=EnrichmentResponse | EnrichmentGseaResponse,
    summary="GO/KEGG enrichment analysis (ORA or GSEA)",
    description=(
        "Assembly-scoped enrichment analysis over the gene_annotations table. 'ora' (default): "
        "hypergeometric right-tail test with Benjamini-Hochberg correction; "
        "the background set is the full set of genes annotated for the "
        "requested ontology.  'gsea': simplified rank-based gene-set test over "
        "per-gene values (requires 'values' aligned 1:1 with 'genes' and a "
        "minimum term size via 'min_genes').  In both modes terms are filtered "
        "by the raw p-value threshold, sorted by q-value ascending, and "
        "limited to 'max_terms'. Annotation rows must be tied to a matching "
        "release/assembly and a source-attributed annotation snapshot; legacy "
        "unscoped or unattributed rows fail closed."
    ),
)
async def run_enrichment(
    payload: EnrichmentRequest,
    db: AsyncSession = Depends(get_db),
    release_context: ReleaseContext = Depends(get_release_context),
) -> EnrichmentResponse | EnrichmentGseaResponse:
    """Run GO/KEGG term enrichment for the submitted gene list."""
    if payload.mode == "gsea":
        assert payload.values is not None  # guaranteed by schema validation
        return await enrichment_service.run_gsea_enrichment(
            db,
            assembly_id=payload.assembly_id,
            release_id=release_context.release_id,
            genes=payload.genes,
            values=payload.values,
            ontology=payload.ontology,
            p_threshold=payload.p_threshold,
            max_terms=payload.max_terms,
            min_genes=payload.min_genes,
        )
    return await enrichment_service.run_enrichment(
        db,
        assembly_id=payload.assembly_id,
        release_id=release_context.release_id,
        genes=payload.genes,
        ontology=payload.ontology,
        p_threshold=payload.p_threshold,
        max_terms=payload.max_terms,
    )


__all__ = ["run_enrichment", "router"]

"""Sequence Tools endpoints — lightweight, synchronous sequence operations.

These are NOT BLAST.  They operate only on caller-supplied inline sequences;
no genome database, assembly or release is consulted, so no genome-browser
link or genomic coordinate is ever fabricated.  Full BLAST+/DIAMOND searches
remain on the existing /blast paths.

The Rust kernel is a hard dependency: if the compiled wheel is unavailable,
every compute endpoint returns a structured 503 instead of a fake success.
``GET /capabilities`` always works and reports the engine state explicitly.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas import sequence_tools as s
from ...services import format_inspect_service as inspect_service
from ...services import sequence_tools_service as service

router = APIRouter(prefix="/tools/sequence", tags=["tools"])


@router.get("/capabilities", response_model=s.SequenceCapabilitiesResponse)
async def sequence_capabilities() -> s.SequenceCapabilitiesResponse:
    """Supported algorithms, formats, limits and engine availability."""
    return service.capabilities()


@router.post("/reverse-complement", response_model=s.ReverseComplementResponse)
async def reverse_complement(payload: s.ReverseComplementRequest) -> s.ReverseComplementResponse:
    return await service.reverse_complement(payload)


@router.post("/match", response_model=s.SequenceMatchResponse)
async def sequence_match(payload: s.SequenceMatchRequest) -> s.SequenceMatchResponse:
    return await service.match(payload)


@router.post("/align", response_model=s.SequenceAlignResponse)
async def sequence_align(payload: s.SequenceAlignRequest) -> s.SequenceAlignResponse:
    return await service.align(payload)


@router.post("/stats", response_model=s.SequenceStatsResponse)
async def sequence_stats(payload: s.SequenceStatsRequest) -> s.SequenceStatsResponse:
    return await service.stats(payload)


@router.post("/orfs", response_model=s.OrfResponse)
async def sequence_orfs(payload: s.OrfRequest) -> s.OrfResponse:
    return await service.orfs(payload)


@router.post("/translate", response_model=s.TranslateResponse)
async def sequence_translate(payload: s.TranslateRequest) -> s.TranslateResponse:
    return await service.translate(payload)


@router.post("/kmers", response_model=s.KmerResponse)
async def sequence_kmers(payload: s.KmerRequest) -> s.KmerResponse:
    return await service.kmers(payload)


@router.post("/inspect", response_model=s.FormatInspectResponse)
async def inspect_format(payload: s.FormatInspectRequest) -> s.FormatInspectResponse:
    """Validate a bounded FASTA/FASTQ/BED payload; never accepts a path or URL."""
    return await inspect_service.inspect(payload)


# ---------------------------------------------------------------------------
# Capabilities beyond the original kernel. They keep the same rules: inline
# sequences only, no paths or URLs, bounded work, and a structured 503 when no
# engine is available.
# ---------------------------------------------------------------------------


@router.post("/convert", response_model=s.ConvertFormatResponse)
async def convert_sequence_format(
    payload: s.ConvertFormatRequest,
) -> s.ConvertFormatResponse:
    """Convert records between FASTA / GenBank / EMBL / tabular text."""
    return await service.convert_format(payload)


@router.post("/restriction-sites", response_model=s.RestrictionResponse)
async def restriction_sites(payload: s.RestrictionRequest) -> s.RestrictionResponse:
    """Report the cut sites of one or more restriction enzymes."""
    return await service.restriction_sites(payload)


@router.post("/protein-properties", response_model=s.ProteinPropertiesResponse)
async def protein_properties(
    payload: s.ProteinPropertiesRequest,
) -> s.ProteinPropertiesResponse:
    """Molecular weight, isoelectric point, extinction and hydrophobicity."""
    return await service.protein_properties(payload)


@router.post("/melting-temp", response_model=s.MeltingTempResponse)
async def melting_temp(payload: s.MeltingTempRequest) -> s.MeltingTempResponse:
    """Primer melting temperature by Wallace, GC or nearest-neighbour."""
    return await service.melting_temp(payload)


@router.post("/multiple-alignment", response_model=s.MultipleAlignmentResponse)
async def multiple_alignment(
    payload: s.MultipleAlignmentRequest,
) -> s.MultipleAlignmentResponse:
    """Progressively align several sequences and return the distance matrix."""
    return await service.multiple_alignment(payload)


@router.post("/tree", response_model=s.TreeResponse)
async def neighbor_joining_tree(payload: s.TreeRequest) -> s.TreeResponse:
    """Neighbour-joining tree over the sequences, as Newick text."""
    return await service.neighbor_joining_tree(payload)

"""Gene-center sequence availability, decided once for every consumer.

The gene detail response must answer "can I get this gene's protein sequence?"
without inventing one. There is exactly one place that knows the answer, so the
portal, the API schema and any future MCP tool cannot disagree.

Today no residue store exists, so every molecule reports ``unavailable`` with a
reason. That is the honest state, and it is pinned by a test: adding a sequence
store without updating this module must fail the gene detail contract.
"""

from __future__ import annotations

from ..schemas.gene_evidence import Availability, SequenceAvailability

#: Machine-readable reason, stable across releases so clients can key on it.
NO_SEQUENCE_STORE = "no_sequence_store"

MOLECULE_LABELS = {
    "genomic": "genomic",
    "cds": "coding_sequence",
    "transcript": "transcript",
    "protein": "protein",
}


def _reason(molecule: str) -> str:
    return f"{NO_SEQUENCE_STORE}:{MOLECULE_LABELS[molecule]}"


def gene_sequence_availability() -> list[SequenceAvailability]:
    """The four molecules a gene detail page offers, with honest availability.

    Called with no arguments on purpose: availability is a property of the
    platform, not of one gene, so a gene-specific flag would be a lie waiting to
    drift. When a store arrives, this becomes a per-gene lookup here only.
    """
    return [
        SequenceAvailability(
            molecule=molecule,  # type: ignore[arg-type]
            availability=Availability.UNAVAILABLE,
            reason=_reason(molecule),
        )
        for molecule in ("genomic", "cds", "transcript", "protein")
    ]


__all__ = ["NO_SEQUENCE_STORE", "gene_sequence_availability"]

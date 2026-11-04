"""Evidence semantics for the gene center.

A scientific portal must never present a missing measurement as a zero and
must never present a computational prediction as an experiment. Both rules are
enforced here rather than in the React components, so every consumer of the
gene detail contract (portal, admin, MCP, third-party clients) reads the same
answer.

The vocabulary is deliberately small:

* ``experimental`` — measured or experimentally validated by the source study.
* ``curated`` — manually reviewed annotation carried by the source record.
* ``predicted`` — computational prediction (ab initio gene models, transferred
  motifs, inferred consequences).
* ``transferred`` — evidence copied from another species/gene by orthology or
  homology; never a statement about this locus.
* ``imported`` — the source record states nothing about how it was produced.

Anything not known is ``unknown``, and the accompanying ``source`` says which
resource it came from.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..core.compat import StrEnum


class EvidenceKind(StrEnum):
    EXPERIMENTAL = "experimental"
    CURATED = "curated"
    PREDICTED = "predicted"
    TRANSFERRED = "transferred"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


#: Ordered from strongest to weakest; the UI sorts by this.
EVIDENCE_STRENGTH: tuple[EvidenceKind, ...] = (
    EvidenceKind.EXPERIMENTAL,
    EvidenceKind.CURATED,
    EvidenceKind.PREDICTED,
    EvidenceKind.TRANSFERRED,
    EvidenceKind.IMPORTED,
    EvidenceKind.UNKNOWN,
)


class Availability(StrEnum):
    """Why a section has nothing to show.

    ``unavailable`` is the only honest answer when the platform holds no
    sequence store. It is *not* ``empty``: "we never imported this" and "this
    gene has no isoforms" are different scientific statements, and the portal
    renders them differently.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class EvidenceTag(BaseModel):
    """Provenance of one displayed assertion."""

    kind: EvidenceKind
    source: str = Field(..., min_length=1, max_length=256)


class SequenceAvailability(BaseModel):
    """Per-molecule availability for a gene's sequences.

    The platform currently has no FASTA store: ``genes``/``transcripts`` carry
    coordinates, not residues. Rather than fabricate a ``sequence`` string (a
    gene page that silently shows a made-up nucleotide string is worse than one
    that says "not imported"), the contract reports availability plus the
    reason. When a sequence store is added, only ``availability`` flips and
    the residue fields populate — consumers do not change shape.
    """

    molecule: Literal["genomic", "cds", "transcript", "protein"]
    availability: Availability = Availability.UNAVAILABLE
    reason: str | None = None
    length: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    #: Residues, only ever set when ``availability`` is ``available``.
    sequence: str | None = None


__all__ = [
    "Availability",
    "EVIDENCE_STRENGTH",
    "EvidenceKind",
    "EvidenceTag",
    "SequenceAvailability",
]

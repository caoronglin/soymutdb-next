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

#: The vocabulary, strongest first. Every member list below is built from one
#: of these tuples so the enum, the JSON schema and the TypeScript client cannot
#: drift apart. They are tuples of literals rather than ``StrEnum`` members on
#: purpose: pydantic hoists a nested enum into ``$defs`` and leaves an opaque
#: ``$ref`` in the vehicle schema, which hides the allowed labels from anyone
#: reading ``openapi.json`` and from ``openapi-typescript``. A ``Literal``
#: inline the values, so the wire contract states what it accepts.
EVIDENCE_KINDS = (
    "experimental",
    "curated",
    "predicted",
    "transferred",
    "imported",
    "unknown",
)


class EvidenceKind(StrEnum):
    EXPERIMENTAL = "experimental"
    CURATED = "curated"
    PREDICTED = "predicted"
    TRANSFERRED = "transferred"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


#: Ordered from strongest to weakest; the UI sorts by this.
EVIDENCE_STRENGTH: tuple[EvidenceKind, ...] = tuple(EvidenceKind(kind) for kind in EVIDENCE_KINDS)


class Availability(StrEnum):
    """Why a section has nothing to show.

    ``unavailable`` is the only honest answer when the platform holds no
    sequence store. It is *not* ``empty``: "we never imported this" and "this
    gene has no isoforms" are different scientific statements, and the portal
    renders them differently.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


AVAILABILITY_STATES = (Availability.AVAILABLE, Availability.UNAVAILABLE)
AVAILABILITY_LITERALS = tuple(state.value for state in AVAILABILITY_STATES)


class EvidenceTag(BaseModel):
    """Provenance of one displayed assertion."""

    kind: Literal[EVIDENCE_KINDS]  # type: ignore[valid-type]
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
    availability: Literal[AVAILABILITY_LITERALS] = (  # type: ignore[valid-type]
        Availability.UNAVAILABLE
    )
    reason: str | None = None
    length: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    #: Residues, only ever set when ``availability`` is ``available``.
    sequence: str | None = None


__all__ = [
    "AVAILABILITY_LITERALS",
    "AVAILABILITY_STATES",
    "Availability",
    "EVIDENCE_KINDS",
    "EVIDENCE_STRENGTH",
    "EvidenceKind",
    "EvidenceTag",
    "SequenceAvailability",
]

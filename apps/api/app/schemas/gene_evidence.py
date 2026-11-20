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

The same rule applies to whole sections. Every optional block of the gene
detail response carries a :class:`SectionStatus`, so "this gene has no GO
terms" and "this release has no GO snapshot" are different answers and the
portal never prints a zero where it should print "not imported".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

#: The vocabulary, strongest first. Every member list below is built from one
#: of these tuples so the enum, the JSON schema and the TypeScript client cannot
#: drift apart. They are tuples of literals rather than ``StrEnum`` members on
#: purpose: pydantic hoists a nested enum into ``$defs`` and leaves an opaque
#: ``$ref`` in the vehicle schema, which hides the allowed labels from anyone
#: reading ``openapi.json`` and from ``openapi-typescript``. A ``Literal``
#: inline the values, so the wire contract states what it accepts.
#:
#: The two ``StrEnum`` classes below are private for the same reason, one step
#: further out: a model field typed by an enum that is *importable* is
#: referenced by its qualname (``app.schemas.gene_evidence.Availability``), so
#: pydantic emits a component named after the module path instead of the values
#: and ``SequenceAvailability.model_json_schema()`` grows a ``$defs`` entry.
#: A module-private class cannot be referenced, so the enum collapses into the
#: inline ``enum`` list the contract promises. Neither class is part of the
#: public surface; the tuples and ``AVAILABILITY_STATES`` are.
EVIDENCE_KINDS = (
    "experimental",
    "curated",
    "predicted",
    "transferred",
    "imported",
    "unknown",
)


class _EvidenceKind(StrEnum):
    EXPERIMENTAL = "experimental"
    CURATED = "curated"
    PREDICTED = "predicted"
    TRANSFERRED = "transferred"
    IMPORTED = "imported"
    UNKNOWN = "unknown"


#: Ordered from strongest to weakest; the UI sorts by this.
EVIDENCE_STRENGTH: tuple[_EvidenceKind, ...] = tuple(_EvidenceKind(kind) for kind in EVIDENCE_KINDS)


class _Availability(StrEnum):
    """Why a section has nothing to show.

    ``unavailable`` is the only honest answer when the platform holds no
    sequence store. It is *not* ``empty``: "we never imported this" and "this
    gene has no isoforms" are different scientific statements, and the portal
    renders them differently.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


#: The literal (``str``) spellings clients actually receive, in declaration
#: order: ``available`` then ``unavailable``.
AVAILABILITY_LITERALS = tuple(state.value for state in _Availability)
AVAILABILITY_STATES = AVAILABILITY_LITERALS


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
        _Availability.UNAVAILABLE
    )
    reason: str | None = None
    length: int | None = Field(default=None, ge=0)
    checksum: str | None = None
    #: Residues, only ever set when ``availability`` is ``available``.
    sequence: str | None = None


#: The optional blocks of a gene detail response. One name per block, used as
#: the ``section`` value clients switch on -- never localised, never reordered.
GENE_SECTIONS = (
    "annotation",
    "homolog",
    "expression",
    "variants",
    "phenotype",
    "literature",
)


class _SectionState(StrEnum):
    """Why a gene-detail section has nothing to show.

    ``available`` — the section carries rows.
    ``empty`` — the data source is present and this gene legitimately has none.
    ``not_imported`` — the source snapshot is absent for this release. This is
    *not* an empty result: "we never imported the GO snapshot for v4" and "this
    gene has no GO terms" are different statements.
    """

    AVAILABLE = "available"
    EMPTY = "empty"
    NOT_IMPORTED = "not_imported"


SECTION_STATE_LITERALS = tuple(state.value for state in _SectionState)


class SectionStatus(BaseModel):
    """Presence, provenance and evidence strength of one gene-detail section."""

    section: Literal[GENE_SECTIONS]  # type: ignore[valid-type]
    state: Literal[SECTION_STATE_LITERALS] = (  # type: ignore[valid-type]
        _SectionState.NOT_IMPORTED
    )
    #: How many rows the section carries. ``None`` when the section could not
    #: be counted because its source is absent. Never 0 as a stand-in for
    #: "unknown" -- that is what ``state`` says.
    count: int | None = Field(default=None, ge=0)
    #: Provenance of the rows, when the source states it.
    evidence: EvidenceTag | None = None
    #: Machine-readable reason the section has no rows, e.g.
    #: ``annotation_set_missing:go``. Stable across releases so clients can
    #: key on it instead of matching prose.
    reason: str | None = None


class AnnotationTerm(BaseModel):
    """One GO/KEGG assertion with the evidence code its source carried."""

    ontology: Literal["go", "kegg"]
    term_id: str
    term_name: str
    #: The source's evidence code verbatim (``IDA``, ``IEA``, ``ISS``...).
    #: ``None`` -- not ``""`` -- when the snapshot carried no code.
    evidence_code: str | None = None
    #: The evidence *class* derived from that code, kept separate so a client
    #: never has to reimplement the mapping.
    kind: Literal[EVIDENCE_KINDS] = "unknown"  # type: ignore[valid-type]
    reference: str | None = None
    qualifier: str | None = None


class AnnotationSection(BaseModel):
    """The gene's GO/KEGG section, or the reason it is absent."""

    status: SectionStatus
    terms: list[AnnotationTerm] = Field(default_factory=list)
    #: The snapshot these terms came from. ``None`` when nothing was imported.
    source_name: str | None = None
    source_version: str | None = None
    source_url: str | None = None


class HomologRecord(BaseModel):
    """One ortholog/paralog assertion, with cross-assembly context."""

    homolog_species: str
    homolog_gene_id: str
    homolog_type: Literal["ortholog", "paralog"]
    #: How the relationship was established. ``None`` when the import source
    #: did not say -- never filled with "computed".
    method: str | None = None
    #: Origin of the row (``soybase``, ``inparanoid``...). ``None`` if silent.
    source: str | None = None
    #: ``transferred``: the row is about another locus, not this one. Always
    #: set for this section by :func:`homolog_evidence_kind`.
    kind: Literal[EVIDENCE_KINDS] = "transferred"  # type: ignore[valid-type]
    #: Confidence as the source recorded it. ``None`` when unstated.
    confidence: float | None = Field(default=None, ge=0, le=1)


class HomologSection(BaseModel):
    status: SectionStatus
    records: list[HomologRecord] = Field(default_factory=list)


class ExpressionRecord(BaseModel):
    """One expression measurement. Absent values stay absent, never 0."""

    library_id: str
    library_name: str
    tissue: str | None = None
    treatment: str | None = None
    stage: str | None = None
    #: All three units are optional: a snapshot may carry TPM only.
    tpm: float | None = None
    fpkm: float | None = None
    raw_count: int | None = None


class ExpressionSection(BaseModel):
    status: SectionStatus
    records: list[ExpressionRecord] = Field(default_factory=list)


class VariantSection(BaseModel):
    """Release- and assembly-scoped variant totals for the gene."""

    status: SectionStatus
    total: int | None = Field(default=None, ge=0)
    #: Counts by consequence class, only for classes that were counted from
    #: rows. A class absent from the map was not measured, which is different
    #: from a class measured as 0 and therefore always present.
    by_impact: dict[str, int] = Field(default_factory=dict)


class PhenotypeRecord(BaseModel):
    """One phenotype observation linked to the gene through a mutant line."""

    mutant_public_id: str
    mutant_name: str
    trait_category: str
    trait_name: str
    #: ``None`` when the source recorded the trait without a value or unit.
    trait_value: str | None = None
    unit: str | None = None
    measurement_method: str | None = None


class PhenotypeSection(BaseModel):
    status: SectionStatus
    records: list[PhenotypeRecord] = Field(default_factory=list)


class LiteratureRecord(BaseModel):
    """One publication, identified by DOI/PMID rather than its row key."""

    title: str
    authors: str | None = None
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    pmid: str | None = None


class LiteratureSection(BaseModel):
    status: SectionStatus
    records: list[LiteratureRecord] = Field(default_factory=list)


__all__ = [
    "AVAILABILITY_LITERALS",
    "AVAILABILITY_STATES",
    "EVIDENCE_KINDS",
    "EVIDENCE_STRENGTH",
    "GENE_SECTIONS",
    "SECTION_STATE_LITERALS",
    "AnnotationSection",
    "AnnotationTerm",
    "EvidenceTag",
    "ExpressionRecord",
    "ExpressionSection",
    "HomologRecord",
    "HomologSection",
    "LiteratureRecord",
    "LiteratureSection",
    "PhenotypeRecord",
    "PhenotypeSection",
    "SectionStatus",
    "SequenceAvailability",
    "VariantSection",
]

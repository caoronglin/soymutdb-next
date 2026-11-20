"""Gene center: no fabricated sequences, explicit evidence labels.

Two rules from `docs/dev/database-core-contract.md` and section 11 of the
platform brief are pinned here:

* never present a missing measurement as a value (a gene page must not render a
  sequence the platform does not hold);
* never raise a prediction to a curated or experimental claim.

Both tests are ablation-shaped: they fail if someone "helpfully" fills the
sequence string, or infers evidence from the accession pattern.

The availability half used to read "the platform has no residue store, so every
molecule is unavailable". A store exists now, so the pinned claim is narrowed to
what is still true and still worth defending: a gene the store does not cover
reports every molecule as unavailable, with the reason shape clients key on, and
one molecule having residues never makes another molecule look served.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.gene_evidence import (
    AVAILABILITY_LITERALS,
    EVIDENCE_KINDS,
    EvidenceTag,
    SequenceAvailability,
)
from app.services.gene_service import gene_model_evidence
from app.services.sequence_availability import (
    NO_SEQUENCE_STORE,
    ReferenceState,
    StoredResidue,
    availability_entries,
)


def _gene() -> SimpleNamespace:
    """A gene in an assembly that declares no reference genome and no residues."""
    return SimpleNamespace(
        accession="Glyma.01G000100",
        gene_pk=1,
        assembly_id=1,
        start=1000,
        end=2000,
        strand="+",
        chromosome=SimpleNamespace(name="Gm01"),
        assembly=SimpleNamespace(
            name="Gmax_880_v6.0", release_id=1, fasta_url=None, fai_url=None
        ),
    )


def _entries(
    *, stored: dict[str, list[StoredResidue]] | None = None
) -> list[SequenceAvailability]:
    return availability_entries(
        _gene(),  # type: ignore[arg-type]
        stored=stored or {},
        spans_by_transcript={},
        reference=ReferenceState(index=None),
    )


def test_a_gene_the_store_does_not_cover_reports_every_molecule_unavailable():
    availability = _entries()
    assert [entry.molecule for entry in availability] == [
        "genomic",
        "cds",
        "transcript",
        "protein",
    ]
    for entry in availability:
        assert entry.availability == AVAILABILITY_LITERALS[1]
        # Ablation: a fabricated residue string is the exact failure this
        # guards. An empty string would be just as dishonest as a real one.
        assert entry.sequence is None
        assert entry.length is None
        assert entry.reason and entry.reason.startswith(NO_SEQUENCE_STORE)


def test_availability_reason_names_the_molecule():
    """Clients switch on the molecule, so the reason must be per-molecule."""
    reasons = {entry.molecule: entry.reason for entry in _entries()}
    assert len(set(reasons.values())) == len(reasons)


def test_one_stored_molecule_never_speaks_for_another():
    """A CDS row must not make the protein look served.

    Ablation: deriving ``protein`` from ``cds`` (translate in the reader) or
    reporting the whole platform's coverage per gene is exactly the fabrication
    the ``sequence`` field must never carry.
    """
    cds = StoredResidue(
        transcript_id="tx1",
        length=6,
        sha256="a" * 64,
        sequence="ACGTAC",
        is_canonical=False,
    )
    by_molecule = {entry.molecule: entry for entry in _entries(stored={"cds": [cds]})}
    assert by_molecule["cds"].availability == AVAILABILITY_LITERALS[0]
    assert by_molecule["cds"].sequence == "ACGTAC"
    assert by_molecule["protein"].availability == AVAILABILITY_LITERALS[1]
    assert by_molecule["protein"].sequence is None


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ({"evidence": "experimental"}, "experimental"),
        ({"evidence": "Curated"}, "curated"),
        ({"evidence": "transferred"}, "transferred"),
        ({"source": "AUGUSTUS"}, "predicted"),
        ({"source": "GeneSnap"}, "predicted"),
        ({"source": "curated by SoyBase"}, "curated"),
        ({"source": "Glyma_275_Wm82.a4.v1.gene.gff3"}, "imported"),
    ],
)
def test_declared_source_maps_to_one_evidence_kind(attributes, expected):
    tag = gene_model_evidence(SimpleNamespace(attributes=attributes))  # type: ignore[arg-type]
    assert tag is not None
    assert tag.kind == expected


@pytest.mark.parametrize(
    "attributes",
    [None, {}, {"source": "   "}, {"evidence": "probably"}, {"note": "x"}],
)
def test_unknown_provenance_stays_unknown(attributes):
    """A silent source yields no tag at all rather than a guessed one."""
    assert gene_model_evidence(SimpleNamespace(attributes=attributes)) is None  # type: ignore[arg-type]


def test_accession_never_implies_predicted_status():
    """A gene id that looks computational is not evidence of anything.

    Ablation: inferring PREDICTED from an accession pattern would relabel
    curated records, which is a false scientific claim.
    """
    gene = SimpleNamespace(accession="Glyma.01G000100.predicted", attributes=None)
    assert gene_model_evidence(gene) is None  # type: ignore[arg-type]


def test_declared_source_is_preserved_verbatim():
    gene = SimpleNamespace(attributes={"source": "AUGUSTUS 3.5"})
    tag = gene_model_evidence(gene)  # type: ignore[arg-type]
    assert tag is not None
    assert tag.source == "AUGUSTUS 3.5"


def test_wire_schema_states_the_enum_labels_inline():
    """The contract must print its allowed values, not a ``$ref`` to ``$defs``.

    Ablation: nested ``StrEnum`` members make pydantic hoist the enum and leave
    an opaque reference in the vehicle schema. ``openapi.json`` then does not
    say what the API accepts and ``openapi-typescript`` still renders a union,
    so the drift stays invisible until someone diffs the two by hand.
    """
    for model, field, expected in (
        (SequenceAvailability, "availability", AVAILABILITY_LITERALS),
        (EvidenceTag, "kind", EVIDENCE_KINDS),
    ):
        schema = model.model_json_schema()
        assert "$defs" not in schema
        property_schema = schema["properties"][field]
        assert "$ref" not in property_schema
        assert property_schema["enum"] == list(expected)

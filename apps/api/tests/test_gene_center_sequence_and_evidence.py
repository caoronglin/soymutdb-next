"""Gene center: no fabricated sequences, explicit evidence labels.

Two rules from `docs/dev/database-core-contract.md` and section 11 of the
platform brief are pinned here:

* never present a missing measurement as a value (a gene page must not render a
  sequence the platform does not hold);
* never raise a prediction to a curated or experimental claim.

Both tests are ablation-shaped: they fail if someone "helpfully" fills the
sequence string, or infers evidence from the accession pattern.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.schemas.gene_evidence import Availability, EvidenceKind
from app.services.gene_service import gene_model_evidence
from app.services.sequence_availability import (
    NO_SEQUENCE_STORE,
    gene_sequence_availability,
)


def test_every_molecule_reports_unavailable_without_a_residue_store():
    availability = gene_sequence_availability()
    assert [entry.molecule for entry in availability] == [
        "genomic",
        "cds",
        "transcript",
        "protein",
    ]
    for entry in availability:
        assert entry.availability is Availability.UNAVAILABLE
        # Ablation: a fabricated residue string is the exact failure this
        # guards. An empty string would be just as dishonest as a real one.
        assert entry.sequence is None
        assert entry.length is None
        assert entry.reason and entry.reason.startswith(NO_SEQUENCE_STORE)


def test_availability_reason_names_the_molecule():
    """Clients switch on the molecule, so the reason must be per-molecule."""
    reasons = {entry.molecule: entry.reason for entry in gene_sequence_availability()}
    assert len(set(reasons.values())) == len(reasons)


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        ({"evidence": "experimental"}, EvidenceKind.EXPERIMENTAL),
        ({"evidence": "Curated"}, EvidenceKind.CURATED),
        ({"evidence": "transferred"}, EvidenceKind.TRANSFERRED),
        ({"source": "AUGUSTUS"}, EvidenceKind.PREDICTED),
        ({"source": "GeneSnap"}, EvidenceKind.PREDICTED),
        ({"source": "curated by SoyBase"}, EvidenceKind.CURATED),
        ({"source": "Glyma_275_Wm82.a4.v1.gene.gff3"}, EvidenceKind.IMPORTED),
    ],
)
def test_declared_source_maps_to_one_evidence_kind(attributes, expected):
    tag = gene_model_evidence(SimpleNamespace(attributes=attributes))
    assert tag is not None
    assert tag.kind is expected


@pytest.mark.parametrize(
    "attributes",
    [None, {}, {"source": "   "}, {"evidence": "probably"}, {"note": "x"}],
)
def test_unknown_provenance_stays_unknown(attributes):
    """A silent source yields no tag at all rather than a guessed one."""
    assert gene_model_evidence(SimpleNamespace(attributes=attributes)) is None


def test_accession_never_implies_predicted_status():
    """A gene id that looks computational is not evidence of anything.

    Ablation: inferring PREDICTED from an accession pattern would relabel
    curated records, which is a false scientific claim.
    """
    gene = SimpleNamespace(accession="Glyma.01G000100.predicted", attributes=None)
    assert gene_model_evidence(gene) is None


def test_declared_source_is_preserved_verbatim():
    tag = gene_model_evidence(SimpleNamespace(attributes={"source": "AUGUSTUS 3.5"}))
    assert tag is not None
    assert tag.source == "AUGUSTUS 3.5"

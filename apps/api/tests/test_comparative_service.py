"""Comparative genomics: no similarity-as-orthology, no empty-list-as-absence.

The load-bearing rule of this slice is negative: **a BLAST hit is not an
ortholog**. Nothing in the comparative service may read an alignment score, an
e-value or an identity percentage and turn it into a relationship type. The
first block below pins that as an executable statement rather than a comment,
by inspecting the module's own imports and by refusing to publish a
relationship for a row whose source does not state one.

The rest of the file covers the presence semantics the portal depends on:
a species with no member is ``no_data`` with ``member_count: null``, never 0.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assembly,
    Chromosome,
    Gene,
    GeneFamily,
    GeneFamilyMember,
    GeneHomolog,
    Release,
    ReleaseStatus,
)
from app.schemas.comparative import (
    ArtifactRequest,
    FamilyDetailResponse,
    FamilyResponse,
)
from app.services import comparative_service as module
from app.services.comparative_service import (
    ALLOWED_ARTIFACT_METHODS,
    ComparativeService,
    family_evidence,
    homology_evidence,
    input_fingerprint,
    relationship_type_for_membership,
    relationship_type_for_orthologs,
)
from app.services.release_context import ReleaseContext

SERVICE_PATH = Path(module.__file__)


# ---------------------------------------------------------------------------
# Similarity is not orthology
# ---------------------------------------------------------------------------


def test_service_never_reads_blast_evidence() -> None:
    """The module must not import BLAST models: similarity is not relationship.

    Ablation: importing ``BlastHit`` (or the service that ranks hits) would
    make it possible to derive ``relationship_type`` from an alignment score,
    which is exactly the claim the roadmap forbids.
    """
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden = {"blast", "models.blast", "services.blast_service", "BlastHit", "BlastJob"}
    assert not {name for name in imported for token in forbidden if name.endswith(token)}


def test_similarity_fields_are_absent_from_the_wire_contract() -> None:
    """No comparative model may carry an alignment score or identity field."""
    from app.schemas import comparative

    banned = {"evalue", "bitscore", "identity", "similarity", "percent_identity"}
    for model in (
        comparative.OrthologRecord,
        comparative.FamilyMemberResponse,
        comparative.SpeciesCoverageResponse,
    ):
        assert not banned & set(model.model_fields), model.__name__


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"soybean": 1, "arabidopsis": 1}, "one_to_one"),
        ({"soybean": 3}, "one_to_many"),
        ({"soybean": 2, "arabidopsis": 1}, "many_to_many"),
    ],
)
def test_ortholog_relationship_type_counts_counterparts_not_scores(counts, expected):
    rows = []
    for species, count in counts.items():
        rows.extend(
            type("Row", (), {"homolog_species": species, "homolog_gene_id": f"{species}{i}"})()
            for i in range(count)
        )
    assert relationship_type_for_orthologs(rows) == expected


def test_membership_type_under_claims_when_members_disagree():
    """Disagreeing rows become ``many_to_many`` rather than the strongest type."""
    members = [
        type("M", (), {"relationship_type": "one_to_one"})(),
        type("M", (), {"relationship_type": "one_to_many"})(),
    ]
    assert relationship_type_for_membership(members) == "many_to_many"


def test_homology_evidence_is_always_transferred():
    assert homology_evidence("soybase").kind == "transferred"
    # An import that states no source still does not upgrade the claim.
    assert homology_evidence(None).kind == "transferred"
    assert homology_evidence(None).source


def test_family_evidence_is_predicted_never_experimental():
    family = type("F", (), {"method": "hmmsearch", "source_name": "fixture"})()
    assert family_evidence(family).kind == "predicted"


def test_input_fingerprint_is_order_sensitive():
    """An alignment depends on member order, so the hash must too."""
    assert input_fingerprint(["a", "b"]) != input_fingerprint(["b", "a"])
    assert input_fingerprint(["a", "b"]) == input_fingerprint(["a", "b"])


def test_artifact_methods_are_an_allowlist():
    assert "mafft" in ALLOWED_ARTIFACT_METHODS
    assert "rm -rf /" not in ALLOWED_ARTIFACT_METHODS


def test_artifact_request_rejects_an_unknown_method_shape():
    with pytest.raises(ValueError):
        ArtifactRequest(family_id=1, artifact_type="msa", method="")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Presence semantics
# ---------------------------------------------------------------------------


def test_coverage_reports_no_data_without_a_count():
    coverage = ComparativeService._coverage_for_species(
        ["arabidopsis", "soybean"],
        [type("M", (), {"species": "soybean"})()],
    )
    by_species = {entry.species: entry for entry in coverage}
    assert by_species["soybean"].state == "available"
    assert by_species["soybean"].member_count == 1
    # Absence of a row is not a measured zero.
    assert by_species["arabidopsis"].state == "no_data"
    assert by_species["arabidopsis"].member_count is None


def test_family_detail_model_requires_typed_relationship():
    """The type the family reports is one of the declared ones, never free text."""
    from app.schemas.comparative import RELATIONSHIP_TYPES

    assert set(RELATIONSHIP_TYPES) == {"one_to_one", "one_to_many", "many_to_many"}
    schema = FamilyDetailResponse.model_json_schema()
    member_type = schema["$defs"]["FamilyMemberResponse"]["properties"]["relationship_type"]
    assert set(member_type["enum"]) == set(RELATIONSHIP_TYPES)


def test_family_response_requires_a_stated_method():
    """A family without a method cannot be represented, let alone stored."""
    assert "method" in FamilyResponse.model_fields
    # The model itself does not police the value; the database does
    # (``method`` is NOT NULL and the migration test covers it). What this test
    # pins is that the field is required on the wire at all -- a family response
    # cannot be built without stating a method.
    with pytest.raises(ValueError):
        FamilyResponse(  # type: ignore[call-arg]
            family_id=1, level="gene_family", external_id="PF1", name="f",
            source_name="s", source_version="1",
            source_url="https://example.org", release_id=1, assembly_id=1,
            evidence=family_evidence(None),
        )


# ---------------------------------------------------------------------------
# PostgreSQL integration
# ---------------------------------------------------------------------------


class _Scope:
    def __init__(self, release, assemblies, genes):
        self.release = release
        self.assemblies = assemblies
        self.genes = genes


async def _scope(db: AsyncSession) -> _Scope:
    token = uuid.uuid4().hex[:8]
    release = Release(
        version=f"comparative-{token}", name="comparative", status=ReleaseStatus.DRAFT
    )
    db.add(release)
    await db.flush()
    assemblies, genes = {}, {}
    for label in ("v4", "v5"):
        assembly = Assembly(
            name=f"Comparative.{label}.{token}", version=label,
            species="Glycine max", release_id=release.id,
        )
        db.add(assembly)
        await db.flush()
        chromosome = Chromosome(assembly_id=assembly.id, name="Chr01", length=100_000)
        db.add(chromosome)
        await db.flush()
        gene = Gene(
            accession="Glyma.01G000100", assembly_id=assembly.id,
            chromosome_id=chromosome.id, start=1, end=500, strand="+",
        )
        db.add(gene)
        assemblies[label] = assembly
        genes[label] = gene
    await db.flush()
    return _Scope(release, assemblies, genes)


async def _family(db: AsyncSession, scope: _Scope, *, assembly, external_id="PF00001"):
    family = GeneFamily(
        assembly_id=assembly.id,
        release_id=scope.release.id,
        level="gene_family",
        external_id=external_id,
        name=f"Family {external_id}",
        method="hmmsearch",
        method_version="3.3",
        source_name="fixture",
        source_version="1",
        source_url="https://example.org/families",
        source_sha256="a" * 64,
    )
    db.add(family)
    await db.flush()
    return family


@pytest.mark.integration
@pytest.mark.asyncio
async def test_family_members_and_coverage_are_release_scoped(db_session):
    scope = await _scope(db_session)
    family = await _family(db_session, scope, assembly=scope.assemblies["v4"])
    for accession, species in (
        ("Glyma.01G000100", "soybean"),
        ("Glyma.01G000200", "soybean"),
        ("AT1G01010", "arabidopsis"),
    ):
        db_session.add(
            GeneFamilyMember(
                family_id=family.id,
                assembly_id=scope.assemblies["v4"].id,
                release_id=scope.release.id,
                gene_accession=accession,
                species=species,
                relationship_type="one_to_many",
                method="hmmsearch",
                confidence=0.9,
            )
        )
    await db_session.flush()

    detail = await ComparativeService().get_family(
        db_session,
        family.id,
        release_context=ReleaseContext(
            release_id=scope.release.id, assembly_id=scope.assemblies["v4"].id
        ),
    )
    assert detail.member_count == 3
    assert {member.relationship_type for member in detail.members} == {"one_to_many"}
    coverage = {entry.species: entry for entry in detail.coverage}
    assert coverage["soybean"].member_count == 2
    assert coverage["arabidopsis"].member_count == 1
    # A species the family says nothing about is not invented here.
    assert "maize" not in coverage


@pytest.mark.integration
@pytest.mark.asyncio
async def test_family_read_never_crosses_into_another_assembly(db_session):
    """A v5 family is not readable when the caller pinned v4.

    Ablation: dropping the ``assembly_id`` filter answers a v4 request with v5
    members, which is the coordinate-namespace leak the core contract forbids.
    """
    from app.core.exceptions import NotFoundError

    scope = await _scope(db_session)
    family = await _family(db_session, scope, assembly=scope.assemblies["v5"])

    with pytest.raises(NotFoundError):
        await ComparativeService().get_family(
            db_session,
            family.id,
            release_context=ReleaseContext(
                release_id=scope.release.id, assembly_id=scope.assemblies["v4"].id
            ),
        )
    # The same row is readable when the caller asks for its own assembly.
    detail = await ComparativeService().get_family(
        db_session,
        family.id,
        release_context=ReleaseContext(
            release_id=scope.release.id, assembly_id=scope.assemblies["v5"].id
        ),
    )
    assert detail.assembly_id == scope.assemblies["v5"].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orthologs_without_rows_report_no_data(db_session):
    scope = await _scope(db_session)
    # Both assemblies hold an accession with this name; the case under test is
    # the resolved-assembly read, not the disambiguation error (which has its
    # own coverage in the gene tests).
    response = await ComparativeService().get_orthologs(
        db_session,
        "Glyma.01G000100",
        release_context=ReleaseContext(
            release_id=scope.release.id, assembly_id=scope.assemblies["v4"].id
        ),
    )
    assert response.state == "no_data"
    assert response.records == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ortholog_rows_expose_stated_type_and_never_a_score(db_session):
    scope = await _scope(db_session)
    db_session.add(
        GeneHomolog(
            gene_id=scope.genes["v4"].gene_pk,
            homolog_species="Arabidopsis thaliana",
            homolog_gene_id="AT1G01010",
            homolog_type="ortholog",
            source="soybase",
        )
    )
    await db_session.flush()

    response = await ComparativeService().get_orthologs(
        db_session,
        "Glyma.01G000100",
        release_context=ReleaseContext(
            release_id=scope.release.id, assembly_id=scope.assemblies["v4"].id
        ),
    )
    assert response.state == "available"
    record = response.records[0]
    assert record.relationship_type == "one_to_one"
    assert record.evidence.kind == "transferred"
    # The import states no method, so none is invented.
    assert record.method is None
    dumped = record.model_dump()
    assert not {"evalue", "bitscore", "similarity"} & set(dumped)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_artifact_request_freezes_the_ordered_member_set(db_session):
    scope = await _scope(db_session)
    family = await _family(db_session, scope, assembly=scope.assemblies["v4"])
    for accession in ("Glyma.01G000100", "Glyma.01G000200", "Glyma.01G000300"):
        db_session.add(
            GeneFamilyMember(
                family_id=family.id,
                assembly_id=scope.assemblies["v4"].id,
                release_id=scope.release.id,
                gene_accession=accession,
                species="soybean",
                relationship_type="one_to_one",
            )
        )
    await db_session.flush()

    artifact, members = await ComparativeService().request_artifact(
        db_session,
        family_id=family.id,
        artifact_type="msa",
        method="mafft",
        release_context=ReleaseContext(
            release_id=scope.release.id, assembly_id=scope.assemblies["v4"].id
        ),
    )
    assert artifact.state == "pending"
    assert artifact.input_sha256 == input_fingerprint(members)
    assert artifact.input_member_ids == members
    assert artifact.release_id == scope.release.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_artifact_request_refuses_an_unknown_method(db_session):
    from app.core.exceptions import ValidationError

    scope = await _scope(db_session)
    family = await _family(db_session, scope, assembly=scope.assemblies["v4"])
    with pytest.raises(ValidationError):
        await ComparativeService().request_artifact(
            db_session,
            family_id=family.id,
            artifact_type="msa",
            method="; rm -rf /",
            release_context=ReleaseContext(release_id=scope.release.id),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_artifact_request_refuses_an_empty_family(db_session):
    from app.core.exceptions import ValidationError

    scope = await _scope(db_session)
    family = await _family(db_session, scope, assembly=scope.assemblies["v4"])
    with pytest.raises(ValidationError, match="no members"):
        await ComparativeService().request_artifact(
            db_session,
            family_id=family.id,
            artifact_type="tree",
            method="iqtree",
            release_context=ReleaseContext(release_id=scope.release.id),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compare_families_splits_shared_and_unique_members(db_session):
    scope = await _scope(db_session)
    left = await _family(db_session, scope, assembly=scope.assemblies["v4"], external_id="PF1")
    right = await _family(db_session, scope, assembly=scope.assemblies["v4"], external_id="PF2")
    for family, accessions in (
        (left, ("Glyma.01G000100", "Glyma.01G000200")),
        (right, ("Glyma.01G000200", "Glyma.01G000300")),
    ):
        for accession in accessions:
            db_session.add(
                GeneFamilyMember(
                    family_id=family.id,
                    assembly_id=scope.assemblies["v4"].id,
                    release_id=scope.release.id,
                    gene_accession=accession,
                    species="soybean",
                    relationship_type="one_to_one",
                )
            )
    await db_session.flush()

    comparison = await ComparativeService().compare_families(
        db_session,
        left.id,
        right.id,
        release_context=ReleaseContext(release_id=scope.release.id),
    )
    assert [m.gene_accession for m in comparison.shared] == ["Glyma.01G000200"]
    assert [m.gene_accession for m in comparison.only_left] == ["Glyma.01G000100"]
    assert [m.gene_accession for m in comparison.only_right] == ["Glyma.01G000300"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_families_listed_for_one_release_only(db_session):
    scope = await _scope(db_session)
    await _family(db_session, scope, assembly=scope.assemblies["v4"])
    listed = await ComparativeService().list_families(
        db_session,
        release_context=ReleaseContext(release_id=scope.release.id),
    )
    assert listed.total == 1
    assert listed.items[0].method == "hmmsearch"
    scoped = await db_session.execute(select(GeneFamily.id))
    assert len(list(scoped.scalars().all())) >= 1

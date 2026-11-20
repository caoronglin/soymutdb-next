"""Gene detail sections: presence is a claim, and it must be a true one.

Three rules from `docs/dev/database-core-contract.md` are pinned here:

* a section that was never imported is not an empty result (``not_imported``
  carries ``count=None``, never ``0``);
* a section's rows never cross assemblies or releases (ASM-01..03);
* an evidence code the platform cannot classify is ``unknown``, never silently
  promoted to ``experimental``.

The unit tests need no database. The integration class runs the same loader
against PostgreSQL when ``SOYMUTDB_TEST_DATABASE_URL`` is set, which is what the
backend gate does.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assembly,
    Chromosome,
    Gene,
    GeneAnnotation,
    GeneAnnotationSet,
    GeneHomolog,
    MutantLine,
    Phenotype,
    Release,
    ReleaseStatus,
    VariantSummary,
)
from app.models.expression import ExpressionData, ExpressionLibrary
from app.services import gene_detail_sections as sections
from app.services.gene_detail_sections import (
    annotation_evidence_kind,
    homolog_evidence_kind,
    load_annotation_section,
    load_literature_section,
    section_statuses,
)
from app.services.release_context import ReleaseContext

# ---------------------------------------------------------------------------
# Evidence vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("EXP", "experimental"),
        ("ida", "experimental"),
        ("TAS", "curated"),
        ("IEA", "predicted"),
        ("IBA", "transferred"),
    ],
)
def test_known_evidence_codes_map_to_one_kind(code: str, expected: str) -> None:
    assert annotation_evidence_kind(code) == expected


@pytest.mark.parametrize("code", [None, "", "   ", "ZZZ", "experimental-ish"])
def test_unclassifiable_evidence_is_unknown_not_stronger(code: str | None) -> None:
    """A code the platform cannot read must not inherit a stronger label.

    Ablation: mapping an unknown code to ``experimental`` or ``curated`` would
    publish a claim the source never made.
    """
    assert annotation_evidence_kind(code) == "unknown"


def test_homolog_rows_are_transferred_evidence() -> None:
    """A homolog row is about another locus; it never describes this one."""
    assert homolog_evidence_kind() == "transferred"


# ---------------------------------------------------------------------------
# Section status semantics
# ---------------------------------------------------------------------------


def test_missing_source_is_not_an_empty_section():
    status = sections._status("annotation", count=None, reason="annotation_set_missing")
    assert status.state == "not_imported"
    # ``count`` must stay absent: 0 would read as "measured, nothing there".
    assert status.count is None
    assert status.reason == "annotation_set_missing"


def test_zero_rows_is_empty_not_not_imported():
    status = sections._status("expression", count=0)
    assert status.state == "empty"
    assert status.count == 0


def test_rows_present_is_available_with_its_count():
    status = sections._status("variants", count=7, evidence=None)
    assert status.state == "available"
    assert status.count == 7


def test_every_section_name_is_a_declared_section():
    """``section`` is a closed vocabulary; a typo must not reach the wire."""
    from app.schemas.gene_evidence import GENE_SECTIONS

    for name in GENE_SECTIONS:
        assert sections._status(name, count=0).section == name


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_section_statuses_are_indexed_by_name():
    indexed = section_statuses(
        [
            sections._status("annotation", count=None),
            sections._status("variants", count=1),
        ]
    )
    assert set(indexed) == {"annotation", "variants"}
    assert indexed["annotation"].state == "not_imported"


@pytest.mark.asyncio
async def test_literature_reports_the_missing_relation_instead_of_every_paper():
    """The schema has no gene->publication relation; the section says so.

    Ablation: returning the publications table would attribute unrelated papers
    to every gene.
    """
    section = await load_literature_section(
        None,  # type: ignore[arg-type]
        SimpleNamespace(gene_pk=1, assembly_id=1, accession="G1"),
        release_context=ReleaseContext(release_id=7, assembly_id=1),
    )
    assert section.status.state == "not_imported"
    assert section.status.reason == "gene_literature_link_missing"
    assert section.records == []


# ---------------------------------------------------------------------------
# PostgreSQL integration
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


class _Scope:
    """A release with two assemblies and one gene in each."""

    def __init__(self, release: Release, v4: Assembly, v5: Assembly, gene_v4: Gene, gene_v5: Gene):
        self.release = release
        self.v4 = v4
        self.v5 = v5
        self.gene_v4 = gene_v4
        self.gene_v5 = gene_v5


async def _scope(db: AsyncSession, token: str | None = None) -> _Scope:
    token = token or uuid4().hex[:8]
    release = Release(
        version=f"gene-center-{token}",
        name="Gene center test",
        status=ReleaseStatus.DRAFT,
    )
    db.add(release)
    await db.flush()
    assemblies = {}
    genes = {}
    for label in ("v4", "v5"):
        assembly = Assembly(
            name=f"GeneCenter.{label}.{token}",
            version=label,
            species="Glycine max",
            release_id=release.id,
        )
        db.add(assembly)
        await db.flush()
        chromosome = Chromosome(assembly_id=assembly.id, name="Chr01", length=100_000)
        db.add(chromosome)
        await db.flush()
        gene = Gene(
            accession="Glyma.01G000100",
            assembly_id=assembly.id,
            chromosome_id=chromosome.id,
            start=1,
            end=1000,
            strand="+",
        )
        db.add(gene)
        assemblies[label] = assembly
        genes[label] = gene
    await db.flush()
    return _Scope(release, assemblies["v4"], assemblies["v5"], genes["v4"], genes["v5"])


async def _annotation_set(
    db: AsyncSession, scope: _Scope, *, assembly: Assembly
) -> GeneAnnotationSet:
    snapshot = GeneAnnotationSet(
        assembly_id=assembly.id,
        release_id=scope.release.id,
        ontology="go",
        source_name="Synthetic GO fixture",
        source_version="1",
        source_url="https://example.org/go/v1",
        source_sha256="a" * 64,
        importer_version="1",
        row_count=2,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


def _context(scope: _Scope) -> ReleaseContext:
    return ReleaseContext(release_id=scope.release.id, assembly_id=scope.v4.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_section_without_a_snapshot_is_not_imported(db_session):
    scope = await _scope(db_session)
    section = await load_annotation_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "not_imported"
    assert section.status.count is None
    assert section.terms == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_terms_carry_their_own_evidence_kind(db_session):
    scope = await _scope(db_session)
    snapshot = await _annotation_set(db_session, scope, assembly=scope.v4)
    db_session.add_all(
        [
            GeneAnnotation(
                annotation_set_id=snapshot.id,
                assembly_id=scope.v4.id,
                release_id=scope.release.id,
                ontology="go",
                gene_id=scope.gene_v4.accession,
                term_id="GO:0008150",
                term_name="biological process",
                evidence_code="IDA",
                reference="PMID:1",
            ),
            GeneAnnotation(
                annotation_set_id=snapshot.id,
                assembly_id=scope.v4.id,
                release_id=scope.release.id,
                ontology="go",
                gene_id=scope.gene_v4.accession,
                term_id="GO:0003674",
                term_name="molecular function",
                evidence_code="IEA",
                reference="",
            ),
        ]
    )
    await db_session.flush()

    section = await load_annotation_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "available"
    assert section.status.count == 2
    kinds = {term.term_id: term.kind for term in section.terms}
    assert kinds == {"GO:0008150": "experimental", "GO:0003674": "predicted"}
    # An absent reference stays absent instead of becoming "".
    assert {term.reference for term in section.terms} == {"PMID:1", None}
    assert section.source_name == "Synthetic GO fixture"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_annotation_section_never_reads_another_assembly(db_session):
    """A GO snapshot imported for v5 must not decorate a v4 gene.

    Ablation: the previous detail path read ``gene`` relationships only, so
    nothing crossed assemblies; a section query without ``assembly_id`` would
    reintroduce exactly that leak.
    """
    scope = await _scope(db_session)
    snapshot = await _annotation_set(db_session, scope, assembly=scope.v5)
    db_session.add(
        GeneAnnotation(
            annotation_set_id=snapshot.id,
            assembly_id=scope.v5.id,
            release_id=scope.release.id,
            ontology="go",
            gene_id=scope.gene_v4.accession,
            term_id="GO:0008150",
            term_name="biological process",
            evidence_code="EXP",
            reference="PMID:9",
        )
    )
    await db_session.flush()

    section = await load_annotation_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "not_imported"
    assert section.terms == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ambiguous_annotation_snapshots_are_refused(db_session):
    """Two snapshots for one scope would make the provenance a guess."""
    from sqlalchemy import text

    scope = await _scope(db_session)
    first = await _annotation_set(db_session, scope, assembly=scope.v4)
    await db_session.flush()
    # ``uq_gene_annotation_sets_scope`` forbids the real duplicate through the
    # ORM path; drop the constraint inside this savepoint to model a database
    # that already carries one, which is the state the reader must survive.
    await db_session.execute(
        text("ALTER TABLE gene_annotation_sets DROP CONSTRAINT uq_gene_annotation_sets_scope")
    )
    second = GeneAnnotationSet(
        assembly_id=scope.v4.id,
        release_id=scope.release.id,
        ontology="go",
        source_name="Conflicting fixture",
        source_version="2",
        source_url="https://example.org/go/v2",
        source_sha256="b" * 64,
        importer_version="1",
        row_count=1,
    )
    db_session.add(second)
    await db_session.flush()
    assert first.id != second.id

    section = await load_annotation_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "not_imported"
    assert section.terms == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_homolog_section_is_transferred_and_incomplete_data_stays_none(db_session):
    scope = await _scope(db_session)
    db_session.add(
        GeneHomolog(
            gene_id=scope.gene_v4.gene_pk,
            homolog_species="Arabidopsis thaliana",
            homolog_gene_id="AT1G01010",
            homolog_type="ortholog",
            source=None,
        )
    )
    await db_session.flush()

    section = await sections.load_homolog_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "available"
    record = section.records[0]
    assert record.kind == "transferred"
    # The import format has no method/confidence column: absent, not invented.
    assert record.method is None
    assert record.confidence is None
    assert record.source is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expression_section_keeps_unmeasured_units_absent(db_session):
    scope = await _scope(db_session)
    library = ExpressionLibrary(
        sample_id="S1",
        library_name="root control",
        tissue="root",
        treatment="control",
        assembly_id=scope.v4.id,
    )
    db_session.add(library)
    await db_session.flush()
    db_session.add(ExpressionData(gene_id=scope.gene_v4.gene_pk, library_id=library.id, tpm=12.5))
    await db_session.flush()

    section = await sections.load_expression_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "available"
    record = section.records[0]
    assert record.tpm == 12.5
    assert record.fpkm is None and record.raw_count is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expression_section_ignores_another_assembly_library(db_session):
    scope = await _scope(db_session)
    library = ExpressionLibrary(
        sample_id="S2",
        library_name="v5 library",
        tissue="root",
        treatment="control",
        assembly_id=scope.v5.id,
    )
    db_session.add(library)
    await db_session.flush()
    db_session.add(ExpressionData(gene_id=scope.gene_v4.gene_pk, library_id=library.id, tpm=1.0))
    await db_session.flush()

    section = await sections.load_expression_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "empty"
    assert section.records == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_variant_section_counts_only_the_resolved_release(db_session):
    scope = await _scope(db_session)
    other_release = Release(
        version=f"gene-center-other-{uuid4().hex[:8]}",
        name="other",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(other_release)
    await db_session.flush()
    chromosome_id = scope.gene_v4.chromosome_id
    for release_id, assembly_id in (
        (scope.release.id, scope.v4.id),
        (other_release.id, scope.v4.id),
        (scope.release.id, scope.v5.id),
    ):
        db_session.add(
            VariantSummary(
                assembly_id=assembly_id,
                chromosome_id=chromosome_id,
                position=10,
                ref="A",
                alt="T",
                variant_type="SNP",
                gene_id=scope.gene_v4.gene_pk,
                impact="HIGH",
                release_id=release_id,
            )
        )
    await db_session.flush()

    section = await sections.load_variant_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.total == 1
    assert section.by_impact == {"HIGH": 1}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phenotypes_are_reached_through_public_mutant_lines(db_session):
    scope = await _scope(db_session)
    line = MutantLine(
        public_id=f"SM{uuid4().hex[:8]}",
        name=f"line-{uuid4().hex[:6]}",
        is_public=True,
        release_id=scope.release.id,
    )
    hidden = MutantLine(
        name=f"hidden-{uuid4().hex[:6]}",
        is_public=False,
        release_id=scope.release.id,
    )
    deleted = MutantLine(
        public_id=f"SM{uuid4().hex[:8]}",
        name=f"deleted-{uuid4().hex[:6]}",
        is_public=True,
        release_id=scope.release.id,
        is_deleted=True,
    )
    foreign = MutantLine(
        public_id=f"SM{uuid4().hex[:8]}",
        name=f"foreign-{uuid4().hex[:6]}",
        is_public=True,
    )
    db_session.add_all([line, hidden, deleted, foreign])
    await db_session.flush()
    others = [
        (hidden, "unreleased sentinel trait"),
        (deleted, "deleted sentinel trait"),
        (foreign, "foreign-release sentinel trait"),
    ]
    rows = [
        VariantSummary(
            assembly_id=scope.v4.id,
            chromosome_id=scope.gene_v4.chromosome_id,
            position=20,
            ref="A",
            alt="T",
            variant_type="SNP",
            gene_id=scope.gene_v4.gene_pk,
            mutant_line_id=line.id,
            release_id=scope.release.id,
        ),
        Phenotype(
            mutant_line_id=line.id,
            trait_category="seed",
            trait_name="seed coat colour",
            trait_value="brown",
        ),
    ]
    for offset, (other, trait) in enumerate(others, start=1):
        rows.append(
            VariantSummary(
                assembly_id=scope.v4.id,
                chromosome_id=scope.gene_v4.chromosome_id,
                position=20 + offset,
                ref="A",
                alt="G",
                variant_type="SNP",
                gene_id=scope.gene_v4.gene_pk,
                mutant_line_id=other.id,
                release_id=scope.release.id,
            )
        )
        rows.append(
            Phenotype(mutant_line_id=other.id, trait_category="seed", trait_name=trait)
        )
    db_session.add_all(rows)
    await db_session.flush()

    section = await sections.load_phenotype_section(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    assert section.status.state == "available"
    # Unpublished, soft-deleted and other-release lines are neither listed nor
    # counted, and their sentinel traits never reach the payload.
    assert [record.trait_name for record in section.records] == ["seed coat colour"]
    payload = section.model_dump_json()
    for _, sentinel in others:
        assert sentinel not in payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_aggregate_reports_every_section_exactly_once(db_session):
    from app.schemas.gene_evidence import GENE_SECTIONS

    scope = await _scope(db_session)
    loaded = await sections.load_gene_sections(
        db_session, scope.gene_v4, release_context=_context(scope)
    )
    # The keys are exactly the ``GeneDetail`` fields that carry a section.
    from app.schemas.genomic import GeneDetail

    assert set(loaded) == {name for name in GeneDetail.model_fields if name.endswith("_section")}
    statuses = section_statuses(section.status for section in loaded.values())
    assert set(statuses) == set(GENE_SECTIONS)
    # Nothing was imported for this brand-new release, and that is stated as
    # such for the sections whose source is a release snapshot.
    assert statuses["annotation"].state == "not_imported"
    assert statuses["literature"].state == "not_imported"
    assert statuses["homolog"].state == "empty"

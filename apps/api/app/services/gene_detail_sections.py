"""The optional sections of a gene detail page, assembled in one place.

The gene route previously answered "what else is there about this gene?" with
whatever the requested relationships happened to hold. That loses the
distinction the platform has to keep: a section can be **empty** (the release
has the data, this gene has none) or **not imported** (the release has no
snapshot at all). Rendering both as an empty table tells a researcher that a
gene has no GO terms when the truth is that GO was never loaded for this
assembly.

Every block below therefore returns a :class:`SectionStatus` alongside its
rows, and this module is the only place that decides which of the two states
applies. It never fabricates a count: an absent snapshot reports
``count=None`` with ``state="not_imported"``.

Scope contract: every query is bound to the resolved release *and* the gene's
own assembly. There is no fallback to another assembly and no "closest"
release -- see ``docs/dev/database-core-contract.md`` (ASM-01..03).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.expression import ExpressionData, ExpressionLibrary
from ..models.gene_annotation import GeneAnnotation, GeneAnnotationSet
from ..models.genomic import Gene
from ..models.homolog import GeneHomolog
from ..models.variant import MutantLine, Phenotype, VariantSummary
from ..schemas.gene_evidence import (
    EVIDENCE_KINDS,
    AnnotationSection,
    AnnotationTerm,
    EvidenceTag,
    ExpressionRecord,
    ExpressionSection,
    HomologRecord,
    HomologSection,
    LiteratureSection,
    PhenotypeRecord,
    PhenotypeSection,
    SectionStatus,
    VariantSection,
)
from .release_context import ReleaseContext

#: The status a section gets when its source snapshot is absent for this
#: release/assembly. Machine-readable and stable: clients key on the prefix.
NOT_IMPORTED = "not_imported"

#: GO evidence code -> evidence class (Gene Ontology evidence-code table).
#: Incomplete on purpose: an unknown code maps to ``unknown``, because guessing
#: "this is experimental" from an unfamiliar two-letter token would upgrade a
#: claim the source never made.
_GO_EVIDENCE_KINDS: dict[str, str] = {
    # Experimental
    "EXP": "experimental",
    "IDA": "experimental",
    "IPI": "experimental",
    "IMP": "experimental",
    "IGI": "experimental",
    "IEP": "experimental",
    "HDA": "experimental",
    "HMP": "experimental",
    "HGI": "experimental",
    "HEP": "experimental",
    # Curated / reviewed
    "IC": "curated",
    "TAS": "curated",
    "NAS": "curated",
    # Computational
    "ISS": "predicted",
    "ISO": "predicted",
    "ISA": "predicted",
    "ISM": "predicted",
    "IGC": "predicted",
    "RCA": "predicted",
    "IEA": "predicted",
    # Transferred from another species by sequence/orthology
    "IBA": "transferred",
    "IBD": "transferred",
    "IKR": "transferred",
    "IRD": "transferred",
    "ISS_ORTHOLOGY": "transferred",
}


def annotation_evidence_kind(code: str | None) -> str:
    """Map a GO evidence code to the shared evidence vocabulary.

    An empty or unrecognised code is ``unknown``: the row exists, but nothing
    in it says how it was produced, and an unlabelled row must not inherit the
    section's strongest label.
    """
    if not code:
        return "unknown"
    kind = _GO_EVIDENCE_KINDS.get(code.strip().upper())
    return kind if kind in EVIDENCE_KINDS else "unknown"


def homolog_evidence_kind() -> str:
    """Homolog rows are always ``transferred``.

    A homolog record describes another locus found in another species; it is
    evidence transferred by homology, never a measurement of this gene.
    """
    return "transferred"


def _status(
    section: str,
    *,
    count: int | None,
    evidence: EvidenceTag | None = None,
    reason: str | None = None,
) -> SectionStatus:
    """Build a section status, choosing ``empty`` vs ``not_imported``.

    ``count is None`` means the source is absent; there is deliberately no way
    to express "0 rows, source unknown" as a count, because that is exactly the
    ambiguity the portal must not render.
    """
    if count is None:
        return SectionStatus(
            section=section,  # type: ignore[arg-type]
            state=NOT_IMPORTED,  # type: ignore[arg-type]
            count=None,
            evidence=evidence,
            reason=reason or NOT_IMPORTED,
        )
    return SectionStatus(
        section=section,  # type: ignore[arg-type]
        state="available" if count else "empty",  # type: ignore[arg-type]
        count=count,
        evidence=evidence,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Annotation (GO + KEGG)
# ---------------------------------------------------------------------------

#: Ontologies a gene page groups separately, in display order.
ANNOTATION_ONTOLOGIES = ("go", "kegg")


async def _annotation_snapshot(
    db: AsyncSession,
    *,
    assembly_id: int,
    release_context: ReleaseContext,
    ontology: str,
) -> GeneAnnotationSet | None:
    """The release/assembly-scoped snapshot for one ontology, or ``None``.

    Two matching snapshots would make the provenance ambiguous, so the query
    asks for two and treats a second row as "absent" rather than picking one:
    the enrichment service refuses the same situation, and a gene page must not
    be more permissive than the analysis tool that reads the same tables.
    """
    result = await db.execute(
        select(GeneAnnotationSet)
        .where(
            GeneAnnotationSet.assembly_id == assembly_id,
            GeneAnnotationSet.release_id == release_context.release_id,
            GeneAnnotationSet.ontology == ontology,
        )
        .limit(2)
    )
    snapshots = list(result.scalars().all())
    return snapshots[0] if len(snapshots) == 1 else None


async def load_annotation_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> AnnotationSection:
    """GO/KEGG terms for one gene, with per-term evidence and one snapshot.

    Terms from several ontologies are returned together but each row keeps its
    own ``ontology``; the section status is the *snapshot* status, so a release
    with a GO snapshot but no KEGG one reports ``available`` and the client can
    see which ontologies produced rows from the terms themselves.
    """
    snapshots = {}
    for ontology in ANNOTATION_ONTOLOGIES:
        snapshot = await _annotation_snapshot(
            db,
            assembly_id=gene.assembly_id,
            release_context=release_context,
            ontology=ontology,
        )
        if snapshot is not None:
            snapshots[ontology] = snapshot

    if not snapshots:
        return AnnotationSection(
            status=_status(
                "annotation",
                count=None,
                reason="annotation_set_missing",
            )
        )

    result = await db.execute(
        select(GeneAnnotation)
        .where(
            GeneAnnotation.gene_id == gene.accession,
            GeneAnnotation.assembly_id == gene.assembly_id,
            GeneAnnotation.release_id == release_context.release_id,
            GeneAnnotation.annotation_set_id.in_([snapshot.id for snapshot in snapshots.values()]),
        )
        .order_by(GeneAnnotation.ontology, GeneAnnotation.term_id)
    )
    rows = list(result.scalars().all())
    terms = [
        AnnotationTerm(
            ontology=row.ontology,  # type: ignore[arg-type]
            term_id=row.term_id,
            term_name=row.term_name,
            evidence_code=row.evidence_code or None,
            kind=annotation_evidence_kind(row.evidence_code),  # type: ignore[arg-type]
            reference=row.reference or None,
            qualifier=row.qualifier or None,
        )
        for row in rows
    ]
    # Provenance names the snapshot(s) actually read. With both ontologies
    # present the source string lists both rather than pretending one covers
    # the other.
    first = snapshots[sorted(snapshots)[0]]
    source_name = first.source_name
    if len(snapshots) > 1:
        source_name = " + ".join(snapshots[key].source_name for key in sorted(snapshots))
    return AnnotationSection(
        status=_status(
            "annotation",
            count=len(terms),
            evidence=EvidenceTag(kind="imported", source=source_name[:256]),
        ),
        terms=terms,
        source_name=source_name,
        source_version=first.source_version,
        source_url=first.source_url,
    )


# ---------------------------------------------------------------------------
# Homology
# ---------------------------------------------------------------------------


async def load_homolog_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> HomologSection:
    """Homolog rows for one gene.

    ``gene_homologs`` carries no release column, so the scope is the gene's own
    assembly inside the resolved release -- the same join the public homolog
    route uses.
    """
    result = await db.execute(
        select(GeneHomolog)
        .where(GeneHomolog.gene_id == gene.gene_pk)
        .order_by(GeneHomolog.homolog_species, GeneHomolog.homolog_gene_id)
    )
    rows = list(result.scalars().all())

    sources = sorted({row.source for row in rows if row.source})
    records = [
        HomologRecord(
            homolog_species=row.homolog_species,
            homolog_gene_id=row.homolog_gene_id,
            homolog_type=row.homolog_type,  # type: ignore[arg-type]
            # The import format has no method column today; ``None`` states
            # that instead of inventing "blast" or "orthofinder".
            method=None,
            source=row.source or None,
            kind=homolog_evidence_kind(),  # type: ignore[arg-type]
            confidence=None,
        )
        for row in rows
    ]
    evidence = EvidenceTag(kind="transferred", source=", ".join(sources)[:256]) if sources else None
    return HomologSection(
        status=_status("homolog", count=len(records), evidence=evidence),
        records=records,
    )


# ---------------------------------------------------------------------------
# Expression
# ---------------------------------------------------------------------------


async def load_expression_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> ExpressionSection:
    """Expression values for one gene, never 0 for "not measured"."""
    result = await db.execute(
        select(ExpressionData)
        .join(ExpressionLibrary, ExpressionData.library_id == ExpressionLibrary.id)
        .where(
            ExpressionData.gene_id == gene.gene_pk,
            # A library belongs to one assembly; a v5 library must never be
            # listed next to v4 coordinates.
            ExpressionLibrary.assembly_id == gene.assembly_id,
        )
        .order_by(ExpressionLibrary.library_name)
    )
    rows = list(result.scalars().all())
    if not rows:
        # The platform holds no study-level snapshot entity for expression, so
        # "no rows" is reported as an empty section rather than claiming the
        # release never carried an experiment it might have carried.
        return ExpressionSection(status=_status("expression", count=0))

    records = [
        ExpressionRecord(
            library_id=str(row.library.sample_id),
            library_name=row.library.library_name,
            tissue=row.library.tissue or None,
            treatment=row.library.treatment or None,
            stage=row.library.developmental_stage or None,
            tpm=row.tpm,
            fpkm=row.fpkm,
            raw_count=row.raw_count,
        )
        for row in rows
    ]
    return ExpressionSection(
        status=_status(
            "expression",
            count=len(records),
            evidence=EvidenceTag(kind="experimental", source="expression_libraries"),
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


async def load_variant_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> VariantSection:
    """Variant totals for the gene in the resolved release *and* assembly."""
    scope = and_(
        VariantSummary.gene_id == gene.gene_pk,
        VariantSummary.release_id == release_context.release_id,
        VariantSummary.assembly_id == gene.assembly_id,
    )
    rows = (
        await db.execute(
            select(VariantSummary.impact, func.count()).where(scope).group_by(VariantSummary.impact)
        )
    ).all()
    by_impact: dict[str, int] = {}
    for impact, count in rows:
        # An unannotated impact is reported under ``unknown`` rather than
        # dropped: a variant with no consequence prediction is still a variant.
        by_impact[str(impact) if impact is not None else "unknown"] = int(count)
    total = sum(by_impact.values())
    return VariantSection(
        status=_status(
            "variants",
            count=total,
            evidence=EvidenceTag(kind="predicted", source="variant_annotation"),
        ),
        total=total,
        by_impact=by_impact,
    )


# ---------------------------------------------------------------------------
# Phenotypes
# ---------------------------------------------------------------------------


async def load_phenotype_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> PhenotypeSection:
    """Phenotypes reached through variants and their mutant lines.

    Only public mutant lines are read: a phenotype record is a statement about
    a line, and an unpublished line is not part of the public record. The
    mutant is identified by ``public_id``; the internal row key never leaves
    the API.
    """
    result = await db.execute(
        select(Phenotype, MutantLine)
        .join(MutantLine, Phenotype.mutant_line_id == MutantLine.id)
        .join(VariantSummary, VariantSummary.mutant_line_id == MutantLine.id)
        .where(
            VariantSummary.gene_id == gene.gene_pk,
            VariantSummary.release_id == release_context.release_id,
            VariantSummary.assembly_id == gene.assembly_id,
            MutantLine.is_public.is_(True),
        )
        .order_by(MutantLine.name, Phenotype.trait_category, Phenotype.trait_name)
    )
    seen: set[tuple[int, str, str]] = set()
    records: list[PhenotypeRecord] = []
    for phenotype, line in result.all():
        key = (line.id, phenotype.trait_category, phenotype.trait_name)
        if key in seen:
            # A line linked through several variants would otherwise repeat its
            # phenotype once per variant.
            continue
        seen.add(key)
        if line.public_id is None:
            # Publication requires a public id; a row without one is not
            # addressable publicly and must not be exposed by name either.
            continue
        records.append(
            PhenotypeRecord(
                mutant_public_id=line.public_id,
                mutant_name=line.name,
                trait_category=phenotype.trait_category,
                trait_name=phenotype.trait_name,
                trait_value=phenotype.trait_value,
                unit=phenotype.unit,
                measurement_method=phenotype.measurement_method,
            )
        )
    return PhenotypeSection(
        status=_status(
            "phenotype",
            count=len(records),
            evidence=EvidenceTag(kind="experimental", source="phenotypes"),
        ),
        records=records,
    )


# ---------------------------------------------------------------------------
# Literature
# ---------------------------------------------------------------------------


async def load_literature_section(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> LiteratureSection:
    """Publications the gene record itself cites.

    There is no gene -> publication relation in the schema yet. The section
    therefore reports ``not_imported`` with an explicit reason instead of
    returning unrelated publications, and when the relation lands only this
    function changes -- the wire shape and the status vocabulary do not.
    """
    del db, gene, release_context
    return LiteratureSection(
        status=_status("literature", count=None, reason="gene_literature_link_missing"),
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


async def load_gene_sections(
    db: AsyncSession,
    gene: Gene,
    *,
    release_context: ReleaseContext,
) -> dict[str, Any]:
    """Every optional gene-detail section, each with its own status."""
    return {
        "annotation_section": await load_annotation_section(
            db, gene, release_context=release_context
        ),
        "homolog_section": await load_homolog_section(db, gene, release_context=release_context),
        "expression_section": await load_expression_section(
            db, gene, release_context=release_context
        ),
        "variants_section": await load_variant_section(db, gene, release_context=release_context),
        "phenotype_section": await load_phenotype_section(
            db, gene, release_context=release_context
        ),
        "literature_section": await load_literature_section(
            db, gene, release_context=release_context
        ),
    }


def section_statuses(sections: Iterable[SectionStatus]) -> dict[str, SectionStatus]:
    """Index section statuses by name for exhaustive checks and tests."""
    return {status.section: status for status in sections}


__all__ = [
    "ANNOTATION_ONTOLOGIES",
    "NOT_IMPORTED",
    "annotation_evidence_kind",
    "homolog_evidence_kind",
    "load_annotation_section",
    "load_expression_section",
    "load_gene_sections",
    "load_homolog_section",
    "load_literature_section",
    "load_phenotype_section",
    "load_variant_section",
    "section_statuses",
]

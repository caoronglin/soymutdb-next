"""Queries for the guarded, unpublished local test-data preview."""

from __future__ import annotations

import re

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.content import Release, ReleaseStatus
from ..models.genomic import Assembly, Chromosome, Gene
from ..models.local_test_preview import LocalTestMutationSite
from ..schemas.local_test_preview import (
    LocalTestPreviewMeta,
    PreviewAssembly,
    PreviewChromosome,
    PreviewDatasetSource,
    PreviewGeneItem,
    PreviewGeneSearchResponse,
    PreviewMutationSiteItem,
    PreviewMutationSiteSearchResponse,
)

PREVIEW_DATASET_KEY = "03_soymut-a6-test"
PREVIEW_RELEASE_VERSION = "local-test-a6-v1"
PREVIEW_ASSEMBLY_NAME = "Gmax_880_v6.0"
PREVIEW_ASSEMBLY_VERSION = "v6.0"
PREVIEW_ANNOTATION_VERSION = "Wm82.a6.v1"
MAX_GENE_IDS = 100


async def get_preview_meta(db: AsyncSession) -> LocalTestPreviewMeta:
    """Return the one imported preview dataset and its explicit v6 context."""
    assembly = await _get_preview_assembly(db)
    sample = await db.scalar(
        select(LocalTestMutationSite)
        .where(
            LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
            LocalTestMutationSite.assembly_id == assembly.id,
            LocalTestMutationSite.release_id == assembly.release_id,
        )
        .order_by(LocalTestMutationSite.id)
        .limit(1)
    )
    if sample is None:
        raise NotFoundError("The local preview dataset has not been imported")

    row_count = int(
        await db.scalar(
            select(func.count())
            .select_from(LocalTestMutationSite)
            .where(
                LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
                LocalTestMutationSite.assembly_id == assembly.id,
                LocalTestMutationSite.release_id == assembly.release_id,
            )
        )
        or 0
    )
    gene_count = int(
        await db.scalar(
            select(func.count())
            .select_from(Gene)
            .where(Gene.assembly_id == assembly.id)
        )
        or 0
    )
    chromosomes = await db.execute(
        select(Chromosome.name, Chromosome.length)
        .where(Chromosome.assembly_id == assembly.id)
        .order_by(Chromosome.order)
    )

    return LocalTestPreviewMeta(
        dataset=PreviewDatasetSource(
            source_file=sample.source_file,
            source_sha256=sample.source_sha256,
            row_count=row_count,
            annotation_file=sample.annotation_file,
            annotation_sha256=sample.annotation_sha256,
            annotation_gene_count=gene_count,
        ),
        assembly=PreviewAssembly(),
        chromosomes=[
            PreviewChromosome(name=name, length=int(length))
            for name, length in chromosomes.all()
        ],
    )


async def search_preview_genes(
    db: AsyncSession,
    gene_id: str,
    *,
    limit: int = 100,
) -> PreviewGeneSearchResponse:
    """Resolve exact v6 GFF accessions (or their exact GFF ``Name`` value)."""
    identifiers = _parse_gene_ids(gene_id)
    if not 1 <= limit <= 100:
        raise ValidationError("limit must be between 1 and 100")
    assembly = await _get_preview_assembly(db)
    identity_filter = or_(
        Gene.accession.in_(identifiers),
        Gene.name.in_(identifiers),
    )
    base = (
        select(Gene.gene_pk)
        .where(Gene.assembly_id == assembly.id, identity_filter)
    )
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)

    site_count_join = and_(
        LocalTestMutationSite.gene_pk == Gene.gene_pk,
        LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
        LocalTestMutationSite.assembly_id == assembly.id,
        LocalTestMutationSite.release_id == assembly.release_id,
    )
    # Count the sites in a correlated scalar subquery instead of an aggregate
    # join: ``Gene`` eagerly loads its assembly, release and chromosome
    # relationships, so a GROUP BY over the entity would have to enumerate every
    # joined table — which PostgreSQL rejects with "must appear in the GROUP BY
    # clause" the moment a relationship is added to the model. A scalar
    # subquery keeps the count and the entity independent.
    site_count = (
        select(func.count(LocalTestMutationSite.id))
        .where(site_count_join)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(Gene, Chromosome.name, site_count.label("site_count"))
        .join(Chromosome, Chromosome.id == Gene.chromosome_id)
        .where(Gene.assembly_id == assembly.id, identity_filter)
        .order_by(Chromosome.order, Gene.start, Gene.accession)
        .limit(limit)
    )
    items = [
        PreviewGeneItem(
            gene_id=gene.accession,
            gene_symbol=gene.name,
            chromosome=chromosome,
            start_pos=gene.start,
            end_pos=gene.end,
            strand=gene.strand,
            biotype=gene.biotype,
            mutation_site_count=int(site_count),
        )
        for gene, chromosome, site_count in rows.all()
    ]
    return PreviewGeneSearchResponse(
        assembly=PreviewAssembly(),
        query=gene_id,
        total=total,
        limit=limit,
        items=items,
    )


async def search_preview_mutation_sites(
    db: AsyncSession,
    *,
    chromosome: str,
    start: int,
    end: int,
    limit: int = 1000,
) -> PreviewMutationSiteSearchResponse:
    """Return source mutation-site records in a 1-based inclusive interval."""
    if start < 1 or end < start:
        raise ValidationError("start/end must define a positive 1-based interval")
    if not 1 <= limit <= 1000:
        raise ValidationError("limit must be between 1 and 1000")

    assembly = await _get_preview_assembly(db)
    chromosome_row = await db.scalar(
        select(Chromosome).where(
            Chromosome.assembly_id == assembly.id,
            Chromosome.name == chromosome,
        )
    )
    if chromosome_row is None:
        raise ValidationError(
            f"Unknown chromosome for {PREVIEW_ASSEMBLY_NAME}: {chromosome}"
        )

    filters = (
        LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
        LocalTestMutationSite.assembly_id == assembly.id,
        LocalTestMutationSite.release_id == assembly.release_id,
        LocalTestMutationSite.chromosome_id == chromosome_row.id,
        LocalTestMutationSite.position >= start,
        LocalTestMutationSite.position <= end,
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(LocalTestMutationSite)
            .where(*filters)
        )
        or 0
    )
    rows = await db.execute(
        select(LocalTestMutationSite, Gene.accession)
        .join(Gene, Gene.gene_pk == LocalTestMutationSite.gene_pk)
        .where(
            *filters,
            Gene.assembly_id == assembly.id,
        )
        .order_by(LocalTestMutationSite.position, LocalTestMutationSite.source_site_key)
        .limit(limit)
    )
    items = [
        PreviewMutationSiteItem(
            source_site_key=site.source_site_key,
            mutant_line_name=site.mutant_line_name,
            chromosome=chromosome_row.name,
            position=site.position,
            confidence=site.confidence,
            gene_id=gene_accession,
            feature=site.feature,
            available=site.available,
            gene_v2=site.gene_v2,
            gene_v4=site.gene_v4,
            gene_dn53=site.gene_dn53,
        )
        for site, gene_accession in rows.all()
    ]
    return PreviewMutationSiteSearchResponse(
        assembly=PreviewAssembly(),
        chromosome=chromosome_row.name,
        start=start,
        end=end,
        total=total,
        limit=limit,
        items=items,
    )


async def _get_preview_assembly(db: AsyncSession) -> Assembly:
    """Resolve only the known draft preview release and its v6 assembly."""
    table_exists = await db.scalar(
        text("SELECT to_regclass('local_preview_mutation_sites')")
    )
    if table_exists is None:
        raise NotFoundError("The local preview dataset has not been imported")
    result = await db.execute(
        select(Assembly)
        .join(Release, Assembly.release_id == Release.id)
        .where(
            Assembly.name == PREVIEW_ASSEMBLY_NAME,
            Assembly.version == PREVIEW_ASSEMBLY_VERSION,
            Release.version == PREVIEW_RELEASE_VERSION,
            Release.status == ReleaseStatus.DRAFT.value,
        )
    )
    assembly = result.scalars().one_or_none()
    if assembly is None:
        raise NotFoundError("The local preview dataset has not been imported")
    return assembly


def _parse_gene_ids(value: str) -> list[str]:
    parts = (part.strip() for part in re.split(r"[,;\r\n]+", value))
    identifiers = list(dict.fromkeys(part for part in parts if part))
    if not identifiers:
        raise ValidationError("gene_id must contain at least one exact identifier")
    if len(identifiers) > MAX_GENE_IDS:
        raise ValidationError(f"gene_id supports at most {MAX_GENE_IDS} identifiers")
    if any(len(identifier) > 64 for identifier in identifiers):
        raise ValidationError("gene identifiers must not exceed 64 characters")
    return identifiers


async def list_preview_mutation_sites_for_gene(
    db: AsyncSession,
    *,
    gene_id: str,
    limit: int = 1000,
) -> list[PreviewMutationSiteItem]:
    """Return every source mutation-site row attached to one gene.

    Keyed on the gene relation rather than on a coordinate interval: 13% of the
    source rows sit up- or downstream of their gene's own start/end (the TSV's
    ``feature`` column carries that offset), so an interval query would silently
    drop them.
    """
    if not 1 <= limit <= 1000:
        raise ValidationError("limit must be between 1 and 1000")

    assembly = await _get_preview_assembly(db)
    scope = (
        LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
        LocalTestMutationSite.assembly_id == assembly.id,
        LocalTestMutationSite.release_id == assembly.release_id,
        Gene.assembly_id == assembly.id,
    )

    async def load(*criteria) -> list:
        statement = (
            select(LocalTestMutationSite, Gene.accession, Chromosome.name)
            .join(Gene, Gene.gene_pk == LocalTestMutationSite.gene_pk)
            .join(Chromosome, Chromosome.id == LocalTestMutationSite.chromosome_id)
            .where(*scope, *criteria)
            .order_by(LocalTestMutationSite.position, LocalTestMutationSite.source_site_key)
            .limit(limit)
        )
        return list((await db.execute(statement)).all())

    # Exact identifiers only — the operator asked for a full match, so a bare or
    # partial string (`Glyma.01G000100`, `Gl`) must not resolve. Two things count
    # as exact: this assembly's own versioned accession
    # (`Glyma.01G000100.Wm82.a6.v1`), or any of the three homolog accessions the
    # source table records for the same row (W82_V2 / W82_V4 / DN53_V1).
    #
    # This assembly's identifier wins when both would match: a string such as
    # `Glyma.02G115200` is a real locus in this assembly *and* another locus's
    # W82_V2 accession, and those belong to different coordinate namespaces, so
    # returning both in one pass would silently merge them.
    rows = await load(Gene.accession == gene_id)
    if not rows:
        rows = await load(
            or_(
                LocalTestMutationSite.gene_v2 == gene_id,
                LocalTestMutationSite.gene_v4 == gene_id,
                LocalTestMutationSite.gene_dn53 == gene_id,
            )
        )
    return [
        PreviewMutationSiteItem(
            source_site_key=site.source_site_key,
            mutant_line_name=site.mutant_line_name,
            chromosome=chromosome_name,
            position=site.position,
            confidence=site.confidence,
            gene_id=gene_accession,
            feature=site.feature,
            available=site.available,
            gene_v2=site.gene_v2,
            gene_v4=site.gene_v4,
            gene_dn53=site.gene_dn53,
        )
        for site, gene_accession, chromosome_name in rows
    ]


async def update_preview_mutation_site(
    db: AsyncSession,
    *,
    source_site_key: str,
    available: bool,
) -> PreviewMutationSiteItem:
    """Set the operator-maintained ``available`` flag on one source row.

    Only this column is writable: every other field is the uploaded table's
    content and is rewritten on the next import.
    """
    assembly = await _get_preview_assembly(db)
    row = (
        await db.execute(
            select(LocalTestMutationSite, Gene.accession, Chromosome.name)
            .join(Gene, Gene.gene_pk == LocalTestMutationSite.gene_pk)
            .join(Chromosome, Chromosome.id == LocalTestMutationSite.chromosome_id)
            .where(
                LocalTestMutationSite.dataset_key == PREVIEW_DATASET_KEY,
                LocalTestMutationSite.assembly_id == assembly.id,
                LocalTestMutationSite.release_id == assembly.release_id,
                LocalTestMutationSite.source_site_key == source_site_key,
            )
        )
    ).first()
    if row is None:
        raise NotFoundError(f"Unknown source mutation site: {source_site_key}")

    site, gene_accession, chromosome_name = row
    site.available = available
    await db.commit()
    return PreviewMutationSiteItem(
        source_site_key=site.source_site_key,
        mutant_line_name=site.mutant_line_name,
        chromosome=chromosome_name,
        position=site.position,
        confidence=site.confidence,
        gene_id=gene_accession,
        feature=site.feature,
        available=site.available,
        gene_v2=site.gene_v2,
        gene_v4=site.gene_v4,
        gene_dn53=site.gene_dn53,
    )


__all__ = [
    "PREVIEW_ANNOTATION_VERSION",
    "PREVIEW_ASSEMBLY_NAME",
    "PREVIEW_ASSEMBLY_VERSION",
    "PREVIEW_DATASET_KEY",
    "PREVIEW_RELEASE_VERSION",
    "get_preview_meta",
    "list_preview_mutation_sites_for_gene",
    "search_preview_genes",
    "search_preview_mutation_sites",
    "update_preview_mutation_site",
]

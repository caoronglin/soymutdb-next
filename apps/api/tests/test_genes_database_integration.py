"""Real-PostgreSQL read path for genes: release isolation + promoted columns.

The mocked suites (test_genes.py) assert the query contract; this one runs the
real SQL against the migrated schema, so the release-scoped join
(``Assembly.release_id == release_context.release_id``) and the columns written
by the ADR-0004 module promotion (accession, coordinates, strand, biotype) are
exercised together. The portal resolves PUBLISHED releases only, and the same
accession is a distinct record per assembly namespace.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Release, ReleaseStatus
from app.models.genomic import Assembly, Chromosome, Gene
from app.schemas.genomic import GeneListParams
from app.services.gene_service import GeneService
from app.services.release_context import ReleaseContext


async def _seed_release_with_gene(
    db: AsyncSession,
    *,
    version: str,
    start: int,
    end: int,
    mutation_feature: str | None = None,
) -> tuple[Release, Assembly, Gene]:
    """Seed one published release -> assembly -> chromosome -> promoted gene."""
    release = Release(
        name=f"Integration {version}",
        version=version,
        status=ReleaseStatus.PUBLISHED.value,
    )
    db.add(release)
    await db.flush()
    assembly = Assembly(name=f"Wm82 {version}", version=f"asm-{version}", release_id=release.id)
    db.add(assembly)
    await db.flush()
    chromosome = Chromosome(
        assembly_id=assembly.id, name="Chr01", length=end, order=0
    )
    db.add(chromosome)
    await db.flush()
    gene = Gene(
        accession="Glyma.01G000100",
        assembly_id=assembly.id,
        chromosome_id=chromosome.id,
        start=start,
        end=end,
        strand="+",
        biotype="protein_coding",
        attributes={"mutation_feature": mutation_feature} if mutation_feature else None,
    )
    db.add(gene)
    await db.flush()
    return release, assembly, gene


async def test_genes_read_is_release_scoped_and_reflects_promoted_rows(
    db_session: AsyncSession,
) -> None:
    first_release, first_assembly, first_gene = await _seed_release_with_gene(
        db_session, version="it-genes-r1", start=1000, end=2000, mutation_feature="EMS"
    )
    second_release, second_assembly, _ = await _seed_release_with_gene(
        db_session, version="it-genes-r2", start=5000, end=6000
    )

    service = GeneService()
    first_page = await service.list_genes(
        db_session,
        GeneListParams(),
        release_context=ReleaseContext(
            release_id=first_release.id, assembly_id=first_assembly.id
        ),
    )
    # Same accession in both assemblies: only the requested release's row is
    # visible, with that release's coordinates.
    assert [gene.gene_id for gene in first_page.items] == ["Glyma.01G000100"]
    assert (first_page.items[0].start, first_page.items[0].end) == (1000, 2000)
    assert first_page.items[0].chromosome == "Chr01"
    assert first_page.items[0].strand == "+"
    assert first_page.items[0].biotype == "protein_coding"

    second_page = await service.list_genes(
        db_session,
        GeneListParams(),
        release_context=ReleaseContext(
            release_id=second_release.id, assembly_id=second_assembly.id
        ),
    )
    assert [(gene.start, gene.end) for gene in second_page.items] == [(5000, 6000)]

    # The promoted annotation is not part of the public response, but it must
    # survive on the canonical row for consumers that read the model.
    stored = (
        await db_session.execute(
            select(Gene.attributes).where(Gene.gene_pk == first_gene.gene_pk)
        )
    ).scalar_one()
    assert stored == {"mutation_feature": "EMS"}

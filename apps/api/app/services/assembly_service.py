"""Assembly reads with counts aggregated from rows, never from release totals.

``Release.gene_count`` / ``Release.variant_count`` are denormalised counters for
a *release*, and one release owns many assemblies. Copying such a counter onto
each assembly would make two assemblies in the same release both report the
whole release's gene count — numbers that look precise and are wrong. Every
figure below therefore comes from an aggregate over rows that carry the
assembly id themselves.

``download_files`` is the one dimension that cannot be aggregated. It has
``release_id`` but no ``assembly_id``, and its ``category`` is free text, so
there is no relation between a download and an assembly to count over. That
field is returned as ``None`` with a reason instead of being guessed.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError
from ..models.genomic import Assembly, Chromosome, Gene, Transcript
from ..schemas.genomic import (
    AssemblyDetailResponse,
    AssemblyMetric,
    AssemblyStatistics,
    AssemblySummaryResponse,
    ChromosomeResponse,
)

#: Stated once, returned to the client, so a missing number is explained rather
#: than read as a zero. These are machine-readable codes: the portal maps them to
#: sentences, and an unrecognised code is still passed through rather than hidden.
DOWNLOAD_COUNT_UNAVAILABLE = "no_linked_downloads"
NO_GENES = "no_genes"
NO_TRANSCRIPTS = "no_transcripts"
NO_CHROMOSOMES = "no_chromosomes"


class AssemblyService:
    """Read-side assembly queries bound to a resolved release."""

    async def list_assemblies(
        self, db: AsyncSession, *, release_id: int
    ) -> list[AssemblySummaryResponse]:
        """Return this release's assemblies, each with its own counts."""
        assemblies = list(
            (
                await db.execute(
                    select(Assembly)
                    .where(Assembly.release_id == release_id)
                    .order_by(Assembly.name)
                )
            )
            .scalars()
            .all()
        )
        if not assemblies:
            return []
        assembly_ids = [assembly.id for assembly in assemblies]
        statistics = await self._statistics_for(db, assembly_ids)
        return [
            self._summary(assembly, statistics.get(assembly.id, _empty_statistics()))
            for assembly in assemblies
        ]

    async def get_assembly(
        self, db: AsyncSession, assembly_id: int, *, release_id: int
    ) -> AssemblyDetailResponse:
        """Return one assembly of this release with its chromosomes.

        Existence is judged the same way ``GeneService.list_chromosomes``
        judges it: a join on ``Assembly.release_id``. An assembly outside the
        resolved release is indistinguishable from one that does not exist, so
        the 404 discloses neither the row nor its release.
        """
        assembly = (
            await db.execute(
                select(Assembly)
                .where(Assembly.id == assembly_id)
                .where(Assembly.release_id == release_id)
            )
        ).scalar_one_or_none()
        if assembly is None:
            raise NotFoundError(f"Assembly {assembly_id} not found in this release")

        statistics = await self._statistics_for(db, [assembly.id])
        chromosomes = list(
            (
                await db.execute(
                    select(Chromosome)
                    .where(Chromosome.assembly_id == assembly.id)
                    .order_by(Chromosome.order)
                )
            )
            .scalars()
            .all()
        )
        summary = self._summary(assembly, statistics.get(assembly.id, _empty_statistics()))
        return AssemblyDetailResponse(
            **summary.model_dump(),
            chromosomes=[
                ChromosomeResponse(
                    id=str(chromosome.id),
                    assembly_id=str(chromosome.assembly_id),
                    name=chromosome.name,
                    length=chromosome.length,
                    order=chromosome.order,
                )
                for chromosome in chromosomes
            ],
        )

    async def _statistics_for(
        self, db: AsyncSession, assembly_ids: list[int]
    ) -> dict[int, AssemblyStatistics]:
        """Aggregate the countable dimensions for *assembly_ids*, in one pass each."""
        gene_counts = await self._gene_counts(db, assembly_ids)
        transcript_counts = await self._transcript_counts(db, assembly_ids)
        chromosome_counts, total_lengths = await self._chromosome_totals(db, assembly_ids)

        return {
            assembly_id: AssemblyStatistics(
                # A count that ran and found nothing is a real ``0``: the
                # aggregate answered, and the answer was zero. Only a count
                # nobody could run is ``None``, and it says why.
                gene_count=AssemblyMetric(value=gene_counts.get(assembly_id, 0)),
                transcript_count=AssemblyMetric(value=transcript_counts.get(assembly_id, 0)),
                chromosome_count=AssemblyMetric(value=chromosome_counts.get(assembly_id, 0)),
                total_length=AssemblyMetric(value=total_lengths.get(assembly_id, 0)),
                # Never a number: there is nothing to aggregate it over.
                download_count=AssemblyMetric(reason=DOWNLOAD_COUNT_UNAVAILABLE),
            )
            for assembly_id in assembly_ids
        }

    async def _gene_counts(self, db: AsyncSession, assembly_ids: list[int]) -> dict[int, int]:
        rows = await db.execute(
            select(Gene.assembly_id, func.count(Gene.gene_pk))
            .where(Gene.assembly_id.in_(assembly_ids))
            .group_by(Gene.assembly_id)
        )
        return {int(assembly_id): int(count) for assembly_id, count in rows.all()}

    async def _transcript_counts(
        self, db: AsyncSession, assembly_ids: list[int]
    ) -> dict[int, int]:
        # ``transcripts`` has ``gene_id`` and no assembly of its own, so the
        # assembly predicate has to travel through ``genes``. Joining
        # ``assemblies`` instead would count every transcript of a release's
        # other assemblies too.
        rows = await db.execute(
            select(Gene.assembly_id, func.count(Transcript.id))
            .join(Gene, Transcript.gene_id == Gene.gene_pk)
            .where(Gene.assembly_id.in_(assembly_ids))
            .group_by(Gene.assembly_id)
        )
        return {int(assembly_id): int(count) for assembly_id, count in rows.all()}

    async def _chromosome_totals(
        self, db: AsyncSession, assembly_ids: list[int]
    ) -> tuple[dict[int, int], dict[int, int]]:
        rows = await db.execute(
            select(
                Chromosome.assembly_id,
                func.count(Chromosome.id),
                func.coalesce(func.sum(Chromosome.length), 0),
            )
            .where(Chromosome.assembly_id.in_(assembly_ids))
            .group_by(Chromosome.assembly_id)
        )
        counts: dict[int, int] = {}
        lengths: dict[int, int] = {}
        for assembly_id, count, total_length in rows.all():
            counts[int(assembly_id)] = int(count)
            lengths[int(assembly_id)] = int(total_length)
        return counts, lengths

    @staticmethod
    def _summary(
        assembly: Assembly, statistics: AssemblyStatistics
    ) -> AssemblySummaryResponse:
        release = assembly.release
        return AssemblySummaryResponse(
            id=str(assembly.id),
            name=assembly.name,
            species=assembly.species,
            version=assembly.version,
            description=assembly.description,
            is_default=assembly.is_default,
            created_at=assembly.created_at,
            updated_at=assembly.updated_at,
            release_id=assembly.release_id,
            release_version=release.version if release is not None else None,
            statistics=statistics,
        )


def _empty_statistics() -> AssemblyStatistics:
    """Statistics for an assembly that was never handed to the aggregates.

    Only reached when ``_statistics_for`` returned nothing for an assembly that
    *is* in this release, which means the caller skipped it rather than that the
    data is empty. Reporting ``0``s here would state a measurement that never
    happened, so each count is an explained absence instead.
    """
    return AssemblyStatistics(
        gene_count=AssemblyMetric(reason=NO_GENES),
        transcript_count=AssemblyMetric(reason=NO_TRANSCRIPTS),
        chromosome_count=AssemblyMetric(reason=NO_CHROMOSOMES),
        total_length=AssemblyMetric(reason=NO_CHROMOSOMES),
        download_count=AssemblyMetric(reason=DOWNLOAD_COUNT_UNAVAILABLE),
    )

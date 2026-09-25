"""Gene service – search, detail, transcripts (PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.genomic import Assembly, Chromosome, Gene, Transcript
from ..schemas.genomic import (
    AssemblyResponse,
    ChromosomeResponse,
    ExonResponse,
    GeneDetail,
    GeneListParams,
    GeneListResponse,
    GeneResponse,
    TranscriptResponse,
)
from .release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
)


def _cursor_filters(params: GeneListParams) -> dict[str, str]:
    return params.model_dump(
        mode="json",
        exclude={"cursor", "limit", "page", "page_size"},
        exclude_none=True,
    )


def encode_cursor(
    accession: str,
    gene_pk: int,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> str:
    """Encode a release/filter-bound gene keyset cursor.

    The sort key is ``(accession, gene_pk)``: accessions repeat across
    assemblies, so the surrogate key is the stable tiebreaker.
    """
    return encode_bound_cursor(
        kind="gene",
        sort_key={"a": accession, "p": str(gene_pk)},
        release_context=release_context,
        filters=_cursor_filters(params),
    )


def decode_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> tuple[str, int]:
    """Verify and decode a release/filter-bound gene keyset cursor."""
    try:
        payload = decode_bound_cursor(
            cursor,
            kind="gene",
            release_context=release_context,
            filters=_cursor_filters(params),
        )
        accession = payload["a"]
        gene_pk = payload["p"]
        if not isinstance(accession, str) or not accession:
            raise ValueError("gene accession must be a non-empty string")
        if not isinstance(gene_pk, str) or not gene_pk.isdigit():
            raise ValueError("gene pk must be a numeric string")
        return accession, int(gene_pk)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Invalid cursor: {exc}") from exc


class GeneService:
    """Gene query service backed by PostgreSQL."""

    async def list_genes(
        self,
        db: AsyncSession,
        params: GeneListParams,
        *,
        release_context: ReleaseContext,
    ) -> GeneListResponse:
        """Return a cursor-paginated list of genes."""
        stmt = (
            select(Gene)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(Assembly.release_id == release_context.release_id)
        )

        if params.assembly_id is not None:
            stmt = stmt.where(Gene.assembly_id == int(params.assembly_id))
        if params.chromosome is not None:
            # genes stores a chromosome_id FK; filter via the joined name.
            stmt = stmt.join(
                Chromosome, Gene.chromosome_id == Chromosome.id
            ).where(Chromosome.name == params.chromosome)
            if params.assembly_id is not None:
                # same chromosome names exist across assemblies.
                stmt = stmt.where(
                    Chromosome.assembly_id == int(params.assembly_id)
                )
        if params.biotype is not None:
            stmt = stmt.where(Gene.biotype == params.biotype)
        if params.search:
            pattern = f"%{params.search}%"
            stmt = stmt.where(
                or_(
                    Gene.accession.ilike(pattern),
                    Gene.name.ilike(pattern),
                    Gene.description.ilike(pattern),
                )
            )

        page_size = params.page_size or params.limit
        total = 0
        if params.page is not None:
            count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
            total = int(await db.scalar(count_stmt) or 0)

        # Keyset pagination on (accession, gene_pk) — accessions repeat
        # across assemblies, the surrogate key is the stable tiebreaker.
        if params.cursor:
            last_accession, last_pk = decode_cursor(
                params.cursor,
                release_context=release_context,
                params=params,
            )
            stmt = stmt.where(
                or_(
                    Gene.accession > last_accession,
                    and_(
                        Gene.accession == last_accession,
                        Gene.gene_pk > last_pk,
                    ),
                )
            )

        stmt = stmt.order_by(Gene.accession.asc(), Gene.gene_pk.asc())
        if params.page is not None:
            stmt = stmt.offset((params.page - 1) * page_size).limit(page_size)
        else:
            stmt = stmt.limit(params.limit + 1)
        result = await db.execute(stmt)
        genes = list(result.scalars().all())

        has_more = (
            len(genes) > params.limit
            if params.page is None
            else params.page * page_size < total
        )
        if has_more and params.page is None:
            genes = genes[: params.limit]

        items = [self._gene_to_response(g) for g in genes]
        next_cursor = (
            encode_cursor(
                genes[-1].accession,
                genes[-1].gene_pk,
                release_context=release_context,
                params=params,
            )
            if has_more and genes
            else None
        )

        page = params.page or 1
        return GeneListResponse(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            page=page,
            page_size=page_size,
            total=total if params.page is not None else len(items),
            total_pages=(total + page_size - 1) // page_size if total else 0,
        )

    async def get_gene(
        self,
        db: AsyncSession,
        gene_id: str,
        *,
        release_context: ReleaseContext,
        assembly_id: int | None = None,
    ) -> GeneDetail:
        """Fetch one gene without crossing the selected data release.

        ``gene_id`` is the assembly-scoped accession. When the same
        accession exists in multiple searchable assemblies and no
        ``assembly_id`` was supplied, the request fails with an explicit
        disambiguation error instead of silently choosing a version.
        """
        conditions = [
            Gene.accession == gene_id,
            Assembly.release_id == release_context.release_id,
        ]
        if assembly_id is not None:
            conditions.append(Gene.assembly_id == int(assembly_id))
        stmt = (
            select(Gene)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(and_(*conditions))
            .order_by(Gene.gene_pk)
        )
        result = await db.execute(stmt)
        genes = list(result.scalars().all())
        if not genes:
            raise NotFoundError(f"Gene {gene_id} not found")
        if len(genes) > 1:
            raise ValidationError(
                f"Gene {gene_id} exists in multiple assemblies; "
                "supply an explicit assembly_id",
                details={
                    "code": "ambiguous_assembly",
                    "assemblies": [
                        {
                            "assembly_id": g.assembly_id,
                            "accession": g.accession,
                        }
                        for g in genes
                    ],
                },
            )
        gene = genes[0]

        # Transcripts + exons are eager-loaded via relationship.
        transcripts = [
            self._transcript_to_response(t) for t in gene.transcripts
        ]
        aliases = [a.alias for a in gene.aliases]

        return GeneDetail(
            id=str(gene.accession),
            gene_id=str(gene.accession),
            assembly_id=str(gene.assembly_id),
            chromosome=gene.chromosome.name,
            name=gene.name,
            symbol=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
            start_pos=gene.start,
            end_pos=gene.end,
            strand=gene.strand,
            description=gene.description,
            transcripts=transcripts,
            aliases=aliases,
            variant_count=0,
            created_at=gene.created_at,
            updated_at=gene.updated_at,
        )

    async def find_by_accessions(
        self,
        db: AsyncSession,
        accessions: list[str] | set[str],
        *,
        release_context: ReleaseContext | None = None,
        assembly_id: int | None = None,
    ) -> dict[str, list[Gene]]:
        """Resolve accessions to assembly-scoped gene rows.

        Returns a mapping accession → matching genes (possibly in several
        assemblies). Callers must disambiguate when a list holds more than
        one entry; they must not silently pick a version.
        """
        if not accessions:
            return {}
        stmt = select(Gene).where(Gene.accession.in_(list(accessions)))
        if release_context is not None:
            stmt = stmt.join(
                Assembly, Gene.assembly_id == Assembly.id
            ).where(Assembly.release_id == release_context.release_id)
        if assembly_id is not None:
            stmt = stmt.where(Gene.assembly_id == int(assembly_id))
        result = await db.execute(stmt)
        mapping: dict[str, list[Gene]] = {}
        for gene in result.scalars().all():
            mapping.setdefault(gene.accession, []).append(gene)
        return mapping

    async def list_assemblies(
        self, db: AsyncSession, *, release_id: int
    ) -> list[AssemblyResponse]:
        result = await db.execute(
            select(Assembly)
            .where(Assembly.release_id == release_id)
            .order_by(Assembly.name)
        )
        return [
            AssemblyResponse(
                id=str(a.id),
                name=a.name,
                species=a.species,
                version=a.version,
                description=a.description,
                is_default=a.is_default,
                created_at=a.created_at,
                updated_at=a.updated_at,
            )
            for a in result.scalars().all()
        ]

    async def list_chromosomes(
        self, db: AsyncSession, assembly_id: int, *, release_id: int
    ) -> list[ChromosomeResponse]:
        result = await db.execute(
            select(Chromosome)
            .join(Assembly, Chromosome.assembly_id == Assembly.id)
            .where(Chromosome.assembly_id == assembly_id)
            .where(Assembly.release_id == release_id)
            .order_by(Chromosome.order)
        )
        return [
            ChromosomeResponse(
                id=str(c.id),
                assembly_id=str(c.assembly_id),
                name=c.name,
                length=c.length,
                order=c.order,
            )
            for c in result.scalars().all()
        ]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _gene_to_response(gene: Gene) -> GeneResponse:
        return GeneResponse(
            id=str(gene.accession),
            gene_id=str(gene.accession),
            assembly_id=str(gene.assembly_id),
            assembly_name=gene.assembly.name if gene.assembly else None,
            chromosome=gene.chromosome.name,
            name=gene.name,
            symbol=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
            start_pos=gene.start,
            end_pos=gene.end,
            strand=gene.strand,
            description=gene.description,
        )

    @staticmethod
    def _transcript_to_response(tx: Transcript) -> TranscriptResponse:
        return TranscriptResponse(
            id=str(tx.id),
            gene_id=str(tx.gene.accession),
            name=tx.name,
            biotype=tx.biotype,
            start=tx.start,
            end=tx.end,
            strand=tx.strand,
            is_canonical=tx.is_canonical,
            exons=[
                ExonResponse(
                    id=str(e.id),
                    start=e.start,
                    end=e.end,
                    order=e.order,
                )
                for e in tx.exons
            ],
        )

"""Gene service – search, detail, transcripts (PostgreSQL)."""

from __future__ import annotations

from sqlalchemy import func, or_, select
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
    gene_id: str,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> str:
    """Encode a release/filter-bound gene-id keyset cursor."""
    return encode_bound_cursor(
        kind="gene",
        sort_key={"g": gene_id},
        release_context=release_context,
        filters=_cursor_filters(params),
    )


def decode_cursor(
    cursor: str,
    *,
    release_context: ReleaseContext,
    params: GeneListParams,
) -> str:
    """Verify and decode a release/filter-bound gene-id keyset cursor."""
    try:
        payload = decode_bound_cursor(
            cursor,
            kind="gene",
            release_context=release_context,
            filters=_cursor_filters(params),
        )
        gene_id = payload["g"]
        if not isinstance(gene_id, str) or not gene_id:
            raise ValueError("gene id must be a non-empty string")
        return gene_id
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
                    Gene.id.ilike(pattern),
                    Gene.name.ilike(pattern),
                    Gene.description.ilike(pattern),
                )
            )

        page_size = params.page_size or params.limit
        total = 0
        if params.page is not None:
            count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
            total = int(await db.scalar(count_stmt) or 0)

        # Keyset pagination on gene id (string, ascending).
        if params.cursor:
            last_id = decode_cursor(
                params.cursor,
                release_context=release_context,
                params=params,
            )
            stmt = stmt.where(Gene.id > last_id)

        stmt = stmt.order_by(Gene.id.asc())
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
                genes[-1].id,
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
    ) -> GeneDetail:
        """Fetch one gene without crossing the selected data release."""
        stmt = (
            select(Gene)
            .join(Assembly, Gene.assembly_id == Assembly.id)
            .where(
                Gene.id == gene_id,
                Assembly.release_id == release_context.release_id,
            )
        )
        result = await db.execute(stmt)
        gene = result.scalar_one_or_none()
        if gene is None:
            raise NotFoundError(f"Gene {gene_id} not found")

        # Transcripts + exons are eager-loaded via relationship.
        transcripts = [
            self._transcript_to_response(t) for t in gene.transcripts
        ]
        aliases = [a.alias for a in gene.aliases]

        return GeneDetail(
            id=str(gene.id),
            gene_id=str(gene.id),
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

    async def list_assemblies(self, db: AsyncSession) -> list[AssemblyResponse]:
        result = await db.execute(select(Assembly).order_by(Assembly.name))
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
        self, db: AsyncSession, assembly_id: int
    ) -> list[ChromosomeResponse]:
        result = await db.execute(
            select(Chromosome)
            .where(Chromosome.assembly_id == assembly_id)
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
            id=str(gene.id),
            gene_id=str(gene.id),
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
        )

    @staticmethod
    def _transcript_to_response(tx: Transcript) -> TranscriptResponse:
        return TranscriptResponse(
            id=str(tx.id),
            gene_id=str(tx.gene_id),
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

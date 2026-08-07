"""Gene service – search, detail, transcripts (PostgreSQL)."""

from __future__ import annotations

import base64
import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NotFoundError, ValidationError
from ..models.genomic import Assembly, Chromosome, Exon, Gene, GeneAlias, Transcript
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


def encode_cursor(gene_id: str) -> str:
    """Encode a gene-id sort key into a base64 cursor."""
    payload = json.dumps({"g": gene_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    """Decode a base64 cursor back into the gene-id sort key."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return str(payload["g"])
    except Exception as exc:
        raise ValidationError(f"Invalid cursor: {exc}") from exc


class GeneService:
    """Gene query service backed by PostgreSQL."""

    async def list_genes(
        self, db: AsyncSession, params: GeneListParams
    ) -> GeneListResponse:
        """Return a cursor-paginated list of genes."""
        stmt = select(Gene)

        if params.assembly_id is not None:
            stmt = stmt.where(Gene.assembly_id == int(params.assembly_id))
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

        # Keyset pagination on gene id (string, ascending).
        if params.cursor:
            last_id = decode_cursor(params.cursor)
            stmt = stmt.where(Gene.id > last_id)

        stmt = stmt.order_by(Gene.id.asc()).limit(params.limit + 1)
        result = await db.execute(stmt)
        genes = list(result.scalars().all())

        has_more = len(genes) > params.limit
        if has_more:
            genes = genes[: params.limit]

        items = [self._gene_to_response(g) for g in genes]
        next_cursor = encode_cursor(genes[-1].id) if has_more and genes else None

        return GeneListResponse(
            items=items, next_cursor=next_cursor, has_more=has_more
        )

    async def get_gene(self, db: AsyncSession, gene_id: str) -> GeneDetail:
        """Fetch a single gene with transcripts and aliases."""
        stmt = select(Gene).where(Gene.id == gene_id)
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
            assembly_id=str(gene.assembly_id),
            chromosome=str(gene.chromosome_id),
            name=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
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
            assembly_id=str(gene.assembly_id),
            chromosome=str(gene.chromosome_id),
            name=gene.name,
            biotype=gene.biotype,
            start=gene.start,
            end=gene.end,
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

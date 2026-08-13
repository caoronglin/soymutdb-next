"""Global search service across genes, variants, mutant lines, publications.

Fix vs. reference: uses proper ``ilike()`` calls (the reference used an
invalid ``func.cast(type_=None)`` expression).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.content import Publication
from ..models.genomic import Gene
from ..models.variant import MutantLine
from ..schemas.search import (
    GlobalSearchResponse,
    SearchHit,
    SearchResultItem,
    SearchResultType,
    SearchSuggestion,
)


class SearchService:
    """Cross-entity search service."""

    async def global_search(
        self,
        db: AsyncSession,
        query: str,
        types: list[SearchResultType] | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> GlobalSearchResponse:
        """Search across multiple entity types."""
        pattern = f"%{query}%"
        hits: list[SearchHit] = []
        active_types = types or list(SearchResultType)
        per_type = max(1, limit // max(1, len(active_types)))

        if SearchResultType.GENE in active_types:
            hits.extend(await self._search_genes(db, pattern, per_type))

        if SearchResultType.MUTANT_LINE in active_types:
            hits.extend(await self._search_mutant_lines(db, pattern, per_type))

        if SearchResultType.PUBLICATION in active_types:
            hits.extend(await self._search_publications(db, pattern, per_type))

        # Sort by score descending and truncate.
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:limit]

        return GlobalSearchResponse(
            query=query,
            results=[
                SearchResultItem(
                    type=h.type,
                    id=h.id,
                    name=h.title,
                    description=h.subtitle,
                    score=h.score,
                    url=self._frontend_url(h.type, h.id),
                    source=h.metadata.get("source", "internal"),
                )
                for h in hits
            ],
            by_type={
                result_type.value: sum(1 for hit in hits if hit.type == result_type)
                for result_type in active_types
            },
            cursor=cursor,
            next_cursor=None,
            has_more=False,
            total_count=len(hits),
        )

    @staticmethod
    def _frontend_url(result_type: SearchResultType, result_id: str) -> str:
        routes = {
            SearchResultType.GENE: "genes",
            SearchResultType.VARIANT: "variants",
            SearchResultType.MUTANT_LINE: "mutants",
            SearchResultType.PUBLICATION: "publications",
        }
        return f"/search/{routes.get(result_type, result_type.value)}/{result_id}"

    async def _search_genes(
        self, db: AsyncSession, pattern: str, limit: int
    ) -> list[SearchHit]:
        """Search genes by id, name, description using proper ilike."""
        stmt = (
            select(Gene)
            .where(
                or_(
                    Gene.id.ilike(pattern),
                    Gene.name.ilike(pattern),
                    Gene.description.ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for gene in result.scalars().all():
            hits.append(
                SearchHit(
                    id=str(gene.id),
                    type=SearchResultType.GENE,
                    title=gene.name or str(gene.id),
                    subtitle=gene.description,
                    highlight=None,
                    score=1.0,
                    url=f"/api/v1/genes/{gene.id}",
                    metadata={"biotype": gene.biotype},
                )
            )
        return hits

    async def _search_mutant_lines(
        self, db: AsyncSession, pattern: str, limit: int
    ) -> list[SearchHit]:
        stmt = (
            select(MutantLine)
            .where(
                or_(
                    MutantLine.name.ilike(pattern),
                    MutantLine.cultivar.ilike(pattern),
                    MutantLine.mutagen.ilike(pattern),
                    MutantLine.description.ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for ml in result.scalars().all():
            hits.append(
                SearchHit(
                    id=str(ml.id),
                    type=SearchResultType.MUTANT_LINE,
                    title=ml.name,
                    subtitle=ml.description,
                    score=1.0,
                    url=f"/api/v1/mutants/{ml.id}",
                    metadata={"mutagen": ml.mutagen, "cultivar": ml.cultivar},
                )
            )
        return hits

    async def _search_publications(
        self, db: AsyncSession, pattern: str, limit: int
    ) -> list[SearchHit]:
        stmt = (
            select(Publication)
            .where(
                or_(
                    Publication.title.ilike(pattern),
                    Publication.authors.ilike(pattern),
                    Publication.abstract.ilike(pattern),
                )
            )
            .limit(limit)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for pub in result.scalars().all():
            hits.append(
                SearchHit(
                    id=str(pub.id),
                    type=SearchResultType.PUBLICATION,
                    title=pub.title,
                    subtitle=pub.journal,
                    score=1.0,
                    url=f"/api/v1/content/publications/{pub.id}",
                    metadata={"year": pub.year, "doi": pub.doi},
                )
            )
        return hits

    async def suggest(
        self, db: AsyncSession, query: str, limit: int = 5
    ) -> list[SearchSuggestion]:
        """Return autocomplete suggestions."""
        pattern = f"{query}%"
        stmt = (
            select(Gene.id, Gene.name)
            .where(or_(Gene.id.ilike(pattern), Gene.name.ilike(pattern)))
            .limit(limit)
        )
        result = await db.execute(stmt)
        suggestions: list[SearchSuggestion] = []
        for gene_id, gene_name in result.all():
            suggestions.append(
                SearchSuggestion(
                    text=gene_name or str(gene_id),
                    type=SearchResultType.GENE,
                    score=1.0,
                    description=f"Gene: {gene_name or gene_id}",
                )
            )
        return suggestions

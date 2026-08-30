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
from .cache import get_or_set


def _contains_pattern(query: str) -> str:
    """Build a literal substring pattern, not a caller-controlled LIKE program."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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
        """Search across multiple entity types with a short-lived cache."""
        limit = max(1, min(int(limit), 100))
        active_types = types or list(SearchResultType)
        # The federated search cursor is a numeric page offset. It is
        # intentionally parsed at the service boundary so a malformed external
        # value cannot reach SQLAlchemy's OFFSET clause.
        try:
            page_offset = max(0, int(cursor or "0"))
        except ValueError:
            page_offset = 0
        cache_params = {
            "query": query,
            "types": [result_type.value for result_type in active_types],
            "cursor": cursor,
            "limit": limit,
        }

        async def load() -> dict[str, Any]:
            pattern = _contains_pattern(query)
            hits: list[SearchHit] = []
            per_type = max(1, limit // max(1, len(active_types)))

            # AsyncSession is intentionally used sequentially here. Running
            # multiple statements concurrently on one session is unsupported.
            has_more = False
            if SearchResultType.GENE in active_types:
                gene_hits = await self._search_genes(db, pattern, per_type + 1, page_offset)
                has_more = has_more or len(gene_hits) > per_type
                hits.extend(gene_hits[:per_type])
            if SearchResultType.MUTANT_LINE in active_types:
                mutant_hits = await self._search_mutant_lines(
                    db, pattern, per_type + 1, page_offset
                )
                has_more = has_more or len(mutant_hits) > per_type
                hits.extend(mutant_hits[:per_type])
            if SearchResultType.PUBLICATION in active_types:
                publication_hits = await self._search_publications(
                    db, pattern, per_type + 1, page_offset
                )
                has_more = has_more or len(publication_hits) > per_type
                hits.extend(publication_hits[:per_type])

            hits.sort(key=lambda hit: hit.score, reverse=True)
            hits = hits[:limit]
            response = GlobalSearchResponse(
                query=query,
                results=[
                    SearchResultItem(
                        type=hit.type,
                        id=hit.id,
                        name=hit.title,
                        description=hit.subtitle,
                        score=hit.score,
                        url=self._frontend_url(hit.type, hit.id),
                        source=hit.metadata.get("source", "internal"),
                    )
                    for hit in hits
                ],
                by_type={
                    result_type.value: sum(
                        1 for hit in hits if hit.type == result_type
                    )
                    for result_type in active_types
                },
                cursor=cursor,
                next_cursor=str(page_offset + per_type) if has_more else None,
                has_more=has_more,
                total_count=len(hits),
            )
            return response.model_dump(mode="json")

        payload = await get_or_set(
            "search:global",
            ttl=60,
            loader=load,
            params=cache_params,
        )
        return GlobalSearchResponse.model_validate(payload)

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
        self, db: AsyncSession, pattern: str, limit: int, offset: int = 0
    ) -> list[SearchHit]:
        """Search genes by id, name, description using proper ilike."""
        stmt = (
            select(Gene.id, Gene.name, Gene.description, Gene.biotype)
            .where(
                or_(
                    Gene.id.ilike(pattern, escape="\\"),
                    Gene.name.ilike(pattern, escape="\\"),
                    Gene.description.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Gene.id)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for gene in result.all():
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
        self, db: AsyncSession, pattern: str, limit: int, offset: int = 0
    ) -> list[SearchHit]:
        stmt = (
            select(
                MutantLine.id,
                MutantLine.name,
                MutantLine.description,
                MutantLine.mutagen,
                MutantLine.cultivar,
            )
            .where(
                or_(
                    MutantLine.name.ilike(pattern, escape="\\"),
                    MutantLine.cultivar.ilike(pattern, escape="\\"),
                    MutantLine.mutagen.ilike(pattern, escape="\\"),
                    MutantLine.description.ilike(pattern, escape="\\"),
                )
            )
            .order_by(MutantLine.name, MutantLine.id)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for ml in result.all():
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
        self, db: AsyncSession, pattern: str, limit: int, offset: int = 0
    ) -> list[SearchHit]:
        stmt = (
            select(
                Publication.id,
                Publication.title,
                Publication.journal,
                Publication.year,
                Publication.doi,
            )
            .where(
                or_(
                    Publication.title.ilike(pattern, escape="\\"),
                    Publication.authors.ilike(pattern, escape="\\"),
                    Publication.abstract.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Publication.id)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        hits: list[SearchHit] = []
        for pub in result.all():
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
        """Return autocomplete suggestions, cached for a short interval."""
        limit = max(1, min(int(limit), 20))

        async def load() -> list[dict[str, Any]]:
            pattern = f"{query}%"
            stmt = (
                select(Gene.id, Gene.name)
                .where(or_(Gene.id.ilike(pattern), Gene.name.ilike(pattern)))
                .limit(limit)
            )
            result = await db.execute(stmt)
            suggestions = [
                SearchSuggestion(
                    text=gene_name or str(gene_id),
                    type=SearchResultType.GENE,
                    score=1.0,
                    description=f"Gene: {gene_name or gene_id}",
                ).model_dump(mode="json")
                for gene_id, gene_name in result.all()
            ]
            return suggestions

        payload = await get_or_set(
            "search:suggest",
            ttl=30,
            loader=load,
            params={"query": query, "limit": limit},
        )
        return [SearchSuggestion.model_validate(item) for item in payload]

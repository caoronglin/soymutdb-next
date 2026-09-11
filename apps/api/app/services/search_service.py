"""Global search service across genes, variants, mutant lines, publications.

Contract highlights (database-core-contract):
- external context: mutant hits come only from published, non-deleted rows
  that carry a ``public_id``; the private persistence key never appears.
- internal context: results carry both identities and the matched field;
  the shared cache is bypassed so authorized data cannot leak via cache.
- assembly is an explicit dimension: unscoped queries span every assembly
  of the active release and label each hit; assembly-scoped queries never
  fall back to a default assembly.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.public_ids import normalize_public_id
from ..core.site_variant import SiteVariant
from ..models.content import Publication
from ..models.genomic import Assembly, Gene, GeneAlias
from ..models.variant import MutantLine
from ..schemas.search import (
    GlobalSearchResponse,
    InternalGeneSearchItem,
    InternalMutantSearchItem,
    InternalSearchResponse,
    MatchType,
    SearchHit,
    SearchResultItem,
    SearchResultType,
    SearchSuggestion,
)
from .cache import get_or_set
from .release_context import resolve_release_context


def _literal_like_fragment(query: str) -> str:
    """Escape user text for SQL LIKE patterns using a backslash escape."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains_pattern(query: str) -> str:
    """Build a literal substring pattern, not a caller-controlled LIKE program."""
    return f"%{_literal_like_fragment(query)}%"


def _is_exact_accession(query: str) -> bool:
    """Treat short, identifier-shaped input as an exact-match candidate."""
    stripped = query.strip()
    return 0 < len(stripped) <= 64 and " " not in stripped


class SearchService:
    """Cross-entity search service."""

    async def global_search(
        self,
        db: AsyncSession,
        query: str,
        types: list[SearchResultType] | None = None,
        cursor: str | None = None,
        limit: int = 20,
        assembly_id: int | None = None,
        site_variant: SiteVariant = SiteVariant.EXTERNAL,
    ) -> GlobalSearchResponse:
        """Search across multiple entity types with a short-lived cache.

        External responses are cached per (site, release, assembly, query,
        types, cursor, limit). Internal responses bypass the cache so
        authorized rows can never be served to a different scope.
        """
        limit = max(1, min(int(limit), 100))
        active_types = types or list(SearchResultType)
        context = await resolve_release_context(db)
        release_id = context.release_id
        # NOTE: an absent assembly_id deliberately searches every assembly
        # of the release; hits are labelled per assembly and the response
        # reports ambiguity. It is never defaulted behind the caller's back.
        try:
            page_offset = max(0, int(cursor or "0"))
        except ValueError:
            page_offset = 0
        cache_params = {
            "query": query,
            "types": [result_type.value for result_type in active_types],
            "cursor": cursor,
            "limit": limit,
            "site_variant": site_variant.value,
            "release_id": release_id,
            "assembly_id": assembly_id,
        }

        async def load() -> dict[str, Any]:
            pattern = _contains_pattern(query)
            hits: list[SearchHit] = []
            per_type = max(1, limit // max(1, len(active_types)))

            # AsyncSession is intentionally used sequentially here. Running
            # multiple statements concurrently on one session is unsupported.
            has_more = False
            if SearchResultType.GENE in active_types:
                gene_hits = await self._search_genes(
                    db, query, pattern, per_type + 1, page_offset,
                    release_id=release_id, assembly_id=assembly_id,
                )
                has_more = has_more or len(gene_hits) > per_type
                hits.extend(gene_hits[:per_type])
            if SearchResultType.MUTANT_LINE in active_types:
                mutant_hits = await self._search_mutant_lines(
                    db, query, pattern, per_type + 1, page_offset,
                    release_id=release_id,
                    site_variant=site_variant,
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
            by_assembly: dict[str, int] = {}
            for hit in hits:
                assembly = hit.metadata.get("assembly_id")
                if assembly is not None:
                    key = str(assembly)
                    by_assembly[key] = by_assembly.get(key, 0) + 1
            response = GlobalSearchResponse(
                query=query,
                results=[
                    SearchResultItem(
                        type=hit.type,
                        id=hit.id,
                        name=hit.title,
                        description=hit.subtitle,
                        score=hit.score,
                        match_type=hit.match_type,
                        url=self._frontend_url(
                            hit.type,
                            hit.id,
                            assembly_id=hit.metadata.get("assembly_id"),
                        ),
                        source=hit.metadata.get("source", "internal"),
                        release_id=hit.metadata.get("release_id"),
                        assembly_id=hit.metadata.get("assembly_id"),
                    )
                    for hit in hits
                ],
                by_type={
                    result_type.value: sum(
                        1 for hit in hits if hit.type == result_type
                    )
                    for result_type in active_types
                },
                by_assembly=by_assembly,
                ambiguous=len(by_assembly) > 1,
                cursor=cursor,
                next_cursor=str(page_offset + per_type) if has_more else None,
                has_more=has_more,
                total_count=len(hits),
            )
            return response.model_dump(mode="json")

        if site_variant == SiteVariant.INTERNAL:
            # Internal results must never enter the shared cache: two users
            # with different authorization scopes could otherwise observe
            # each other's data under the same query key.
            return GlobalSearchResponse.model_validate(await load())
        payload = await get_or_set(
            "search:global",
            ttl=60,
            loader=load,
            params=cache_params,
        )
        return GlobalSearchResponse.model_validate(payload)

    async def internal_search(
        self,
        db: AsyncSession,
        query: str,
        *,
        release_id: int | None = None,
        limit: int = 20,
    ) -> InternalSearchResponse:
        """Authorized internal search across both identity namespaces.

        Callers must enforce server-side internal authorization before
        invoking this; results intentionally include internal identities.
        When ``release_id`` is supplied, gene hits are scoped to that
        release; mutant hits always span releases so internal users can
        locate records that are not yet published.
        """
        limit = max(1, min(int(limit), 100))
        pattern = _contains_pattern(query)
        mutants = await self._internal_search_mutants(
            db, query, pattern, release_id=release_id, limit=limit
        )
        genes = await self._internal_search_genes(
            db, query, pattern, release_id=release_id, limit=limit
        )
        return InternalSearchResponse(
            query=query,
            mutants=mutants,
            genes=genes,
            total_count=len(mutants) + len(genes),
        )

    @staticmethod
    def _frontend_url(
        result_type: SearchResultType,
        result_id: str,
        *,
        assembly_id: int | None = None,
    ) -> str:
        encoded_id = quote(result_id, safe="")
        if result_type == SearchResultType.GENE:
            url = f"/genes/{encoded_id}"
            if assembly_id is not None:
                url += "?" + urlencode({"assembly": assembly_id})
            return url
        if result_type == SearchResultType.MUTANT_LINE:
            return f"/mutants/{encoded_id}"
        if result_type == SearchResultType.VARIANT:
            return "/variants"
        if result_type == SearchResultType.PUBLICATION:
            return "/publications"
        return "/search"

    async def _search_genes(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        limit: int,
        offset: int = 0,
        *,
        release_id: int,
        assembly_id: int | None,
    ) -> list[SearchHit]:
        """Search genes with exact > alias > text match typing."""
        text_match = or_(
            Gene.accession.ilike(pattern, escape="\\"),
            Gene.name.ilike(pattern, escape="\\"),
            Gene.description.ilike(pattern, escape="\\"),
        )
        conditions = [text_match]
        if _is_exact_accession(query):
            # Curated alias equality widens the candidate set; matching
            # never falls back to string similarity.
            needle = query.strip()
            alias_match = (
                select(GeneAlias.gene_id)
                .where(
                    GeneAlias.gene_id == Gene.gene_pk,
                    func.lower(GeneAlias.alias) == func.lower(needle),
                )
                .exists()
            )
            conditions = [or_(text_match, alias_match)]
        conditions.append(Assembly.release_id == release_id)
        if assembly_id is not None:
            conditions.append(Gene.assembly_id == assembly_id)
        stmt = (
            select(
                Gene.gene_pk,
                Gene.accession,
                Gene.name,
                Gene.description,
                Gene.biotype,
                Gene.assembly_id,
            )
            .join(Assembly, Assembly.id == Gene.assembly_id)
            .where(and_(*conditions))
            .order_by(Gene.accession, Gene.gene_pk)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # Alias equality (curated data only, never string similarity).
        alias_map: dict[int, str] = {}
        exact_map: set[int] = set()
        if rows and _is_exact_accession(query):
            pks = [row.gene_pk for row in rows]
            needle = query.strip()
            alias_rows = await db.execute(
                select(GeneAlias.gene_id, GeneAlias.alias).where(
                    and_(
                        GeneAlias.gene_id.in_(pks),
                        func.lower(GeneAlias.alias) == func.lower(needle),
                    )
                )
            )
            for gene_pk, alias in alias_rows.all():
                alias_map[gene_pk] = alias
            exact_map = {
                row.gene_pk
                for row in rows
                if row.accession.lower() == needle.lower()
            }

        hits: list[SearchHit] = []
        for row in rows:
            if row.gene_pk in exact_map:
                match_type = MatchType.EXACT
                score = 3.0
            elif row.gene_pk in alias_map:
                match_type = MatchType.ALIAS
                score = 2.0
            else:
                match_type = MatchType.TEXT
                score = 1.0
            hits.append(
                SearchHit(
                    id=row.accession,
                    type=SearchResultType.GENE,
                    title=row.name or row.accession,
                    subtitle=row.description,
                    highlight=None,
                    score=score,
                    url=f"/api/v1/genes/{row.accession}",
                    match_type=match_type,
                    metadata={
                        "biotype": row.biotype,
                        "release_id": release_id,
                        "assembly_id": row.assembly_id,
                    },
                )
            )
        return hits

    async def _search_mutant_lines(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        limit: int,
        offset: int = 0,
        *,
        release_id: int,
        site_variant: SiteVariant,
    ) -> list[SearchHit]:
        """Search mutant lines.

        External context: only public, non-deleted rows carrying a
        ``public_id`` are eligible, and matching uses the public identity
        only. The internal lab designation and the persistence key are not
        matchable on the external site.
        """
        if site_variant == SiteVariant.EXTERNAL:
            conditions = [
                MutantLine.is_public.is_(True),
                MutantLine.is_deleted.is_(False),
                MutantLine.public_id.is_not(None),
                MutantLine.public_id.ilike(pattern, escape="\\"),
            ]
            stmt = (
                select(
                    MutantLine.public_id,
                    MutantLine.name,
                    MutantLine.description,
                    MutantLine.mutagen,
                    MutantLine.cultivar,
                )
                .where(and_(*conditions))
                .order_by(MutantLine.public_id, MutantLine.id)
                .limit(limit)
                .offset(offset)
            )
            result = await db.execute(stmt)
            hits: list[SearchHit] = []
            for ml in result.all():
                public_id = ml.public_id or ""
                exact = _is_exact_accession(query) and public_id.upper() == normalize_public_id(query.strip())
                hits.append(
                    SearchHit(
                        id=public_id,
                        type=SearchResultType.MUTANT_LINE,
                        title=public_id,
                        subtitle=ml.description,
                        score=3.0 if exact else 1.0,
                        url=f"/api/v1/mutants/{public_id}",
                        match_type=MatchType.EXACT if exact else MatchType.TEXT,
                        metadata={
                            "mutagen": ml.mutagen,
                            "cultivar": ml.cultivar,
                            "release_id": release_id,
                            "display_name": ml.name,
                        },
                    )
                )
            return hits

        # Internal federated search: kept for internal callers of
        # global_search; matching spans both identities.
        stmt = (
            select(
                MutantLine.public_id,
                MutantLine.name,
                MutantLine.description,
                MutantLine.mutagen,
                MutantLine.cultivar,
            )
            .where(
                and_(
                    MutantLine.is_deleted.is_(False),
                    MutantLine.release_id == release_id,
                    or_(
                        MutantLine.name.ilike(pattern, escape="\\"),
                        MutantLine.cultivar.ilike(pattern, escape="\\"),
                        MutantLine.mutagen.ilike(pattern, escape="\\"),
                        MutantLine.description.ilike(pattern, escape="\\"),
                    ),
                )
            )
            .order_by(MutantLine.name, MutantLine.id)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        hits = []
        for ml in result.all():
            hits.append(
                SearchHit(
                    id=ml.public_id or ml.name,
                    type=SearchResultType.MUTANT_LINE,
                    title=ml.name,
                    subtitle=ml.description,
                    score=1.0,
                    url=f"/mutants/{ml.public_id or ml.name}",
                    match_type=MatchType.TEXT,
                    metadata={
                        "mutagen": ml.mutagen,
                        "cultivar": ml.cultivar,
                        "release_id": release_id,
                    },
                )
            )
        return hits

    async def _internal_search_mutants(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        *,
        release_id: int,
        limit: int,
    ) -> list[InternalMutantSearchItem]:
        """Internal mutant search across public_id and lab designation."""
        conditions = [
            MutantLine.is_deleted.is_(False),
        ]
        if _is_exact_accession(query):
            needle = normalize_public_id(query.strip())
            conditions.append(
                or_(
                    MutantLine.name.ilike(pattern, escape="\\"),
                    func.upper(MutantLine.public_id) == needle,
                )
            )
        else:
            conditions.append(MutantLine.name.ilike(pattern, escape="\\"))
        stmt = (
            select(MutantLine)
            .where(and_(*conditions))
            .order_by(MutantLine.name, MutantLine.id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: list[InternalMutantSearchItem] = []
        needle = normalize_public_id(query.strip()) if _is_exact_accession(query) else None
        for ml in result.scalars().all():
            matched_field = "name"
            match_type = MatchType.TEXT
            if (
                ml.public_id
                and needle
                and ml.public_id.upper() == needle
            ):
                matched_field = "public_id"
                match_type = MatchType.EXACT
            elif ml.name.lower() == query.strip().lower():
                matched_field = "name"
                match_type = MatchType.EXACT
            items.append(
                InternalMutantSearchItem(
                    public_id=ml.public_id or "",
                    internal_id=str(ml.id),
                    name=ml.name,
                    matched_field=matched_field,
                    match_type=match_type,
                    is_public=ml.is_public,
                    release_id=ml.release_id,
                    url=f"/mutants/{ml.public_id}" if ml.public_id else None,
                )
            )
        return items

    async def _internal_search_genes(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        *,
        release_id: int,
        limit: int,
    ) -> list[InternalGeneSearchItem]:
        """Internal gene search across accession, name and curated aliases."""
        conditions = [
            or_(
                Gene.accession.ilike(pattern, escape="\\"),
                Gene.name.ilike(pattern, escape="\\"),
            )
        ]
        stmt = select(Gene).join(Assembly, Assembly.id == Gene.assembly_id)
        gene_conditions = list(conditions)
        if release_id is not None:
            gene_conditions.append(Assembly.release_id == release_id)
        stmt = stmt.where(and_(*gene_conditions))
        stmt = stmt.order_by(Gene.accession, Gene.gene_pk).limit(limit)
        result = await db.execute(stmt)
        genes = list(result.scalars().all())
        alias_map: dict[int, str] = {}
        if genes and _is_exact_accession(query):
            needle = query.strip()
            alias_rows = await db.execute(
                select(GeneAlias.gene_id, GeneAlias.alias).where(
                    and_(
                        GeneAlias.gene_id.in_([g.gene_pk for g in genes]),
                        func.lower(GeneAlias.alias) == func.lower(needle),
                    )
                )
            )
            alias_map = dict(alias_rows.all())
        items: list[InternalGeneSearchItem] = []
        for gene in genes:
            if gene.accession.lower() == query.strip().lower():
                matched_field, match_type = "accession", MatchType.EXACT
            elif gene.gene_pk in alias_map:
                matched_field, match_type = "alias", MatchType.ALIAS
            elif gene.name and gene.name.lower() == query.strip().lower():
                matched_field, match_type = "name", MatchType.EXACT
            else:
                matched_field, match_type = "accession", MatchType.TEXT
            items.append(
                InternalGeneSearchItem(
                    gene_id=gene.accession,
                    internal_id=str(gene.gene_pk),
                    name=gene.name,
                    matched_field=matched_field,
                    match_type=match_type,
                    assembly_id=gene.assembly_id,
                    release_id=release_id,
                    url=f"/genes/{quote(gene.accession, safe='')}",
                )
            )
        return items

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
        self, db: AsyncSession, query: str, limit: int = 5,
        *, release_id: int | None = None,
    ) -> list[SearchSuggestion]:
        """Return autocomplete suggestions, cached for a short interval.

        Gene suggestions are scoped to the data release so a suggestion can
        never point into a different release context than the search itself.
        """
        limit = max(1, min(int(limit), 20))

        async def load() -> list[dict[str, Any]]:
            pattern = f"{_literal_like_fragment(query)}%"
            stmt = (
                select(Gene.accession, Gene.name, Gene.assembly_id)
                .join(Assembly, Assembly.id == Gene.assembly_id)
            )
            if release_id is not None:
                stmt = stmt.where(Assembly.release_id == release_id)
            stmt = stmt.where(
                or_(Gene.accession.ilike(pattern, escape="\\"), Gene.name.ilike(pattern, escape="\\"))
            ).limit(limit)
            result = await db.execute(stmt)
            suggestions = [
                SearchSuggestion(
                    text=accession,
                    type=SearchResultType.GENE,
                    score=1.0,
                    description=f"Gene: {gene_name or accession}",
                    metadata={"assembly_id": assembly_id},
                ).model_dump(mode="json")
                for accession, gene_name, assembly_id in result.all()
            ]
            return suggestions

        payload = await get_or_set(
            "search:suggest",
            ttl=30,
            loader=load,
            params={"query": query, "limit": limit, "release_id": release_id},
        )
        return [SearchSuggestion.model_validate(item) for item in payload]

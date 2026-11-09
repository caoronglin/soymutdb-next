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

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import and_, case, desc, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.exceptions import ValidationError
from ..core.public_ids import normalize_public_id
from ..core.site_variant import SiteVariant
from ..models.content import Publication, Release, ReleaseStatus
from ..models.genomic import Assembly, Gene, GeneAlias, GeneCrosswalk
from ..models.variant import MutantLine
from ..schemas.search import (
    CrossVersionLink,
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
from .release_context import (
    ReleaseContext,
    decode_bound_cursor,
    encode_bound_cursor,
    resolve_release_context,
)

_GLOBAL_CURSOR_VERSION = 1
_MAX_GLOBAL_CURSOR_LENGTH = 8192
_CURSOR_SOURCES = (
    SearchResultType.GENE,
    SearchResultType.MUTANT_LINE,
    SearchResultType.PUBLICATION,
)


def _normalize_search_query(query: str) -> str:
    """Return the canonical query representation used for cursor binding."""
    return unicodedata.normalize("NFKC", query).strip().casefold()


def _query_fingerprint(query: str) -> str:
    return hashlib.sha256(_normalize_search_query(query).encode("utf-8")).hexdigest()


def _cursor_filters(
    *,
    query: str,
    active_types: list[SearchResultType],
    site_variant: SiteVariant,
    assembly_id: int | None,
) -> dict[str, Any]:
    """Return non-secret context bound by the existing cursor primitive."""
    return {
        "query": _query_fingerprint(query),
        "types": _cursor_type_values(active_types),
        "site_variant": site_variant.value,
        "assembly_id": assembly_id,
    }


def _cursor_type_values(types: Iterable[str | SearchResultType]) -> list[str]:
    """Canonical, de-duplicated type values for cursor binding.

    The bound context is digested with ``json.dumps(sort_keys=True)``, which
    orders dict keys and leaves list elements alone. A list of type names is
    therefore order-significant to the digest, so two requests that select the
    same result types in a different order produced different digests and the
    second request was rejected with "Cursor context does not match this release
    or filter set" even though nothing about the filter set had changed.

    ``_normalize_active_types`` already exists to make cursor bindings
    deterministic and orders by enum declaration; this applies it to both the
    encoder and the decoder so the ordering can no longer be the caller's.
    """
    return [item.value for item in _normalize_active_types(list(types))]


def _encode_global_cursor(payload: Mapping[str, Any]) -> str:
    """Sign a v1 cursor with the repository's release-bound primitive.

    The repository primitive authenticates both release context and filters.
    """
    context = ReleaseContext(
        release_id=int(payload["release_id"]),
        assembly_id=payload.get("assembly_id"),
    )
    filters = {
        "query": payload["q"],
        "types": _cursor_type_values(payload["types"]),
        "site_variant": payload["site_variant"],
        "assembly_id": payload.get("assembly_id"),
    }
    signed = encode_bound_cursor(
        kind="global-search",
        sort_key={"v": _GLOBAL_CURSOR_VERSION, "positions": payload["positions"]},
        release_context=context,
        filters=filters,
    )
    return signed


def _normalize_active_types(types: list[SearchResultType] | None) -> list[SearchResultType]:
    """Deduplicate types in enum order so cursor bindings are deterministic."""
    supplied = types or list(SearchResultType)
    try:
        values = {SearchResultType(item) for item in supplied}
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid search result type") from exc
    return [result_type for result_type in SearchResultType if result_type in values]


def _validate_position(
    source: SearchResultType,
    value: Any,
    *,
    site_variant: SiteVariant,
) -> dict[str, Any]:
    """Validate one source position without accepting ambiguous extra fields."""
    if not isinstance(value, dict):
        raise ValidationError(f"Invalid {source.value} cursor position")
    expected = {
        SearchResultType.GENE: (
            {"rank", "score", "accession", "gene_pk", "exhausted"}
            if site_variant == SiteVariant.INTERNAL
            else {"rank", "score", "accession", "assembly_id", "exhausted"}
        ),
        SearchResultType.PUBLICATION: {"rank", "score", "id", "exhausted"},
        SearchResultType.MUTANT_LINE: {
            "rank", "score", "public_id", "exhausted"
        }
        if site_variant == SiteVariant.EXTERNAL
        else {
            "rank", "score", "name", "id", "exhausted"
        },
    }[source]
    if set(value) != expected:
        raise ValidationError(f"Invalid {source.value} cursor position")
    exhausted = value["exhausted"]
    if not isinstance(exhausted, bool):
        raise ValidationError(f"Invalid {source.value} cursor exhausted flag")
    if (
        isinstance(value["rank"], bool)
        or not isinstance(value["rank"], int)
        or value["rank"] not in {1, 2, 3}
        or isinstance(value["score"], bool)
        or not isinstance(value["score"], (int, float))
        or float(value["score"]) != float(value["rank"])
    ):
        raise ValidationError(f"Invalid {source.value} cursor score")
    if source == SearchResultType.GENE:
        tie_key = "gene_pk" if site_variant == SiteVariant.INTERNAL else "assembly_id"
        if value["accession"] is None:
            if value[tie_key] is not None or not exhausted:
                if value[tie_key] is not None:
                    raise ValidationError("Invalid empty gene cursor position")
                return value
            return value
        if not isinstance(value["accession"], str) or not value["accession"]:
            raise ValidationError("Invalid gene cursor accession")
        if (
            isinstance(value[tie_key], bool)
            or not isinstance(value[tie_key], int)
            or value[tie_key] < 1
        ):
            raise ValidationError("Invalid gene cursor tie-breaker")
    elif source == SearchResultType.PUBLICATION:
        if value["id"] is None:
            return value
        if isinstance(value["id"], bool) or not isinstance(value["id"], int) or value["id"] < 1:
            raise ValidationError("Invalid publication cursor tie-breaker")
    else:
        key_name = "public_id" if site_variant == SiteVariant.EXTERNAL else "name"
        if value[key_name] is None:
            if site_variant == SiteVariant.EXTERNAL:
                return value
            if value["id"] is not None or not exhausted:
                if value["id"] is not None:
                    raise ValidationError("Invalid empty mutant-line cursor position")
                return value
            return value
        if not isinstance(value[key_name], str) or not value[key_name]:
            raise ValidationError("Invalid mutant-line cursor name")
        if site_variant == SiteVariant.EXTERNAL:
            return value
        if isinstance(value["id"], bool) or not isinstance(value["id"], int) or value["id"] < 1:
            raise ValidationError("Invalid mutant-line cursor tie-breaker")
    return value


def _decode_global_cursor(
    cursor: str,
    *,
    query: str,
    active_types: list[SearchResultType],
    site_variant: SiteVariant,
    release_id: int,
    assembly_id: int | None,
) -> int | dict[str, Any]:
    """Decode a legacy offset or validate a bound opaque cursor.

    Decimal-only values intentionally retain the pre-A-04 offset behavior.
    Every other malformed value is rejected before source SQL is constructed.
    """
    if not isinstance(cursor, str) or not cursor:
        raise ValidationError("Invalid global search cursor")
    if cursor.isascii() and cursor.isdecimal():
        return int(cursor)
    if len(cursor) > _MAX_GLOBAL_CURSOR_LENGTH:
        raise ValidationError("Global search cursor is too large")
    context = ReleaseContext(release_id=release_id, assembly_id=assembly_id)
    try:
        sort_key = decode_bound_cursor(
            cursor,
            kind="global-search",
            release_context=context,
            filters=_cursor_filters(
                query=query,
                active_types=active_types,
                site_variant=site_variant,
                assembly_id=assembly_id,
            ),
        )
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Invalid global search cursor") from exc
    if set(sort_key) != {"v", "positions"}:
        raise ValidationError("Invalid global search cursor payload")
    if (
        isinstance(sort_key["v"], bool)
        or not isinstance(sort_key["v"], int)
        or sort_key["v"] != _GLOBAL_CURSOR_VERSION
    ):
        raise ValidationError("Unknown global search cursor version")
    positions = sort_key["positions"]
    if not isinstance(positions, dict):
        raise ValidationError("Invalid global search cursor positions")
    expected_sources = {source.value for source in active_types if source in _CURSOR_SOURCES}
    if set(positions) != expected_sources:
        raise ValidationError("Global search cursor sources do not match")
    checked: dict[str, Any] = {}
    for source in _CURSOR_SOURCES:
        if source.value in positions:
            checked[source.value] = _validate_position(
                source, positions[source.value], site_variant=site_variant
            )
    return {"positions": checked}


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


def _gene_match_query(
    query: str,
    pattern: str,
    *,
    release_id: int,
    assembly_id: int | None,
):
    """Return a subquery of the ``gene_pk``s a release-scoped search matches.

    Extracted so the ambiguity aggregate and the page query can never drift
    apart: both must apply the identical text/alias/release scope.

    The text arm and the curated-alias arm are ``UNION``-ed rather than ``OR``-ed
    on purpose. PostgreSQL cannot turn an ``OR`` list containing a SubPlan into a
    bitmap index condition: the whole disjunction collapses into a filter on a
    scan node, so adding the alias test to the text test made every
    identifier-shaped search — the normal case for a search box — read
    ``genes`` end to end and silently bypass the trigram indexes migration 0046
    exists to provide. Measured on 300k genes with ``EXPLAIN (ANALYZE,
    BUFFERS)``: the ``OR`` form planned ``Index Scan using ix_gene_accession``
    with ``Rows Removed by Filter: 299999`` at 760 ms, the ``UNION`` form planned
    ``BitmapOr`` over ``ix_genes_accession_trgm`` / ``ix_genes_name_trgm`` /
    ``ix_genes_description_trgm`` at 9 ms — and forced ``enable_seqscan = off``
    did not recover the ``OR`` form, so this is a structural limit, not a cost
    estimate. Alias equality is still curated data only, never similarity.

    ``lower(alias)`` is matched through the functional index added by migration
    0048; without it this arm would scan ``gene_aliases`` on every search.
    """
    scope = [Assembly.release_id == release_id]
    if assembly_id is not None:
        scope.append(Gene.assembly_id == assembly_id)
    text_match = or_(
        Gene.accession.ilike(pattern, escape="\\"),
        Gene.name.ilike(pattern, escape="\\"),
        Gene.description.ilike(pattern, escape="\\"),
    )
    text_arm = (
        select(Gene.gene_pk)
        .join(Assembly, Assembly.id == Gene.assembly_id)
        .where(and_(text_match, *scope))
    )
    if not _is_exact_accession(query):
        return text_arm
    alias_arm = (
        select(Gene.gene_pk)
        .join(Assembly, Assembly.id == Gene.assembly_id)
        .join(GeneAlias, GeneAlias.gene_id == Gene.gene_pk)
        .where(
            and_(
                func.lower(GeneAlias.alias) == func.lower(query.strip()),
                *scope,
            )
        )
    )
    return union_all(text_arm, alias_arm)


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
        release_id: int | None = None,
    ) -> GlobalSearchResponse:
        """Search across multiple entity types with a short-lived cache.

        External responses are cached per (site, release, assembly, query,
        types, cursor, limit). Internal responses bypass the cache so
        authorized rows can never be served to a different scope.

        ``release_id`` is the request's explicit release scope. When it is
        supplied it is used verbatim -- including for a release that is not
        published yet, whose assemblies/mutant lines are still queryable at
        the SQL level -- so two different releases can never share a response.
        When it is ``None`` the active published release is resolved and used
        instead.
        """
        limit = max(1, min(int(limit), 100))
        active_types = _normalize_active_types(types)
        if release_id is None:
            context = await resolve_release_context(db)
            release_id = context.release_id
        # NOTE: an absent assembly_id deliberately searches every assembly
        # of the release; hits are labelled per assembly and the response
        # reports ambiguity. It is never defaulted behind the caller's back.
        cursor_state: dict[str, Any] | None = None
        legacy_cursor = cursor is not None and cursor.isascii() and cursor.isdecimal()
        page_offset = 0
        if cursor is not None:
            decoded_cursor = _decode_global_cursor(
                cursor,
                query=query,
                active_types=active_types,
                site_variant=site_variant,
                release_id=release_id,
                assembly_id=assembly_id,
            )
            if isinstance(decoded_cursor, int):
                page_offset = decoded_cursor
            else:
                cursor_state = decoded_cursor["positions"]
        cache_params = {
            "query": query,
            "types": [result_type.value for result_type in active_types],
            "cursor": cursor,
            "limit": limit,
            # Defence in depth (cache-site.md I2): with the internal bypass
            # below in force, INTERNAL never reaches the shared store, so this
            # field is currently unreachable for internal callers. It is kept
            # deliberately: the moment the bypass is removed (or another
            # caller routes INTERNAL through get_or_set) an omitted
            # site_variant would silently let internal and external reuse one
            # cache entry. Pinned by
            # tests/test_opt_crossversion_links.py::test_opt02_*.
            "site_variant": site_variant.value,
            "release_id": release_id,
            "assembly_id": assembly_id,
        }

        async def load() -> dict[str, Any]:
            pattern = _contains_pattern(query)
            hits: list[SearchHit] = []
            per_type = max(1, limit // max(1, len(active_types)))
            # New cursors need enough rows from every source to perform a
            # true global merge. Legacy decimal cursors retain their former
            # per-source offset behavior for mixed-version clients.
            source_limit = per_type + 1 if legacy_cursor else limit + 1
            page_limit = per_type if legacy_cursor else limit

            # AsyncSession is intentionally used sequentially here. Running
            # multiple statements concurrently on one session is unsupported.
            has_more = False
            source_positions: dict[str, dict[str, Any]] = {}
            source_pages: dict[
                str, tuple[list[SearchHit], bool]
            ] = {}

            def previous_position(source: SearchResultType) -> dict[str, Any] | None:
                if cursor_state is None:
                    return None
                position = cursor_state.get(source.value)
                if not isinstance(position, dict):
                    return None
                key_name = (
                    "accession"
                    if source == SearchResultType.GENE
                    else "public_id"
                    if source == SearchResultType.MUTANT_LINE
                    and site_variant == SiteVariant.EXTERNAL
                    else "name"
                    if source == SearchResultType.MUTANT_LINE
                    else "id"
                )
                return position if position.get(key_name) is not None else None

            def source_exhausted(source: SearchResultType) -> bool:
                if cursor_state is None:
                    return False
                position = cursor_state.get(source.value)
                return isinstance(position, dict) and position.get("exhausted") is True

            def finish_source(
                source: SearchResultType,
                page_hits: list[SearchHit],
                source_has_more: bool,
                visible_hits: list[SearchHit],
            ) -> None:
                """Record only the terminal row actually returned to callers."""
                previous = previous_position(source)
                if visible_hits:
                    key = visible_hits[-1].metadata.get("_cursor")
                    if not isinstance(key, dict):
                        raise RuntimeError(f"{source.value} result did not provide a cursor key")
                    source_positions[source.value] = {
                        **key,
                        "exhausted": not (source_has_more or len(visible_hits) < len(page_hits)),
                    }
                elif previous is not None:
                    # A non-empty page can be omitted by the global limit; in
                    # that case do not advance this source at all.
                    source_positions[source.value] = {
                        **previous,
                        "exhausted": True if not page_hits else previous["exhausted"],
                    }
                elif source == SearchResultType.GENE:
                    source_positions[source.value] = {
                        "rank": 1,
                        "score": 1.0,
                        "accession": None,
                        "assembly_id": None,
                        "exhausted": not page_hits,
                    }
                elif source == SearchResultType.PUBLICATION:
                    source_positions[source.value] = {
                        "rank": 1,
                        "score": 1.0,
                        "id": None,
                        "exhausted": not page_hits,
                    }
                elif site_variant == SiteVariant.EXTERNAL:
                    source_positions[source.value] = {
                        "rank": 1,
                        "score": 1.0,
                        "public_id": None,
                        "exhausted": not page_hits,
                    }
                else:
                    source_positions[source.value] = {
                        "rank": 1,
                        "score": 1.0,
                        "name": None,
                        "id": None,
                        "exhausted": not page_hits,
                    }

            if SearchResultType.GENE in active_types:
                previous = previous_position(SearchResultType.GENE)
                if source_exhausted(SearchResultType.GENE):
                    gene_hits = []
                else:
                    gene_hits = await self._search_genes(
                        db, query, pattern, source_limit,
                        page_offset if legacy_cursor else 0,
                        cursor_key=previous if cursor_state is not None else None,
                        release_id=release_id,
                        assembly_id=assembly_id,
                        site_variant=site_variant,
                    )
                source_has_more = len(gene_hits) > page_limit
                page_hits = gene_hits[:page_limit]
                has_more = has_more or source_has_more
                source_pages[SearchResultType.GENE.value] = (page_hits, source_has_more)
                hits.extend(page_hits)
            if SearchResultType.MUTANT_LINE in active_types:
                previous = previous_position(SearchResultType.MUTANT_LINE)
                if source_exhausted(SearchResultType.MUTANT_LINE):
                    mutant_hits = []
                else:
                    mutant_hits = await self._search_mutant_lines(
                        db, query, pattern, source_limit,
                        page_offset if legacy_cursor else 0,
                        cursor_key=previous if cursor_state is not None else None,
                        release_id=release_id,
                        site_variant=site_variant,
                    )
                source_has_more = len(mutant_hits) > page_limit
                page_hits = mutant_hits[:page_limit]
                has_more = has_more or source_has_more
                source_pages[SearchResultType.MUTANT_LINE.value] = (page_hits, source_has_more)
                hits.extend(page_hits)
            if SearchResultType.PUBLICATION in active_types:
                previous = previous_position(SearchResultType.PUBLICATION)
                if source_exhausted(SearchResultType.PUBLICATION):
                    publication_hits = []
                else:
                    publication_hits = await self._search_publications(
                        db, pattern, source_limit,
                        page_offset if legacy_cursor else 0,
                        cursor_key=previous if cursor_state is not None else None,
                    )
                source_has_more = len(publication_hits) > page_limit
                page_hits = publication_hits[:page_limit]
                has_more = has_more or source_has_more
                source_pages[SearchResultType.PUBLICATION.value] = (page_hits, source_has_more)
                hits.extend(page_hits)

            hits.sort(key=lambda hit: hit.score, reverse=True)
            hits = hits[:limit]
            visible_ids = {id(hit) for hit in hits}
            # Cross-version links are metadata on the matched gene item, not
            # extra rows: the page/total_count above are already final.
            gene_pks = [
                int(hit.metadata["gene_pk"])
                for hit in hits
                if hit.type == SearchResultType.GENE and hit.metadata.get("gene_pk") is not None
            ]
            cross_version_by_gene = await self._resolve_cross_version_links(
                db, gene_pks, release_id=release_id
            )
            has_more = False
            for source_name, (page_hits, source_has_more) in source_pages.items():
                source = SearchResultType(source_name)
                visible_hits = [hit for hit in page_hits if id(hit) in visible_ids]
                finish_source(source, page_hits, source_has_more, visible_hits)
                has_more = has_more or source_has_more or len(visible_hits) < len(page_hits)
            # Ambiguity is a property of the whole release-scoped match set,
            # not of the truncated page: an unscoped ``limit=1`` page must
            # still reveal that the accession matches several assemblies.
            if SearchResultType.GENE in active_types and assembly_id is None:
                by_assembly = await self._gene_assembly_distribution(
                    db, query, pattern, release_id=release_id
                )
            else:
                by_assembly = {}
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
                        assembly=hit.metadata.get("assembly"),
                        cross_version=cross_version_by_gene.get(
                            hit.metadata.get("gene_pk"), []
                        ),
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
                next_cursor=(
                    str(page_offset + per_type)
                    if legacy_cursor and has_more
                    else _encode_global_cursor(
                        {
                            "v": _GLOBAL_CURSOR_VERSION,
                            "q": _query_fingerprint(query),
                            "types": [item.value for item in active_types],
                            "site_variant": site_variant.value,
                            "release_id": release_id,
                            "assembly_id": assembly_id,
                            "positions": source_positions,
                        }
                    )
                    if has_more
                    else None
                ),
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
        cursor_key: Mapping[str, Any] | None = None,
        release_id: int,
        assembly_id: int | None,
        site_variant: SiteVariant = SiteVariant.EXTERNAL,
    ) -> list[SearchHit]:
        """Search genes with exact > alias > text match typing."""
        # The match set arrives as one indexable subquery instead of an OR of
        # text tests and a correlated alias EXISTS; see _gene_match_query for
        # the measured reason.
        conditions: list = [
            Gene.gene_pk.in_(
                _gene_match_query(
                    query, pattern, release_id=release_id, assembly_id=assembly_id
                )
            )
        ]
        exact_match = (
            func.lower(Gene.accession) == func.lower(query.strip())
            if _is_exact_accession(query)
            else literal(False)
        )
        alias_match = (
            select(GeneAlias.gene_id)
            .where(
                GeneAlias.gene_id == Gene.gene_pk,
                func.lower(GeneAlias.alias) == func.lower(query.strip()),
            )
            .exists()
            if _is_exact_accession(query)
            else literal(False)
        )
        rank_expr = case(
            (exact_match, 3),
            (alias_match, 2),
            else_=1,
        )
        if cursor_key is not None:
            conditions.append(
                or_(
                    rank_expr < cursor_key["rank"],
                    and_(
                        rank_expr == cursor_key["rank"],
                        or_(
                            Gene.accession > cursor_key["accession"],
                            and_(
                                Gene.accession == cursor_key["accession"],
                                (
                                    Gene.gene_pk > cursor_key["gene_pk"]
                                    if site_variant == SiteVariant.INTERNAL
                                    else Gene.assembly_id > cursor_key["assembly_id"]
                                ),
                            ),
                        ),
                    ),
                )
            )
        stmt = (
            select(
                Gene.gene_pk,
                Gene.accession,
                Gene.name,
                Gene.description,
                Gene.biotype,
                Gene.assembly_id,
                Assembly.name.label("assembly_name"),
                Assembly.version.label("assembly_version"),
                rank_expr.label("match_rank"),
            )
            .join(Assembly, Assembly.id == Gene.assembly_id)
            .where(and_(*conditions))
            .order_by(
                desc(rank_expr),
                Gene.accession,
                Gene.gene_pk if site_variant == SiteVariant.INTERNAL else Gene.assembly_id,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # Alias equality (curated data only, never string similarity).
        hits: list[SearchHit] = []
        for row in rows:
            if row.match_rank == 3:
                match_type = MatchType.EXACT
                score = 3.0
            elif row.match_rank == 2:
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
                        "gene_pk": int(row.gene_pk),
                        "release_id": release_id,
                        "assembly_id": row.assembly_id,
                        "assembly": " ".join(
                            part
                            for part in (row.assembly_name, row.assembly_version)
                            if part
                        )
                        or None,
                        "_cursor": (
                            {
                                "rank": int(row.match_rank),
                                "score": float(row.match_rank),
                                "accession": row.accession,
                                "gene_pk": int(row.gene_pk),
                            }
                            if site_variant == SiteVariant.INTERNAL
                            else {
                                "rank": int(row.match_rank),
                                "score": float(row.match_rank),
                                "accession": row.accession,
                                "assembly_id": int(row.assembly_id),
                            }
                        ),
                    },
                )
            )
        return hits

    async def _resolve_cross_version_links(
        self,
        db: AsyncSession,
        gene_pks: list[int],
        *,
        release_id: int,
    ) -> dict[int, list[CrossVersionLink]]:
        """Resolve explicit cross-assembly links for the matched genes.

        One batched query (no N+1) over ``gene_crosswalks`` in BOTH
        directions: a row is relevant whether the matched gene is its source
        or its target. Rows scoped to a different release are skipped;
        ``release_id IS NULL`` means "generic, every release".

        Each endpoint assembly must belong either to the resolved release or
        to another *published* release (v4 and v5 can live in separate published
        releases, which is what makes cross-version links useful). A generic row
        can point at a gene whose assembly exists only in an unpublished
        release; disclosing that accession and assembly would publish a record
        this catalogue does not contain. The assembly/release joins are
        therefore part of the scope, not just display metadata, and equivalence
        is still never inferred from them.
        """
        if not gene_pks:
            return {}
        matched = set(gene_pks)
        source_gene = aliased(Gene)
        target_gene = aliased(Gene)
        source_assembly = aliased(Assembly)
        target_assembly = aliased(Assembly)
        source_release = aliased(Release)
        target_release = aliased(Release)
        stmt = (
            select(
                GeneCrosswalk.source_gene_id,
                GeneCrosswalk.target_gene_id,
                GeneCrosswalk.relation_type,
                GeneCrosswalk.provenance_source,
                source_gene.accession.label("source_accession"),
                source_gene.assembly_id.label("source_assembly_id"),
                source_assembly.name.label("source_assembly_name"),
                source_assembly.version.label("source_assembly_version"),
                target_gene.accession.label("target_accession"),
                target_gene.assembly_id.label("target_assembly_id"),
                target_assembly.name.label("target_assembly_name"),
                target_assembly.version.label("target_assembly_version"),
            )
            .join(source_gene, source_gene.gene_pk == GeneCrosswalk.source_gene_id)
            .join(target_gene, target_gene.gene_pk == GeneCrosswalk.target_gene_id)
            .join(source_assembly, source_assembly.id == source_gene.assembly_id)
            .join(target_assembly, target_assembly.id == target_gene.assembly_id)
            .join(source_release, source_release.id == source_assembly.release_id)
            .join(target_release, target_release.id == target_assembly.release_id)
            .where(
                or_(
                    GeneCrosswalk.source_gene_id.in_(matched),
                    GeneCrosswalk.target_gene_id.in_(matched),
                ),
                or_(
                    GeneCrosswalk.release_id.is_(None),
                    GeneCrosswalk.release_id == release_id,
                ),
                or_(
                    source_assembly.release_id == release_id,
                    source_release.status == ReleaseStatus.PUBLISHED,
                ),
                or_(
                    target_assembly.release_id == release_id,
                    target_release.status == ReleaseStatus.PUBLISHED,
                ),
            )
        )

        def as_link(prefix: str, row: Any) -> CrossVersionLink:
            return CrossVersionLink(
                gene_accession=getattr(row, f"{prefix}_accession"),
                assembly_id=getattr(row, f"{prefix}_assembly_id"),
                assembly_name=getattr(row, f"{prefix}_assembly_name"),
                assembly_version=getattr(row, f"{prefix}_assembly_version"),
                relation_type=row.relation_type,
                provenance_source=row.provenance_source,
            )

        resolved: dict[int, list[CrossVersionLink]] = {}
        seen: dict[int, set[tuple[str, str, str]]] = {}
        for row in (await db.execute(stmt)).all():
            for matched_pk, other_prefix in (
                (row.source_gene_id, "target"),
                (row.target_gene_id, "source"),
            ):
                if matched_pk not in matched:
                    continue
                link = as_link(other_prefix, row)
                identity = (link.gene_accession, link.relation_type, link.provenance_source)
                if identity in seen.setdefault(matched_pk, set()):
                    continue
                seen[matched_pk].add(identity)
                resolved.setdefault(matched_pk, []).append(link)
        return resolved

    async def _gene_assembly_distribution(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        *,
        release_id: int,
    ) -> dict[str, int]:
        """Count gene matches per assembly over the full release-scoped set.

        Ambiguity is a property of the whole match set, not of the current
        page: ``limit=1`` must still report that two assemblies match.

        The release scope now lives entirely inside the shared match subquery,
        so the ``assemblies`` join this query used for the release filter is
        gone: ``Gene.gene_pk`` already carries the assembly.
        """
        stmt = (
            select(Gene.assembly_id, func.count())
            .where(
                Gene.gene_pk.in_(
                    _gene_match_query(
                        query, pattern, release_id=release_id, assembly_id=None
                    )
                )
            )
            .group_by(Gene.assembly_id)
        )
        rows = (await db.execute(stmt)).all()
        return {str(assembly_id): int(count) for assembly_id, count in rows}

    async def _search_mutant_lines(
        self,
        db: AsyncSession,
        query: str,
        pattern: str,
        limit: int,
        offset: int = 0,
        *,
        cursor_key: Mapping[str, Any] | None = None,
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
                # Redundant-by-design defence: the ILIKE below already drops NULL public_id.
                MutantLine.public_id.is_not(None),
                MutantLine.release_id == release_id,
                MutantLine.public_id.ilike(pattern, escape="\\"),
            ]
            exact_match = (
                func.upper(MutantLine.public_id) == normalize_public_id(query.strip())
                if _is_exact_accession(query)
                else literal(False)
            )
            rank_expr = case((exact_match, 3), else_=1)
            stmt = (
                select(
                    MutantLine.public_id,
                    MutantLine.name,
                    MutantLine.description,
                    MutantLine.mutagen,
                    MutantLine.cultivar,
                )
                .where(and_(*conditions))
            )
            if cursor_key is not None:
                stmt = stmt.where(
                    or_(
                        rank_expr < cursor_key["rank"],
                        and_(
                            rank_expr == cursor_key["rank"],
                            MutantLine.public_id > cursor_key["public_id"],
                        ),
                    )
                )
            stmt = stmt.order_by(desc(rank_expr), MutantLine.public_id).limit(limit).offset(offset)
            result = await db.execute(stmt)
            hits: list[SearchHit] = []
            for ml in result.all():
                public_id = ml.public_id or ""
                exact = _is_exact_accession(query) and public_id.upper() == normalize_public_id(
                    query.strip()
                )
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
                            "_cursor": {
                                "rank": 3 if exact else 1,
                                "score": 3.0 if exact else 1.0,
                                "public_id": public_id,
                            },
                        },
                    )
                )
            return hits

        # Internal federated search: kept for internal callers of
        # global_search; matching spans both identities.
        stmt = (
            select(
                MutantLine.public_id,
                MutantLine.id,
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
        )
        rank_expr = literal(1)
        if cursor_key is not None:
            stmt = stmt.where(
                or_(
                    rank_expr < cursor_key["rank"],
                    and_(
                        rank_expr == cursor_key["rank"],
                        or_(
                            MutantLine.name > cursor_key["name"],
                            and_(
                                MutantLine.name == cursor_key["name"],
                                MutantLine.id > cursor_key["id"],
                            ),
                        ),
                    ),
                )
            )
        stmt = (
            stmt.order_by(desc(rank_expr), MutantLine.name, MutantLine.id)
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
                        "_cursor": {
                            "rank": 1,
                            "score": 1.0,
                            "name": ml.name,
                            "id": int(ml.id),
                        },
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
        """Internal mutant search across public_id, internal id and name."""
        stripped = query.strip()
        is_exact = _is_exact_accession(query)
        needle = normalize_public_id(stripped) if is_exact else None
        # Only a bare decimal token is treated as an internal-key lookup, and
        # only within int4 range: a mixed token must not coerce, and an
        # out-of-range literal must not reach the database as a bad cast.
        internal_id_value: int | None = None
        if is_exact and stripped.isdigit():
            candidate = int(stripped)
            if candidate <= 2_147_483_647:
                internal_id_value = candidate
        conditions = [
            MutantLine.is_deleted.is_(False),
        ]
        if is_exact:
            match_conditions = [
                MutantLine.name.ilike(pattern, escape="\\"),
                func.upper(MutantLine.public_id) == needle,
            ]
            if internal_id_value is not None:
                match_conditions.append(MutantLine.id == internal_id_value)
            conditions.append(or_(*match_conditions))
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
        for ml in result.scalars().all():
            matched_field = "name"
            match_type = MatchType.TEXT
            if ml.public_id and needle and ml.public_id.upper() == needle:
                matched_field = "public_id"
                match_type = MatchType.EXACT
            elif internal_id_value is not None and int(ml.id) == internal_id_value:
                matched_field = "internal_id"
                match_type = MatchType.EXACT
            elif ml.name.lower() == stripped.lower():
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
        self,
        db: AsyncSession,
        pattern: str,
        limit: int,
        offset: int = 0,
        *,
        cursor_key: Mapping[str, Any] | None = None,
    ) -> list[SearchHit]:
        stmt = select(
            Publication.id,
            Publication.title,
            Publication.journal,
            Publication.year,
            Publication.doi,
        ).where(
            or_(
                Publication.title.ilike(pattern, escape="\\"),
                Publication.authors.ilike(pattern, escape="\\"),
                Publication.abstract.ilike(pattern, escape="\\"),
            )
        )
        rank_expr = literal(1)
        if cursor_key is not None:
            stmt = stmt.where(
                or_(
                    rank_expr < cursor_key["rank"],
                    and_(
                        rank_expr == cursor_key["rank"],
                        Publication.id > cursor_key["id"],
                    ),
                )
            )
        stmt = stmt.order_by(desc(rank_expr), Publication.id).limit(limit).offset(offset)
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
                    metadata={
                        "year": pub.year,
                        "doi": pub.doi,
                        "_cursor": {
                            "rank": 1,
                            "score": 1.0,
                            "id": int(pub.id),
                        },
                    },
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
                or_(
                    Gene.accession.ilike(pattern, escape="\\"),
                    Gene.name.ilike(pattern, escape="\\"),
                )
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
